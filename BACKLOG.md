# agent-demo 功能完善清单（Backlog）

> **基线**：`main @ ba0b33f`（A2 已提交）+ DDL 笔误修复；M0–M5 已落地；M6 仍为空壳；
> **M7 已全部落地**（调度面五个 job + 成本预算 + 日志归档 + 定时内容推送）
> **规模**：<!-- DOCS-STATS:BEGIN（机器生成勿手改：scripts/check_review_docs.py --write-stats 维护 / --check-stats 核对） -->测试 94 个文件（**3674 收集：3601 通过 + 73 跳过**——`pytest -q` 实测 2026-10-29）<!-- DOCS-STATS:END -->；上一基线 2026-10-07 REVIEW-de09478..workdir 全量修复
> （review/FIX-de09478..workdir.md）为 57 文件 / 2060 收集：2009 通过 + 51 跳过；
> 设 `TEST_DATABASE_URL`（`qqagent_test`）全量套件 2026-10-07 实测 **2051 通过 + 9 跳过**
> （2026-10-11 逐条复核实测 **2151 通过 + 9 跳过**（端口性整改 + 部署脚本落地后复跑），含 wiki/群身份锚点等后续新增用例；
> 2026-10-10 实测 PG 契约子集 `test_pg_store.py + test_store_contract.py` 45 通过），
> `TZ=Pacific/Midway`/`TZ=UTC` 错位时区复跑同数（2026-10-07）；**全新空库**要 `9e93472`（TIMESTZ 笔误修复）之后才能建表跑通。首行计数由脚本实测生成，
> 勿手写估算；PG / 错位时区数字为人工维护并各自注明实测日期。勘误：2026-09-28 的「50 文件 / 1699
> 收集」与 2026-09-30 的「+1 文件 / +12 收集」均为当时手写口径，与实测不符——该
> 区间实际新增 3 个测试文件（`tests/test_config_write.py`、`tests/test_reboot.py`、
> `tests/test_ssh_skill.py`），以本行实测数为准）。
> **工具面**：34 个内置工具（`@registry.register` 装饰器调用点，grep 实测，含
> 新增的 `run_shell`）+ 4 个默认安装的 prompt 技能 + search_web/search_multi
> （`install` 注册，配 `SEARCH_API_KEY` 才有）+ wiki_prts/wiki_blhx
> （`install` 注册，`AGENT_WIKI_SITES` 控制，缺省 `prts,blhx` 启用）
>
> **更新说明（2026-09-11，按代码实测重写）**：上一版基线停在 `c0978c9`（314 测试），
> 其中「§0 已发现缺陷」「CI + pre-commit」「M5 RAG」「M7 的调度/归档/备份」**均已落地**，
> 原「建议落地顺序」已作废。旧版内容保留在 git 历史（`git show c0978c9:BACKLOG.md`）。
> 本版分两部分：§1–§4 是**还没做的事**，§6 是**评审已实证、属于必修而非新功能**的缺陷。

优先级图例：**P0** 影响正确性/数据/安全 → 立刻做；**P1** 影响可用性/可维护性 → 近期做；**P2** 锦上添花。

---

## 0. 已完成（仅记结论，不再展开）

| 项 | 状态 |
|---|---|
| 原 §0 全部缺陷（P0-1 历史窗口取反 / P0-2 索引 / P0-3 session 竞态 / P1-4 连接池泄漏 / P1-5 静默异常 / P1-6 停机回收 / P2-7 文档不一致） | ✅ 已修 |
| **群统计双周视图**（2026-10-20） | ✅ Web 群统计 tab 同时展示**上周（完整）+ 本周（进行中）**：`build_group_stats` 返回 `windows[{key,label,start,end,groups}]`（保留旧 `window`/`groups` 兼容），每群两列并排（条数/人数、Top5、词云、小时直方图），只在单周出现的群另一侧标「无记录」；QQ `/发言榜 本周` 原本已支持，无需改。回归：`tests/test_web.py` 的群统计用例补本周 seed 与窗口断言；临时实例截图 `stats-two-weeks.png` |
| **设置簇 + 多 LLM Provider**（2026-10-19，P1+P2 续） | ✅ 已落地：设置页改为 **17 个业务簇**（折叠 + 锚点 + 跨簇搜索），有总开关的簇把 gate 排第一，关闭时同簇其余项灰置 **且后端拒写**（409 `cluster_disabled:<gate>`，gate 值从文件读、不读 stale environ）。新增显式开关 `AGENT_MUSIC_ENABLED` / `SEARCH_ENABLED` / `AGENT_PERSONA_GROWTH_ENABLED`（默认开；前两个调用时生效，人格开关启动期生效，抽出 `_growth_active()` 以便单测关闭分支）。多 LLM：`data/llm-providers.json`（0600、原子写、备份、写后重读校验、symlink fail-closed）+ `agentcore/llm/protocols.py`（OpenAI Chat 与 Anthropic Messages 双向适配：system 提升、tool_use↔tool_calls、连续 tool_result 合并、stop_reason/usage 归一化）；provider CRUD/设主/排序/测试连接走 web（两段确认，**key 只写不回显**，GET 只出 `key_set`），`/model <id|model>` 与 `/model reset` 兼容；首次启动从 `LLM_MODEL(S)/FALLBACK` 自动迁移（幂等，损坏回落 env）。回归：`tests/test_llm_providers.py`（16）/`tests/test_llm_protocols.py`（11）/`tests/test_llm.py`（+7 路由）/`tests/test_web.py`（+12 簇/gate/provider）/`tests/test_search.py`、`test_music_route.py`、`test_admin_import.py`（+开关）；conftest 新增 `AGENT_LLM_PROVIDERS_FILE` 隔离 + 共享客户端重置。**变异复核 14/14**（簇 gate / 排序 / 文件读取 / 前端灰置标记 / 搜索 / 点歌 / 成长开关 / key 回显 / Anthropic 结果合并 / 迁移幂等 / reload 跟随文件 / 协议分派 / usage 归属 / 留空 key 保留）。**遗留**：provider 面板的编辑用 `prompt()` 串行输入（可用但不算优雅），后续可做行内表单 |
| **全部设置上 Web**（2026-10-19，P1+P2） | ✅ 已落地：单一 schema —— `plugins/qq_agent_adapter/settings_spec.py` （`ENV_SPECS` 165 键（落地时 161，后续 +3 开关 + provider 文件）：kind/group/label/description/default/live/writable/secret/min/max；由 `.env.example` 引导生成后改为手工维护）+ `config_yaml.py`（`YAML_SPECS` 35 个标量路径）驱动设置页动态渲染，终结「`.env.example` 注释 / `WRITABLE` / 前端 JS 数组 / docs 表格」四处手抄（本轮实测：加 `LLM_MODEL` 只改了后端，前端编辑列表漏了）。可写 **105 env + 29 yaml**（落地时点 2ed7c63 实测）；**18 个凭据/端点类连键名都不进响应体**（`secret`），42 个只读项（ACL/权限级别/写面门禁/数据保留期/日志正文开关/SSRF 白名单/结构路径/`LLM_MODELS`）可见不可写，一律 SSH。`live` 标注决定「即时 / 重启生效」，`apply_runtime` 对 boot 键返回 `boot`（不再一律谎报 live）；boot 项保存后页面提示重启并提供按钮。`config.yaml` 走**文本级逐键补丁**（保注释/空行/顺序）+ 写后 `yaml.safe_load` 校验 + 失败还原；`yaml:` 前缀让两类文件共用同一套两段确认/审计/回滚（确认码绑定整个 key，不需要额外 scope 维度）。回归：`tests/test_config_yaml.py`（新建 16）/`tests/test_web.py`（+12：schema 覆盖 `.env.example`、凭据名与值都不出、live/boot 标注、ACL 可见不可写、YAML 写/只读/非法值）/`tests/test_config_write.py`（+5：boot 不谎报、float、validator 语义、secret 不可写）。**变异复核 6/6**（secret 进 payload / 全谎报 live / YAML 跳过写后校验 / 补丁丢行内注释 / 端点键变可写 / schema 与 `.env.example` 漂移）。文档：README、AGENTS 配置与 Web 行、`docs/configuration.md`、`docs/features-interaction.md`（设置/写入两节重写）、`docs/features-skills.md`、`docs/features-community.md` |
| **模型页 Embedding / 搜索配置**（2026-10-21） | ✅ 已落地：web「模型」标签在 M1 对话模型 / M2 Providers 之外新增 **M3 Embedding**（端点/key/模型/维度）与 **M4 多搜索源**（format/端点/key/启停）CRUD 面板，编辑走 modal 表单（挂 body 下，不受 5s 轮询清空），可增删改、排序、测试连接，**按列表顺序 fallback**（一个源失败自动切下一个，全挂才报错）。四个凭据键 `SEARCH_API_KEY` / `SEARCH_BASE_URL` / `EMBEDDING_BASE_URL` / `EMBEDDING_API_KEY` 从「走 SSH 不可写」放开为 **web 可写**（`writable=True`，仍 `secret=True` 不回显，加 `max_len`）；可写 env 键 105→**109**。搜索主路径走 `data/search-providers.json`（0600、原子写、备份、写后校验、启动期从 env 迁移，与 llm-providers 同构；**无 active，顺序即优先级**），`search.py` 的 `search_web`/`search_items` 遍历 enabled 源 + fallback，`_search_bocha`/`_search_tavily`/`_search_stepfun`/`_search_items_one` 按 format 分派（bocha/tavily/stepfun 三种格式各一套请求/解析）、端点用 `base_url or 默认`；env 单配置（`SEARCH_PROVIDER`/`SEARCH_API_KEY`/`SEARCH_BASE_URL`）为回落兼容（文件缺失时作单源）。数据来自 `build_settings()` 新增 `model_config` 块——**字段名刻意避开 `base_url`/`api_key` 子串**（用 `endpoint_set`/`key_set`），凭据只报「已设置/未设置」，守住 `test_no_secrets_in_payload`「响应体不得含 api_key/base_url」不变量。embedding client 与搜索 `_state` 均启动期/首次调用装配，故 `live=False`（**改后重启生效**，页面标注）。回归：`tests/test_web.py`（+4 model_config / 四键可写 / 写入落盘 / `SEARCH_BASE_URL` 写入 + `TestSearchProvidersWeb` +5：save/编辑保留 key/H2 防护/删除末位拒/reorder）+ `tests/test_search.py`（+7：读配置 / 自定义端点 / 默认端点 / fallback 切下一个 / 全挂报错 / stepfun 请求+解析）+ `tests/test_search_providers.py`（新建 17：校验/迁移/load-save/0600/ensure_migrated/stepfun format）。**变异复核**：`SEARCH_API_KEY` 改回不可写 → 2 用例红；`_search_bocha` 端点改回硬编码 → `test_bocha_uses_custom_endpoint` 红（均还原后复绿）；实现期实测缺陷 1 处——改 spec 时多传位置参数把 `"..."` 落到 `live` 位（truthy）致 `effective` 谎报 `live`，被写入用例抓住后修复。文档：AGENTS 配置与 Web 行、README、`docs/features-interaction.md`（模型 tab + 凭据/可写数两节） |
| **web 写面 2FA（TOTP 双因素）**（2026-10-21） | ✅ 已落地：两段确认升级为 2FA——第一段发 challenge（HMAC 绑定 nonce\|key\|值，防篡改），用户私聊 bot 发 `/2fa`（superuser）获取 5 分钟 TOTP 滚动码填入网页，后端验证 TOTP 码 + challenge + nonce 防重放。`agentcore/totp.py`（RFC 4226 HOTP，300s 步长，±1 窗容忍）；secret 存 0600 文件 `data/2fa-secret.json`（gitignore，首次自动生成，`AGENT_2FA_SECRET_FILE` 可覆盖）。7 个写入路由（settings/write、llm/search providers、personas save/delete/group、reboot）全部接入；前端 confirmDialog 加 TOTP 输入框返回码（reboot 意图段用原生 confirm 不涉 2FA）。回归：`tests/test_totp.py`（新建 7）+ `tests/test_web.py`（两段确认测试批量加 totp_code + `test_m1_confirm_single_use` 改 nonce 防重放）+ `tests/test_reboot.py`（+totp_code）；变异复核：totp.verify 恒真 → 2 用例红。文档：AGENTS Web 行 |
| **运行期切模型**（2026-10-19） | ✅ 已落地：`LLM_MODELS` 候选池（`模型[@base_url[|api_key]]`）+ 活跃位 `LLM_MODEL`（可写 `模型[@base_url]`，**不接受 key**）；降级链 = 活跃位 → 刚换下的旧主 → 池内其余（书写序）→ `LLM_FALLBACK_*` 独立线，仅活跃位保留 2 次瞬时重试；`/model`（查看）/`/model <条目>`（探测通过才切）/`/model reset`（回 `.env` 装配值）均 superuser；探测 20s （`AGENT_MODEL_PROBE_TIMEOUT`）失败即原地不动；落盘复用 `config_write`（备份/原子写/写后验证/失败还原）并进 `WRITABLE` 第 8 键，web 写它同样先探测再落盘；`model_status()` 与 `chat()` 同源（`_effective` 活跃位），usage 按实际候选分账；`embeddings()` 模型名改 import 期快照。回归：`tests/test_llm.py`（+20）/`tests/test_model_switch.py`（新建 17）/`tests/test_admin_import.py`（+16）/`tests/test_web.py`（+3）/`tests/test_config_write.py`；**变异复核 12/12**（旧主排最前 / 端点 key 继承 / usage 归属 / 探测失败被吞 / 池成员校验 / 落盘跳过 / 运行态同步跳过 / 活跃位带 key / self 过滤漏挂 / embedding 跟着活跃位漂 / `set_active` 重复调用抹掉旧主 / switch 后不确认运行态）。**实现期实测缺陷 1 处**：`_persist` 的 `apply_runtime` 已同步一次活跃位，`switch_active_model` 返回前又 `set_active` 一次，旧主从降级链上消失——改为「与当前相同则保留 `_previous`」，回归见 `test_real_apply_runtime_keeps_old_model_in_chain`。两条教训：① 编排层测试忘桩 `AGENT_ENV_FILE`，一条用例走了真实 `write_env_key` 把仓库 `.env` 的 `LLM_MODEL` 改成测试值（已从 `data/backups/config` 还原，两个误建备份已删）——现已加 autouse 夹具关进 tmp；② 只桩掉 `apply_runtime` 的用例抓不到「同步被调了两次」这类缺陷，必须留一条让运行态同步真跑的集成用例 |
| 工程安全网：GitHub Actions + pre-commit + ruff pin | ✅ 已加 |
| **M5 RAG** | ✅ 已完成，超出原计划（蒸馏 / 两层脱敏 / 不可信围栏 / `/kb`） |
| **M7 的调度面** | ✅ 已落地：`kb_digest`（03:00）、`archive_prune`（03:20）、`db_backup`（03:30）、`reminders`（30s tick）四个 job 全接线（`plugins/qq_agent_adapter/__init__.py:177-216`），`ReminderService` 已接 `sink`（`scheduler/reminder.py:199-209`） |
| **M7 的归档面** | ✅ 已落地：7 天滚动归档（`memory/archive.py`）+ pg_dump/JSONL 双路备份 + 异地镜像 + `restore` / `restore-archive` CLI |
| **M7 的定时内容推送** | ✅ 已落地：`agentcore/scheduler/push.py`（LLM 生成 + 模板兜底 + 预算熔断回退）、复用 `schedules` 表（`action='push'`，**无 DDL 变更**）、`/push list\|off\|run\|help` 管理命令、ALLOWED_GROUPS ACL + 每目标每日上限 + 失败退避停用告警 |
| §6 双轨工具系统 | ✅ 旧 `agentcore/tools/` 已删除，收敛到 skills |
| `/status` 真实化、`/persona`、30+ 工具 | ✅ 已做 |
| **P0 权限缺口**：config.yaml `skills.permissions.superusers: ["*"]` 把 registry 层 superuser 门对所有人敞开，ops/log_tail/db_query 曾对白名单群全体成员可用（复现见 FIX 文档） | ✅ 已修（2026-10-05，见 `review/FIX-permission-levels-202610.md`） |
| **MediaWiki 在线直查外挂**：`wiki_prts`/`wiki_blhx` skill（三层降级检索 + wikitext 转 MD + 按预算截取；限速/24h 缓存/429 退避；engine `_result_needs_fence` 围栏）+ 精选子集落库 `scripts/sync_wiki_subset.py`（kind=`wiki`，转换后正文 sha256 判重、变更自动替换先写新后删旧、`--prune` 只动本站清单外来源、重定向按最终标题入库、有意不 PII 掩码保数值） | ✅ 已完成（2026-10-10；`tests/test_wiki_skill.py` 32 例 + `tests/test_wiki_sync.py` 14 例，5 处变异复核全被抓） |
| **CI #91 存量红修复**（7 个用例「本地绿 CI 红」，`0b9f29e`/`babf957` 引入、与 wiki 无关）：① conftest autouse「`.env` 存在就 load_dotenv」把 `DATABASE_URL` 泄漏进本地测试进程，CI 无 `.env` → restore 门用例先 `SystemExit(2)`；② run_shell 依赖仓库里恰好存在 gitignore 掉的 `data/workspace`（cwd 不存在 spawn 即炸）。修法：run_shell 按需创建工作区目录（对全新部署同样是真实修复）；两个测试文件改密闭夹具（`WORKSPACE_DIR` 指向不存在的 tmp 目录、显式 `monkeypatch.setenv DATABASE_URL`） | ✅ 已修（2026-10-10；变异复核：去掉 mkdir 后 4 用例必失败；教训入册 AGENTS.md §5） |
| **群聊身份锚点**（2026-10-10 群 2000000002 事故：模型把群上下文里其他成员的消息当成提问者本人的聊天记录来评价）：① 群上下文围栏后追加「均不是当前提问者本人发送」排除句；② 系统提示注入提问者群名片（`当前提问者：名片（QQ:号）`，名片按引用围栏同口径清洗 + 连串折叠防伪造分隔线，经 pipeline→matcher→engine.context 透传）；③ 群聊能力边界声明（「无法查看任何成员的普通群聊记录」） | ✅ 已完成（2026-10-10；`tests/test_pipeline.py::TestGroupContextIdentityAnchor` 6 例 + `tests/test_engine.py::TestGroupIdentityAnchor` 4 例，4 处变异复核全被抓——含 1 处测试串修正：`-----` 放首段会被 `strip("._-")` 顺带剥掉而漏测折叠逻辑） |
| **「你自己」身份锚点**（2026-10-15 群 2000000003 事故：用户引用 bot 的上一条回复说「我们没崩吧」，系统提示只有提问者身份、被引内容虽全文在围栏里但标题写「消息发送者 云崽（QQ:1000000002）」，模型把「云崽」当外部实体，理解成「用户和别人」——不是读不到内容，是认不出是自己说的）：① 系统提示注入 bot 自身 QQ 号锚点（`你自己的身份：你的 QQ 号是 <self_id>` + 「我们」默认含双方声明，self_id 经 pipeline→matcher→engine.context 透传，非 ASCII 数字不注入）；② 引用被引发送者 uid == self_id 时围栏头部追加「这条是你自己之前发的」（fail-closed：sender 缺失/脏 uid 不标注，错标比漏标更糟）。群流方案经代码核实取消——`_record_group_rule` 早已用 `_is_self_message` 排除 bot 自身发言 | ✅ 已完成（2026-10-15；`tests/test_pipeline.py::TestReplyResolution` 3 例 + `tests/test_engine.py::TestGroupIdentityAnchor` 3 例 + `tests/test_matcher.py::TestSelfIdPassedToEngine` 2 例，4 处变异复核全被抓：删标注 / 恒 True 错标别人消息 / 删引擎锚点 / 不透传 self_id） |
| **权限三级收束**：`AGENT_PERMISSION_LEVEL`（low/medium/high，缺省 medium）替代 `AGENT_SYSTEMCTL_UNITS`/`AGENT_DOCKER_CONTAINERS`/`AGENT_KILL_PATTERNS`/`AGENT_BUILD_SCRIPTS` 四个目标白名单；`run_shell`（high 专属）；`system_status` 收编管理员专属；服务/容器控制加自保护（拒 bot 自身 unit 与 `PG_CONTAINER`） | ✅ 已完成（同上） |
| **npm 全局包更新下沉 medium**（`npm_update` skill，2026-10-18 管理员决策）：`AGENT_NPM_GLOBAL_PACKAGES` 登记表制（空 = 不注册；LLM 只能精确选表内条目、不能拼——`deepseek-ai/dsh` 这类 GitHub shorthand 亦可，但它不走 registry、版本不被 lockfile 钉死）；执行 `npm update -g <包>`，`dry_run` 只预演、布尔字符串归一。刻意与 `run_command` 相反的取舍：**真实 HOME**（尊重 `~/.npmrc` 的 prefix/registry——沙箱化会让 npm 回落 `/usr/local` 装错位置/EACCES）+ **不强制 `--ignore-scripts`**（登记即信任上游账号，全局 CLI 常靠 postinstall 装平台二进制）；90s 超时杀进程组 + 输出 4000 字符截断过围栏 + 最小 env（不泄漏 LLM key）+ 审计 uid。残留：防不住上游仓库自身投毒、全局覆盖式更新不可回退 | ✅ 已完成（2026-10-18；`tests/test_action_skills.py::TestNpmUpdate` 11 例，3 处变异复核全被抓〔精确匹配恒真放行 / env 泄漏 / dry_run 归一去除〕——含 1 处测试串修正：拒绝路径补「不得 spawn」断言，防变异时真实执行 npm） |
| **元流程门禁与不变量机械化**（2026-10-11，源自通用规范评审的三条建议落地）：① `scripts/check_review_docs.py` 把「M14 索引断裂 / §7 产物散落 / 文档地图断链 / M13 计数漂移」变成归档前必跑的自检（挂 pre-commit + CI `--check-stats`）；② `tests/test_repo_guards.py` 把三条高复发铁律变成 CI 可执行断言（`agentcore` 禁 import nonebot〔唯一豁免 file_sender 且必须 try 保护〕、plugins 禁直接 `finish(权限拒绝)` 必须走 `acl.deny`、代码读取的 env 必须出现在 `.env.example`〔唯一豁免 `LLM_EMBEDDING_MODEL` 已知死代码〕）；③ REVIEW-WORKFLOW 增加 L 级收敛规则（>10 条出批量关闭计划 / 同一 L 不得连续两轮遗留 / >15 触发专项整改）；④ BACKLOG 头部计数改为 DOCS-STATS 机器生成块；⑤ 补齐 4 个漏文档 env（`AGENT_PUSH_STATE_FILE`/`AGENT_SCHEDULER_TZ`/`AGENT_TURN_TIMEOUT`/`AGENT_WEB_BACKUP_DIR`） | ✅ 已完成（2026-10-11；`tests/test_repo_guards.py` 探测器均经投毒夹具验证，真实文件变异 3/3 被抓；自检脚本 3 个检查面变异 3/3 被抓） |
| **平台可移植性与模板安全整改**（2026-10-11，端口性评审落地；Windows 阻塞项按管理员决定暂缓）：① `_scan_pids` 补 `/proc` 缺失容错——macOS 上 proc_kill 不再抛 FileNotFoundError（回归用例 + 变异复核）；② 4 处 `time.localtime` 显示收敛到 `agentcore.tz.fmt_ts`（UTC 服务器 + 上海日键场景下显示与日键同源）+ `test_repo_guards.py` 新增「禁 localtime」机械守卫；③ `.env.example`/README 清除作者个人标识（`SUPERUSERS=1000000001,10002` → 留空 + 「填你自己的号」告警、istore/192.168.1.2/xiaji 的 ssh 示例 → myserver/10.0.0.2/you、ONEBOT token `123456` → 留空）——照抄模板不再把陌生人设成超管；④ README 新增「平台支持与移植边界」一节（七能力 × 三平台支持矩阵 / 移植到其它聊天平台的三步 / 部署假设：单账户、CWD 相对路径、默认时区、reboot 链）；⑤ `config.yaml` 顶部补相对目录按 CWD 解析的说明 | ✅ 已完成（2026-10-11；新用例变异 3/3 被抓，`backup_db.py list` 冒烟通过。遗留：Windows 2 处阻塞〔`os.O_NOFOLLOW` AttributeError、权限位语义缺失〕按决定暂缓，README 支持矩阵已如实标注） |
| **一键部署脚本 `scripts/deploy.py`**（2026-10-11）：子命令 `env / check / install / db / systemd / smoke / all`——幂等、纯标准库（venv 建成前就能引导自身）；两条硬边界：**不自动启动 bot**（`all` 到 smoke 为止，systemd 只生成/安装 unit 不 enable/start，fail-loud 防带着占位配置静默跑）、**不写仓库外文件**（`systemd --install` 唯一例外且需 root）；unit 零密钥（`EnvironmentFile=.env`）+ `ProtectSystem=strict`/`ReadWritePaths=<repo>/data` 硬化 + `Restart=always`（对齐 /reboot 执行链末端）；`check` 区分 strict（放行门）/soft（all 流程配置类降级为 warn），识别 `LLM_API_KEY=...` 占位符与 `SUPERUSERS=*` 残留；`tests/test_deploy.py` 18 例（env 解析/DSN/unit 安全面/不覆盖/soft 分级）+ 5 处变异复核全被抓（其中抓到真 bug 一处：`with_suffix` 对点文件 `.env` 不替换后缀导致备份名变成 `.env.env.bak-*`） | ✅ 已完成（2026-10-11；README「一键部署」小节同步） |
| **群发言榜 + 词云**（2026-10-12，opt-in 默认关）：`/发言榜`、`/词云` 群命令（PIL 渲染图片，base64 CQ:image 发送）+ 周一 9:00 cron 周报（Sink 三态投递）+ `/agent-web`「群统计」只读 tab + **`my_group_review` skill**（用户说「点评我一下」时由 LLM 判断调用，个人周报卡片图；schema 无 user_id 参数=越权面归零；昵称/话题词进 prompt 前过 `safety.fence_untrusted` 围栏（含行中值 scrub）；预算硬闸门熔断放弃生成且不缓存、事实卡照发；同周评语落 `group_reviews` 缓存，重复查看零 LLM 成本；usage 记 `group_stats_review` 路由）+ **周报推送白名单** `AGENT_GROUP_STATS_WEEKLY_GROUPS`（空=不推 fail-closed；只管推送，采集/命令/skill 仍按 ALLOWED_GROUPS；条目 ASCII 数字校验）+ **群消息原文归档** `AGENT_GROUP_ARCHIVE`（独立 opt-in，仅 PG：白名单群每条非 bot 消息落 `group_messages_raw`，保留 30 天；PK (group_id, message_id) 幂等去重 + 四条查询索引；合并转发照常归档但不展开内容、被引只记 reply_to——被引/被转发内容从不进词云与 prompt；停机 flush 不丢、kill -9 丢 ≤ flush 周期；聚合管线不变，归档用于对账/回溯/点评增强〔路线甲〕）+ **点评 archive 增强 5 项**（本人高频词〔归档 text 重切，与词云同口径〕/转发次数/发图次数/被引用次数/代表性原句；全部过围栏；归档关闭时 prompt 与增强前一致）。**行为变更（从 X 改为 Y）**：群聊上下文「群消息绝不落库」（group_context docstring）→ **白名单群聚合落库**——隐私收敛为三条：仅 `ALLOWED_GROUPS`、只存聚合（每用户每日条数/字数/小时直方图 + jieba 词频，**消息原文不进任何存储**）、35 天 retention；合并转发消息整条不采集（转发内容不是本人发言），引用照常。采集挂在既有 `group_recorder`（不新增 matcher，零额外事件开销）；存储独立模块 `agentcore/groupstats/`（PgStatsStore/InMemoryStatsStore 语义一致、参数化测试；PG 失败启动降级内存）；flush 走独立 interval job，停机 flush 插在 `lifecycle.shutdown_agent` 的 debounce flush 与 memory.aclose 之间（失败合并回内存，重试不双计）；jieba 为新增依赖（纯 Python，缺失降级 bigram）；词云用墨阶三色 + 确定性等环间距螺旋布局（无随机数，同输入同输出）；点评 skill 住 plugins 层注册（发图要 Sink，遵守 agentcore 不 import nonebot 铁律，照点歌 skill 先例） | ✅ 已完成（2026-10-12；`tests/test_group_stats.py` 64 例含 PG 双实现 + `test_group_stats_render.py` 27 例 + `test_group_stats_review.py` 33 例 + `test_group_stats_route.py` 49 例 + `test_group_archive.py` 37 例含 PG + `test_lifecycle.py` 5 例 + `test_web.py` 6 例；变异复核 49/49 被抓；README 功能小节 + `.env.example` 17 键同步） |
| **性能复查落地：内存后端向量检索 + 每轮重复 embedding**（2026-10-12）：① `InMemoryMemoryStore.recall_facts`/`kb_search` 原为**纯 Python O(N·dim) 且同步跑在事件循环里**（5000 块 × 2048 维实测单次检索 1.66s、2000 条 facts 召回 0.67s，期间整个 bot 冻结）→ 写入时预计算向量模长（新 `_pair_sim` 每候选只做一次点积，省两趟遍历）+ 快照后 `asyncio.to_thread` 外包（实测检索 1.66s→0.67s、召回 0.67s→0.26s，且不再阻塞事件循环；PG 后端走 HNSW 不受影响）；② 引擎每轮把**同一条 user_message** 分别用于 facts 召回与 KB 检索、各 `embed` 一次 → 改为算一次向量两处复用（`_recall_facts`/`_recall_knowledge`/`KnowledgeBase.retrieve` 均新增可选 `query_embedding`），并把 facts 召回并入原有 `asyncio.gather`（每轮少一次 embedding 往返）。**语义不变**：空向量/维度不符/零模仍按旧 `_cosine_sim` 口径得 score=0.0（threshold=0.0 时仍入列），双实现契约测试全绿 | ✅ 已完成（2026-10-12；`test_engine.py::test_query_embedded_once_per_turn_for_facts_and_kb` + `test_memory.py` 两条边界口径用例，变异复核 2/2 被抓） |
| **性能基线门禁抗抖动**（2026-10-12）：`scripts/perf_baseline.py` 单次采样受 CPU 竞争/调度影响，同一指标相邻两次可差 2 倍（实测 `qq_plain_ms` 30/60ms 交替，一次报 2.27x 劣化、另一次无劣化）→ 新增 `--repeat`（默认 3）**多次采样按指标取中位数**再对比，消除纯抖动假阳性 | ✅ 已完成（2026-10-12；`test_perf_baseline.py::TestMedianMetrics` 5 例；三次实测已无假阳性） |
| **F1 用户自定义工具型技能（`data/skills/*.py` 加载器）**（2026-10-16）：与 prompt 型（`*.yaml`）并列的**代码型**介质——`agentcore/skills/local.py` 按路径 importlib 加载目录下 `*.py`（flat 不递归、字典序），调模块级 `register_skills(registry)`；适配器 `_init_agent` 在 prompt 型 manifest 之后接线（两种介质同名都按「先到先得」，后者被拒+WARNING）。安全边界：① 包装注册表在 `register()` 入口拒同名（dict 赋值永不发生，内置对象完好——防本地 `ssh_run.py` 静默顶掉内置提权），**冲突点直接 WARNING 明示技能名**（加载器再报所在文件）；② 目录解析后落在 fs 可写工作区内（含相等）→ 拒绝加载全部 `.py`（否则聊天内容可经 `fs_write` 预埋代码，启动即执行）；③ 坏文件 WARNING 跳过不阻断启动；④ 默认 `read_only=False`（opt-in `mark_read_only` 透传）；⑤ 信任模型=部署者自担（同改源码/装插件），不做沙箱不管依赖。非目标：无热重载（重启生效）、`skillinstall` 不管 `.py`（文件系统即管理界面）。模板与 env key 纪律（key 只走 `.env`，tool call 参数全量落 `agent.log`）见 `docs/features-skills.md` 新节 | ✅ 已完成（2026-10-16；`tests/test_local_skills.py` 19 例覆盖 A1–A3/S1–S4/O1，变异复核 3/3 被抓〔去同名检查 → S1/S2 红；去掉 try/except → A2 全红；去冲突点 WARNING → S1/S2 红〕；全量默认套件 2473 通过 + 58 跳过；README 功能索引 + 目录树同步） |
| **F2 `/skill list` 已安装技能查询命令**（2026-10-16）：补上 skill 管理命令族的「查」——`plugins/qq_agent_adapter/admin.py` 新增 `/skill list`，按介质分两组输出：prompt 型（`*.yaml`，SkillInstaller 缓存，名称+描述，即时生效）与代码型（`*.py`，仅文件名，重启后生效；`installed.yaml` 记账文件不列），空目录给明确文案。权限与 install/uninstall/info 同门=superuser only（M3：manifest 权限串只回 superuser）。同时明确**「链接安装」刻意不做**并写入 `docs/features-skills.md` 新节：LLM 是不可信执行者（输入含群聊不可信内容），让它「决定装什么」=不可信内容驱动持久配置；远端 yaml 的 `prompt` 原样进 system prompt 不过围栏（`registry.py` `_run_prompt_skill`）；`.py` 链接=启动即任意代码执行。安装入口保持确定性命令+superuser 门禁 | ✅ 已完成（2026-10-16；`tests/test_admin_import.py::TestSkillListCommand` 5 例〔非 superuser 拒/未授权走 deny/空目录文案/两种介质分组+installed.yaml 不列/AGENT_SKILLS_DIR 显式〕，变异复核 2/2 被抓〔去 superuser 门 → 拒权例红；不列 py → 分组例红〕；help 文本 + help_render + features-messaging 命令清单同步） |
| **工具调用与回合耗时日志**（2026-10-16，A 方案）：`LLM step` / `skill call` / `[reply]` 三类行补耗时（此前全仓日志点无一记时，"这轮为什么慢"只能靠猜）——① 步骤级 `LLM step 0: 1.83s \| content=None \| tool_calls=['fetch_url', 'search_web']`（工具名进日志替代只有布尔；无工具 `tool_calls=none`；LLM 调用失败分支也带耗时）；② 工具级 `skill done: fetch_url (0.42s) -> ok, 1234 chars`——计时放 `_exec_tool` 内部，串行/并行两路径天然全覆盖；错误态按 registry 返回值 `Error:` 前缀判定（`registry.execute` 把 handler 异常兜成字符串），`skills.execute` 自身抛异常折成 `Error: tool 执行异常（类型）` 工具结果、不炸整轮；`skill denied (skip re-exec)` 与 `skill call: <名> <args>` 两行原样保留（卡住时只有开始行没有 done 行即为信号）；并行批另加 `parallel batch: [a, b] (0.55s)`（与各工具耗时并列才看得出并发省了多少）；③ 回合级 `[reply] … \| engine=1.23s \| total=4.72s`（`engine`=产出回复，`total`=从收到消息算起含防抖窗口/闸门排队/出站投递；起点 `_recv_monotonic` 由 `handle_chat` 写进 payload，`_run_and_format` 另建 context 故不进 prompt；缺键时回落成 engine 起点而非 `-`）。耗时统一 `time.monotonic()` 差值 + `agentcore.tz.format_duration` 分档显示 `0.42s`/`12.35s`/`1m05s`（负值夹 0）；全部 INFO、不加开关 | ✅ 已完成（2026-10-16；`tests/test_engine.py::TestTimingLogs` 5 例 + `tests/test_matcher.py` 3 例，变异复核 4/4 被抓〔抹步骤耗时 / 错误态判定恒 False / 起点标记丢失 / 负值不夹 0〕——其中"起点标记丢失"首轮**未被捕获**（测试直接给 payload 塞标记，没覆盖 `handle_chat` 写入），补 `test_handle_chat_marks_recv_time_on_payload` 后被抓；全量 2486 通过 + 58 跳过；`docs/operations.md` 新增「耗时日志」小节 + README 文档表同步） |
| **解压线整体退役外部 zip/unzip/tar（方案 B）**（2026-10-18，REVIEW-6745556..d730827 H1 管理员拍板）：历轮 4 个 H（zip `-T/-TT`、扫描超限告警放行、展平 flag、通配符 archive 名）全部源于「Python 预扫描 vs 外部解压工具真实行为」的语义鸿沟——继续封 flag 是打地鼠。新增 `extract`（zip/tar 系解压：两遍法零落盘拒绝、产物一律 0600/0700、拒穿越/绝对路径/`.git*`/链接/设备条目、条目数与总大小上限防炸弹、输出过围栏）与 `pack_zip`（打包，拒 symlink、条目 0600）两个标准库技能；`run_command` 白名单删除 zip/unzip/tar（任何参数形态拒绝），runner 解压军备死代码约 500 行退役。**「LLM 内容→可执行文件」的转化通路自此不存在**（fs.write 0600 + extract 0600 双侧）；上限 env `AGENT_EXTRACT_MAX_ENTRIES`/`AGENT_EXTRACT_MAX_MB` | ✅ 已完成（2026-10-18；`tests/test_archive_skills.py` 30 例 + 白名单退役负例；变异复核 3/3 被抓；同批发现并修复 `SkillRegistry.execute` `name` 形参与技能参数冲突——positional-only 一行，run_build_script 此前在真实链路永远执行失败；详见 BACKLOG §6.10 与 review/FIX-6745556..d730827.md） |
| **NAS 容器化部署修复**（2026-10-27，ugreen-docker 分支，源自 `agent-demo-review-nas-2026-10-27.md`）：**P1-2** web 受控写面在容器内整体 500——compose 挂 `.env`→`/app/.env` + `AGENT_ENV_FILE=/app/.env`、挂 `config.yaml`、Dockerfile 给 `/app` 目录属主补 app（原子写的同目录临时文件此前无处落地，不补属主挂载也白挂）、entrypoint 修两个单文件挂载属权；**P1-3** data/ 根 7 个状态文件 recreate 即静默丢——新增 `data/state` 挂载 + `.env.example` 重定向注释块（`AGENT_LLM_PROVIDERS_FILE=data/state/…` 等），compose 另挂 `mirror`（异地镜像落点）与 `ssh`（known_hosts TOFU 持久化）；**P1-5** 6 键谎报 live（出站节流五键 + `AGENT_RECENT_IMAGE_BYTES`，载体是 import 期固化单例，web 显示"即时生效"实际一个属性都没变）——回落 `boot`，设置页诚实提示重启生效；**P2-1** psql 依赖补 `libedit2`/`libicu72` + `ldd` 自检写进文档（"备份能跑恢复不能跑"是最坏组合）；**P2-5** db `shm_size: 256mb`；**P2-6** compose 容器侧按 `PORT` 插值（改 PORT 不再静默破坏映射）；**P2-8** `AGENT_NUDGE_HOTSPOT_FILE` 补 `writable=False`（描述早写"只读"但标志位缺失）；**P2-11** `.env.example` 新增 compose 层变量节。**不适用项**：P1-1（ARM libpq，NAS 为 x86_64）、P1-4（pgdata named volume，RootDir 在 3.6T 存储池） | ✅ 已完成（2026-10-27；回归 `tests/test_config_write.py::test_singleton_backed_keys_report_boot_not_live`（6 键必须 boot）+ `tests/test_web.py::test_structure_path_keys_are_readonly`，变异复核：任一键加回 `live=True` → 新用例红；文档：`docs/deploy-nas.md`（新建，DX4600 全流程：55432 端口/`.env` 模板/构建/NapCat 切换先停 picoclaw/HA 令牌轮换/回滚/验收清单）、`docs/operations.md` 容器节、AGENTS 文档地图；详见 review/FIX-ugreen-docker.md） |

---

## 1. 下一步必要项（P0/P1）

### A 组：钱与容量 —— 从 demo 转可用的门槛

**A1（P0）token 用量统计 + `/cost` + 日预算熔断**　*已完成（`be13897`）*
- **现状（更新，2026-09-11）**：已落地 `agentcore/budget.py`（按日账本 + 软/硬闸门 + 成本估算），
  `LLMClient._post` 与两个 embedding 客户端均上报 usage，`/status` 展示当日用量；
  **残余**：独立 `/cost` 命令、per-user 维度、超限「降级换小模型」尚未实现（当前是拦截/告警）。
- **后果**：花费不可知；恶意刷消息线性放大成账单；`LLM_MAX_TOKENS=1024` 对 reasoning 模型本就偏小，改了也不知道代价。
- **做**：解析 usage（含 embedding 调用）→ `/cost` 出 per-user / per-day → 日预算上限，超限**降级**（换小模型/拒答）而非仅告警。
- **验收**：`/cost` 输出与上游账单同量级；预算命中时降级有日志与用户可见提示。
- **备注**：M7 的成本预算部分已完成；本条剩余项（`/cost` 命令、per-user 拆分、降级策略）转入 P2。

**A2（P0）历史裁剪 + 滚动摘要（启用 `sessions.summary`）**　*✅ 已完成*
- **落地**：`get_history_window`（带 id/ts 窗口）/ `get_session_messages_between`（水位补漏）/
  `get_session_summary` / `save_session_summary` 四个存储原语（双实现 + 契约测试）；
  `sessions` 加 `summary_upto_id` 水位列（幂等 ALTER，老库自动补）；引擎按
  `agent.history_token_budget` 保守估算裁剪历史，掉出窗口的消息滚动压缩进
  `sessions.summary` 并以不可信围栏注入 system prompt（`summary_enabled` 可整体关闭）。
- **追加（2026-10-13，见 §6.7）**：历史补上**时间维度**——`get_history_window` 带内部
  `ts`，最后一条距今超过 `agent.history_stale_after`（默认 6h）时注入「对话时间线」警示；
  `summary_max_tokens` 默认 400 → 4096（推理型模型把预算耗在思维链上，空 content 曾让
  摘要水位静默停更），空正文改为 WARNING 留痕。
- **验收**：裁剪/水位推进/摘要失败不伤主流程/开关等价/围栏防闭合均有自动化测试
  （`tests/test_engine.py::TestRollingSummary`、`tests/test_store_contract.py`）；
  摘要质量依赖模型，真模型长会话 E2E 待线上观察（`unknown`）。

### D 组：Web 管理面演进（2026-09-28 规划，经两轮交互定稿）

**D1（已完成，P0）设置只读视图**　*✅ 2026-09-28*
`/agent-web/api/settings`：LLM 线路（复用 `model_status()`）/ 运行开关+唤醒词 /
预算 / 记忆摘要（`agent:` 段白名单键）/ RAG / 备份归档，每块标注生效时机
（即时 / 需重启）；白名单键、`base_url`/api_key 不进响应体、降级不炸页；
页面加「设置」tab（即时/重启两栏）。回归：`tests/test_web.py::TestSettingsView`
（9 条，5 个护栏全部变异复核）。

**D4（已完成）日志查看面**　*✅ 2026-09-29*
`/api/logs/files` + `/api/logs`（tail 窗口 64KB/上限 256KB + `after` 增量游标 +
轮转重置 + 级别/模块/字面量 grep 过滤，行对齐保证）+ `/api/logs/download`
（流式，>200MB 拒绝，`logs_downloaded` 审计）。**内容口径（管理员决策）：原始日志
不脱敏**——AGENTS.md §4 已注明这是"响应体不含消息正文"的唯一显式例外，README
提示勿分享截图。门禁与 settings 相同（Bearer + 可选 CIDR，无新配置项）。
回归：`tests/test_web.py::TestLogsView`（14 条），护栏变异复核 6/6（文件白名单、
行对齐记账、下载上限、级别过滤、下载审计、不脱敏锚点）。

**D2（P1）受控写入面**　*D2-1 ✅ 2026-09-29 完成；D2-2 待做*
- **D2-1（已完成）**：`config_write.py` 纯函数核心（校验/定位/补丁/备份/原子写/
  运行态同步）+ web 两段确认流水线（HMAC 确认码绑定 nonce+键+新值+5 分钟窗口、
  单次有效；改前快照滚动 10 份；原子写 + 写后验证失败自动还原 + 审计）。
  白名单 7 键全热生效（写 .env + os.environ + budget 属性双写）；门禁 =
  CIDR 已配 **且** `AGENT_WEB_WRITE=1`，缺一写路由不挂载。回归
  `tests/test_config_write.py`（23 条，REVIEW-3ce6e0a..de09478 补 M1 窗口
  权限 / L3 行模型 2 条）+ `TestSettingsWrite`（20 条），
  护栏变异 6/6（确认码/备份/运行态同步/白名单/回滚/原子写）。
  定Nonce 修正：确定性 HMAC 会让同窗口写同键同值的第二人被误判重放
  （实现期实测），挑战改带随机 nonce。
- **D5（已完成，2026-09-29）进程重启**：`reboot.py`（白名单 argv 解析 + C/B/A
  执行链 + 停机编排 + 后台任务强引用）+ `/reboot` 命令（superuser 直执行，黑名单
  静默）+ web `/api/reboot`（写门禁 + 两段确认 + `reboot_requested` 审计）+ 设置
  页「重启」按钮。回归 `tests/test_reboot.py` 28 条；护栏变异 8/8（白名单开放/路径
  形态/spawn 不回落/execv 不回落/预校验失效/编排颠倒/任务不强引用/不走 lifecycle）。
  部署前提：systemd unit 需 `Restart=always` 或 compose `restart: unless-stopped`
  （否则 C/B 都不可用时重启即死亡，README 已警示）。
- **D2-2（待做）**：drift 表（文件值 vs 运行值差异 + "待重启 N 项"提示条）、
  env 白名单扩容（出站/防抖等组，逐键核对读取时机后入册）。
- ~~**原定稿要点**~~：v2 定稿的「范围/写入语义/三件套/门槛」四条**已被
  D2-1 取代**（"改运行态不落盘"是 P1 时代的旧语义；实际实现 = 写 `.env` 文件 +
  运行态同步，见 [REVIEW-26fec4d..3ce6e0a](REVIEW-26fec4d..3ce6e0a.md) M9）。
  当前有效口径：
  - **范围**：`config_write.WRITABLE` 硬编码锁死的 7 个 env 键（vision /
    group_context 开关+条数+TTL / wake_words / budget 两键），运行期不可扩充；
    凭据与安全边界键（API_KEY/TOKEN/SUPERUSERS/黑白名单）**刻意不在表内**，走 SSH。
  - **写入语义**：手术式改 `.env`（唯一落盘）+ 运行态同步（os.environ / budget
    属性 / group_context 单例属性）；优先级模型不变（env > config.yaml > 默认）。
  - **不变量三件套**：审计（`config_write`，key+掩码旧新值+backup+source_ip+
    confirm_nonce）+ 两段确认（HMAC 绑定 nonce+键+值+5 分钟窗口，按 nonce 单次
    有效）+ 改前快照滚动 10 份 + 原子写 + 写后验证失败自动还原。
  - **门槛**：`AGENT_WEB_WRITE=1` **且** `AGENT_WEB_ALLOW_CIDRS` 已配置（双门，
    缺一写路由整体不挂载）。

**D3（P2）配置持久化**　*架构级，需单独评审*
config.yaml 受控回写（yaml 回写丢注释需取舍）或 DB 覆盖层（env 之上的
key-value override，动 store 双实现契约）；"动 .env" 触碰"全部 env 驱动"铁律，
除非单独给出方案，否则不做。

**D6（P1，待定）Web 运维面与 bot 解耦（ops-web）**　*未排期；2026-10-23 评估*
- **问题**：`/agent-web` 挂在 bot 进程的 FastAPI 上（`mount_web`），bot / 协议端 /
  主机任一挂掉，备份列表与下载也一起不可用；人在异地时无法取备份重建。TOTP 又依赖
  私聊 `/2fa`，QQ 挂了取不到码。
- **结论（评估）**：可行，但只拆**专用只读运维面**，不要把整个 web 独立。
  备份列表/校验/下载/日志/health 零 bot 运行时依赖（`agentcore.backup` + 文件系统 +
  `DATABASE_URL`）；总览/设置/人格/模型/群统计/重启强依赖 `driver._agent_*`，
  拆解收益低、风险高，保留在 bot 内。
- **方案**：新增 `ops_web.py`（独立 FastAPI + uvicorn，**不 import nonebot**），只注册
  `/ops/api/health`、`/ops/api/backup*`、`/ops/api/logs*`；复用现有鉴权/2FA/
  `_backup_items`/`_find_backup`，不复制第二套白名单。独立 systemd unit、独立
  token（`AGENT_OPS_TOKEN`）与 CIDR，默认只监听 `127.0.0.1`，反代终止 TLS。
- **前置依赖**：① 第三方 TOTP 或一次性恢复码（bot 挂了也能取码）；② 部署在
  **NAS/云 VPS**（与 bot 同机的 ops-web 解决不了主机挂掉）；③ 公网访问必须
  TLS + VPN/IP 白名单 + 2FA + 限流。
- **不做**：远程执行/一键重建、生产库一键恢复、设置/人格/模型/群统计的独立写面
  （High 风险，仍走 SSH/CLI）。
- **验收（草案）**：无 NoneBot 初始化的进程能启动；未配 token 不监听（fail-closed）；
  只注册运维路由（`/api/settings`、`/api/personas`、`/api/reboot` 返回 404）；
  备份列表/下载/校验与 bot 内 web 行为一致；下载/删除/立即备份 2FA 两段；
  审计写文件/journal 只含 `name/bytes/source_ip`；systemd unit 独立；
  文档给出「下载 → 新机器部署 → restore → 协议端登录」runbook。
- **待定**：部署位置（NAS vs 云 VPS）、访问方式（Tailscale/WireGuard vs 公网反代）、
  2FA 方案（手机 TOTP / 恢复码）、是否含「恢复到 scratch 演练」。

### E 组：run_command 白名单放宽 + SSH 远程只读诊断（2026-09-30 管理员决策，已完成）

**E1（已完成，P1）只读运维命令进 run_command 白名单**　*✅ 2026-09-30*
- **决策依据**：私聊日志（`data/logs/agent.log` 09-30 04:00/05:49）——管理员问
 「core 强制重启」「ssh 上 192.168.1.2 看内存」，bot 因白名单无 `ps`/`ssh` 只能
  转人工；实际只读运维面已有 6 个 superuser skill（proc_detail 等），缺的是
  **LLM 可自组合的原始命令**。三档商定：只读命令放开 / 进程控制不放开 / SSH 走
  专用技能。
- **落地**：A 组免参数白名单（ps/top/free/df/du/uptime/uname/nproc/whoami/id/
  ss/netstat/lscpu——无任何写向选项，全局四道闸覆盖）；B 组子命令/flag 白名单
  （systemctl 只读子命令且拒 `--host/-H/-M/--machine`；journalctl 拒
  `--file/--root/--directory/--rotate/--vacuum-*`；dmesg 拒 `-C/-c/-w/-n/-D/-E`；
  hostname 只查不改；top 必须 `-b`）。`run_command` 描述同步 + 引导 `/reboot`。
- **刻意不放行（从"可放开"改为"不开"）**：`kill` 与 systemctl 动作类子命令
  （restart/stop/mask/edit…）——重启本服务走 `/reboot`（C→B→A 三段式退路）；
  杀进程不可回退，不把执行权交给自由拼参数的 LLM。依据：AGENTS.md §2 High 级
  边界变更需可复现证据与方案，方案经三档交互定稿。
- **验收**：`tests/test_runner_security.py::TestReadonlyOpsWhitelist`（15 条：
  正例放行、反例逃逸向量——`systemctl --host=root@192.168.1.2`、
  `journalctl --file=/etc/shadow`、`top -W`、`hostname myhost`、`ps -o x;id`、
  `df /` 等，加真实 `ps/free` 执行）；护栏变异复核 5/5（systemctl 子命令闸 /
  journalctl flag 闸 / top -b 闸 / sshpass 密码位置 / 远端命令常量性）。

**E2（已完成，P1）ssh_run 专用技能（内网设备只读诊断）**　*✅ 2026-09-30*
- **落地**：`agentcore/skills/ssh_skill.py`——host/用户/端口只来自
  `AGENT_SSH_HOSTS`（`alias=user@host:port`，未配置 = 整体关闭，fail-closed）；
  远端命令是**代码写死的常量菜单**（free/uptime/hostname/uname/ps/ps_mem/top/
  meminfo/cpuinfo/disks/mounts/dmesg/logread/netstat/ifconfig/services/users），
  LLM 只报 action 名——ssh 把命令交给远端用户 shell 执行，自由拼接 = 远端 RCE
  权交给 LLM，故不容许任何插值；凭据走 `AGENT_SSH_KEY_<ALIAS>`（私钥，权限过宽
  按缺失处理）或 `AGENT_SSH_PASSWORD_<ALIAS>`（经 `SSHPASS` 环境变量进 sshpass，
  **不进 argv/日志/返回值**——tool call 参数会全量落 agent.log）；
  `BatchMode=yes`/`ConnectTimeout=5`/`accept-new`+专用 known_hosts（TOFU）/
  `-F /dev/null`/`IdentitiesOnly=yes`；20s 超时 + 8000B 截断。
- **已知残余（如实披露）**：`accept-new` 首次连接可被同网段 MITM（换来一次远程
  只读执行权），收紧需预置 known_hosts 指纹；远端 busybox/GNU 差异只影响可用性。
- **验收**：`tests/test_ssh_skill.py`（14 条：host 解析/脏条目跳过、alias 与
  action 双白名单、密码不进 argv、`--` 隔断、sshpass 位置、密钥模式、超时/截断、
  权限双层 fail-closed）；护栏变异复核见 E1。

### B 组：用户能管自己的数据 —— 隐私底线

**B1（P1）`/memory list | forget <id> | clear`**　*工作量：小*
- **现状**：命令面仅 `reset / aihelp / status / skills / skillcatalog / skillinstall / skilluninstall / skillinfo / kb / persona`，**无任何记忆管理入口**。
- **后果**：用户看不到也删不掉关于自己的长期事实；而 facts 只增不减、无语义去重、无衰减。
- **做**：基于已有 `list_facts` / 删除接口暴露命令，输出只含调用者自己 session 的事实。
- **验收**：`forget` 后该事实不再进入任何 prompt；跨群不越权。

**B2（P2）`/export` 导出当前会话为 md**　*工作量：极小* — 复用 `send_markdown_file`，与归档天然配套。

### C 组：稳定性 —— QQ 场景必然踩到

| 编号 | 项 | 现状证据 | 做 |
|---|---|---|---|
| C1（P1）✅ | **LLM 重试退避** | ~~`client.py` 无 `retry`/`backoff`~~ 已落地：主模型瞬时故障重试（可重试分类 + 线性退避），重试耗尽才切 fallback | 原方案（指数退避）改为线性退避 `delay*attempt`，语义等价且可测 |
| C2（P1）✅ | **turn 级超时与取消** | ~~只有单次 LLM 60s 超时~~ 已落地：`AGENT_TURN_TIMEOUT`（默认 180s，0=不限）包住 engine.run | 超时回一句降级文案；debounce 队列不受影响 |
| C3（P1）✅ | **tool_calls 并行** | ~~串行 `for tc in ...`~~ 已落地：全只读工具 `asyncio.gather` 并行（fail-closed 白名单），含写操作仍串行 | `Skill.read_only` 标记 + `mark_read_only` 集中注册 |
| C4（P2） | **并发上限** | `Debouncer` 只保证同会话串行，无全局上限 | 全局 Semaphore + per-user 速率限制（与 A1 配套） |

---

## 2. 工程安全网（必要，但不是"功能"）

| 编号 | 项 | 为什么 | 做 |
|---|---|---|---|
| **2.1（P0）** | **PG 侧测试进 CI** ⭐ | 实测 32 个跳过**全部**是 `TEST_DATABASE_URL` 门控，CI 无 PG service → store / restore / replay 这些最危险的代码**零回归保护** | CI 加 `postgres:16`+pgvector service 并导出 `TEST_DATABASE_URL`（conftest 已有防误连生产库断言）；顺带加 3.11/3.12 矩阵 |
| **2.2（P0）** | **恢复演练脚本** ⭐ | 备份 / 镜像 / restore CLI 都有了，但**从未真恢复过一次**——没演练过的备份等于信仰 | `scripts/drill_restore.py`：定期把最新备份灌进 scratch 库，校验行数/向量一致性并输出报告 |
| 2.3（P1） | **Dockerfile** | README 自己写「根治方案是容器/独立低权用户运行」，但 compose 里只有 `db`，安全声明未兑现 | 单容器 + 非 root + `--cap-drop ALL` + 出口白名单；**不要挂 `docker.sock`**（改用镜像内 `postgresql-client` 直连 `db`） |
| 2.4（P2） | `/healthz` + 轻量 `/metrics` | fastapi driver 自带 HTTP 服务，成本很低 | turn 数、LLM 耗时、错误率、缓存命中 |
| 2.5（P2） | `config.yaml` pydantic 校验 + 结构化日志（turn_id 串联） | 字段写错只静默用默认值；一次 turn 的步骤散在各处 INFO | 启动 fail-fast；turn_id 串起 LLM/skill 调用 |
---

## 7. 架构债（2026-11-02 全量评审识别，均未修）

来源：上游 a9a28cf 评审 + 本 fork 六路只读子代理并行评审（RAG/embedding、记忆库/群统计、
渲染/点歌/人格、消息适配层、技能/沙箱、备份脚本/LLM 客户端）+ 主代理自审未覆盖模块。
本轮已修的全部为**正确性/安全/数据完整性**类（群统计双计、归档 mid 碰撞、创建即 0600 八处、
人格半截删除、备份脚本 compose 形态、技能越权、孤儿进程、识图预算架空、布尔配置静默失效等）；
下面这些是**结构性问题**，改动面大、收益不在本轮范围，逐条记档以免丢失。

### 7.1 Web 单体（`plugins/qq_agent_adapter/web.py`，5165 行）

| 项 | 现状 | 代价 |
|---|---|---|
| 单文件 5165 行 | 8 个闭包路由组挂在 `mount_web` 里 | 任何改动都要在 5000 行里定位；diff 冲突面大 |
| 路由注册不可静态枚举 | `importlib` 字符串式条件装载 | 新增面时容易漏挂鉴权/审计/2FA 三件套 |
| `AGENTS.md` 配置优先级表述脱节 | 文档与 `config_json.py` 的实际优先级链有偏差 | 接手者按文档推理会得出错误结论 |
| 无 ADR | 重大决策只散落在 `review/` 与 commit message | 「为什么这样」不可检索 |

建议拆法（未实施）：按现有 8 个闭包分组切成 `web/routes/<组>.py`，共享鉴权/2FA/审计提取为
中间件式依赖；先补「路由表 + 每路由的鉴权等级」快照测试再动手，防止拆的过程中漏挂门禁。

### 7.2 `agentcore/llm/client.py` 两条候选循环（真缝）

`_chat_providers`（:387-440）与 `chat()` 的 env 路径（:655-718）是两份近似重复的候选/重试/降级
状态机——都是「idx==0 重试 `_PRIMARY_ATTEMPTS`(=2) 次 + `_RETRY_BACKOFF_SECONDS`(=0.5)s 退避、
失败换下一个、全失败抛 last_err」，差别只在状态字段（providers 版记 `_last_served_provider`/
`_provider_previous`；env 版管 `_using_fallback`/`_previous`/`_last_served`）。删任何一份，
复杂度都会在另一份复现。

建议顺序：先收敛成统一的 `_FallbackState`，再加「两条路径行为等价」的参数化测试，
最后才抽 `_run_chain`。跳过前两步直接抽 = 没有安全网的重构。

### 7.3 `pipeline.py` `_build` 336 行内嵌 6 个「有没有图」判据

`plugins/qq_agent_adapter/pipeline.py:751-1086` 的 `_build` 里并列 6 个互不等价的图片来源判据：
`direct_media` / `had_image_segments` / `quoted_imgs` / `fwd_imgs` / `history_imgs` /
`recent_images.get`。本轮 F1（群历史回捞图被 `recent_images` 缓存静默覆盖）正是漏判一项的直接后果。

建议抽单一 `ImageSupply` 值对象：五个互斥来源（direct/quoted/forwarded/history/cached）+ 显式优先级
+ `is_empty()`，`_build` 改为对其查询。

### 7.4 子进程启动策略四套并存

`agentcore/workspace/runner.py`、`agentcore/skills/shell_skill.py`、`action_skills.py`（npm_update）、
action_skills.py`（run_build_script）、`command_util.py`、`ssh_skill.py` 六处的 env/进程组/超时杀法
原本四套并存。本轮 D1 已逐站点补齐 `start_new_session=True` + `os.killpg`，B2 已给
`command_util.py` 补最小 env；**未抽共用的 `spawn_guarded(cmd, *, cwd, env, timeout, kill_group=True)`**。

不抽的理由（AGENTS.md §2.5 最小改动）：跨文件抽公共函数会把 4 个模块的 logger/返回值/超时文案
差异卷进来，风险与收益不成比例。若日后再抽，须连同六处的超时文案差异一起设计。

### 7.5 全仓零目录 fsync

`os.replace` 站点 12 处（`budget.py:222`、`db_backup.py:228/266/628/704`、`totp.py:80`、
`llm/providers.py:350`、`workspace/fs.py:168`、`personas/manager.py:377`、`search_providers.py:238`、
`push.py:612`、`nudge.py:635/947`、`jobs.py:366`），文件级 fsync 只 4 处，**父目录 fsync 0 处**。
掉电时 rename 可能不持久（ext4 `data=ordered` 下影响有限；NAS 部署目标值得注意）。

### 7.6 配置单一事实源（上一轮 B 组，仍未修）

18 个生产 env 键不在 `settings_spec.ENV_SPECS`；spec default 与代码 default 三处漂移
（`LLM_MODEL` spec `step-3.7-flash` vs 代码 `step-1-flash`；`AGENT_WAKE_WORDS` spec `小助手,助手`
vs 代码 `''`）；`find_env_names` 漏 `env_bool` 包装的 6 个键。本轮已把 6 处 `kind=bool` 手解
迁到 `boolenv`（脏值告警后回落默认），但 schema 漂移本身未动。

### 7.7 并发生命周期（上一轮 C 组，仍未修）

cron tick 串行致触发时刻漂移；`growth.aclose`/`debounce.cancel_all` 零调用方（前者本轮 E4 已接线到
`lifecycle.shutdown_agent`，后者仍为死代码）；预算硬闸四种日志待遇（`engine.py:1068/1383/1740/1800`）；
`engine.py:1284` 的 `gather` 无 `return_exceptions`。

