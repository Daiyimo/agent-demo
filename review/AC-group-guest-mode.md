# AC — 群聊访客模式 + cron/人格出沙箱（信任模型重铸，v2）

> 状态：**草案 v2（待评审）**。v1 为 2026-10-29 的外部草稿（`Downloads/AC-group-guest-mode.md`），
> 本文件是据此 + 全仓实证修订后的版本，**自包含**（v1 的 `REVIEW-pr6-3c00145.md` 在本仓库与
> GitHub 均不存在，PR #6 的 API 查询返回空，H2/H3 的原始证据无法核对；凡涉及该评审的条目
> 一律降级为"未验证来源"，不作为验收依据）。
>
> 2026-10-29 三条定夺（v1 未决、本版固化）：
> 1. **访客面 = 白名单制（fail-closed）**：群友只看到显式标了 `guest=True` 的技能；新技能默认
>    不给群友。v1 的"public 即群可见"是 fail-open，会把 `send_markdown_file`/联网/LLM prompt
>    技能直接交给陌生人（现状已如此，见 D5）。
> 2. **`AGENT_GROUP_EXTRA_SKILLS` 只对"群内的 superuser 回合"生效，且只接受只读技能**：写/执行类
>    （`fs_*`/`run_*`/`ssh_run`/`db_query`）出现在名单里 → 启动 WARNING 并忽略该项（fail-closed）。
>    群内文本不可信，给 owner 在群里开写通道等于把注入面重新打开。
> 3. **旧布局迁移 = 复制不搬走 + 旧位读回退**：回滚（revert）时数据仍在，不会出现"代码回滚了、
>    配置已经搬没了"。
>
> 本 AC 是"怎么算改好了"的验收规格。每条验收附**可执行断言**（真实测试文件 + 断言要点）；
> 实施时逐条补变异复核结论（改坏实现 → 用例必红 → 还原）。

## 0. 信任模型（本 AC 的宪法）

| 会话 | 身份 | 技能面 | cron | 人格 |
|---|---|---|---|---|
| 私聊 | superuser（owner） | **全量**（含 fs/run/db/ssh/ops/archive） | 可用（主机文件 / SSH；**无 web 面，也无 QQ 命令**） | 可改（web 2FA / SSH） |
| 私聊 | 非 superuser | **直接拒绝**（`acl.is_allowed` 现状；根本没有"访客面"入口） | 无 | 无 |
| 群聊 | superuser | 访客面 ∪ `AGENT_GROUP_EXTRA_SKILLS`（**仅只读项**） | 无 | 无 |
| 群聊 | 非 superuser | 访客面（`guest=True`） | 无 | 无 |
| **cron `agent_turn`** | owner 代理 | **全量**（与私聊 owner 同权——`jobs.json` 是主机配置，属 owner 写的可信指令） | — | 默认人格（隔离会话） |

**owner 上下文 = 私聊 superuser ∪ cron 任务**。这条必须写进代码判定，否则 v1 的 D1 会把
jobs.json 的主用例（"到点跑脚本 + 发群"）一起废掉：cron 既不是 `private` 也不是访客。

**访客面**（默认集，可加不改）：`now` / `date_calc` / `calc` / `unit_convert` / `random` /
`get_weather` / `wiki_blhx` / `wiki_prts` / `xiaoheihe_post` / `reminder_add` / `reminder_list` /
`reminder_cancel` / `play_music`（仍受群白名单）/ `my_group_review`（本群统计）。准入标准见 D5。

**不在访客面**（现状是 public，但**不属于**访客面）：`send_markdown_file`（写工作区 + 上传）、
`render_text_image`（渲染 + 上传）、`fetch_url` / `summarize_url` / `search_web` / `search_multi`
（陌生人可驱动的外网访问）、`data/skills/*.yaml` 的 prompt 技能（每次调用都是 owner 的 LLM 账单）、
`data/skills/*.py` 的本地代码技能（默认 `permission="public"`，见 D5 的 fail-closed 要求）。

**威胁模型不变的部分**：本模型**不宣称免疫提示注入**。owner 私聊里照样混着不可信内容
（引用/网页/检索），`run_shell`（`AGENT_PERMISSION_LEVEL=high`）仍是可写文件的残余通道——
所以"配置出沙箱"是**去除一条确定的提权链**，不是"零通道"。v1 的"LLM 全通道不可达 / 比
OpenClaw 更严"必须改口径（见 D2）。

## 1. 变更面（含 v1 漏掉的部署面）

| 文件/目录 | 层 | 变更 |
|---|---|---|
| `agentcore/skills/registry.py` | 纯 Python | `register(..., guest=False)` + `Skill.guest`；`_is_allowed` 增加 where 轴判定（`group_id` + `user_id`），不依赖 contextvar |
| `agentcore/skills/permissions.py` | 纯 Python | 群内 superuser 的收窄判定；extra 名单只读强制 |
| `agentcore/loop/engine.py` | 纯 Python | owner/isolated/route 三项从 `context` 取出：`get_schemas`/`execute` 传 `owner`；`isolated=True` 时跳过 `_remember_facts` 与两处 `growth.maybe_trigger`；`current_route` 取 `context["route"]` |
| `agentcore/scheduler/jobs.py` | 纯 Python | 目录 `data/cron/`；state 拆 `state.json`（`state_path`/`_read_state_sidecar`/`_write_state_sidecar`）；`_dump_job` 不再输出 state/updatedAtMs；旧内嵌 state 读入后由 `save` 迁入 sidecar |
| `agentcore/scheduler/agent_turn.py` | 纯 Python | M1 群目标 ACL（**P0 已完成**）；M2 会话隔离 + facts/growth 抑制；L3 pending-before-send |
| `agentcore/personas/manager.py` | 纯 Python | `DEFAULT_PERSONAS_DIR` → `data/personas/`；`PERSONAS_DIR` 覆盖优先 |
| `plugins/qq_agent_adapter/__init__.py` | NoneBot | 注入 `ALLOWED_GROUPS`（P0 已完成）；`AGENT_GROUP_EXTRA_SKILLS` 解析 + 注册后校验；`jobs_file=jobs_path()`；启动期调 `migrate_legacy_layout()`（早于 `_build_cron_jobs`） |
| `agentcore/migrate_layout.py`（新） | 纯 Python | 旧布局 → 新位：复制不搬、幂等、失败只 WARNING（`migrate_legacy_layout()` 返回搬动项列表） |
| `docs/examples/cron-jobs.example.json`（新） | — | 唯一入库的 cron 模板（占位群号、`enabled: false`、无 state），`compose_init` 首启复制成 `data/cron/jobs.json` |
| `plugins/qq_agent_adapter/settings_spec.py` + `.env.example` | 配置 | `AGENT_CRON_DIR` 默认 `data/cron`；新增 `AGENT_GROUP_EXTRA_SKILLS`（两侧键集相等由 `test_web.py` 锁） |
| `scripts/compose_init.py` | 脚本 | `DATA_DIRS` 加 `cron`/`personas`；SOUL 自举落点改 `data/personas/` |
| `scripts/docker-entrypoint.sh` | 脚本 | `MOUNTS` 加 `cron`/`personas` |
| `Dockerfile` | — | `mkdir data/cron data/personas` |
| `docker-compose.yml`、`docs/deploy-nas/docker-compose.yml` | 部署 | 各加两条逐目录挂载 |
| `scripts/backup_usb.sh` | 脚本 | 冷备复制清单加 `cron personas`；修掉早已失效的 `agentcore/personas/*.md` glob；必含断言加 `jobs.json` |
| `scripts/check_privacy.py` | 脚本 | `_SHAPE_SCOPES` 加 `docs/examples/`；`PLACEHOLDER_TOKENS` 复核 |
| `.gitignore` | — | 忽略 `data/cron/`、`data/personas/`；撤销 `data/workspace/{SOUL.md,personas/,cron/}` 放行 + `git rm --cached` 三个已跟踪文件 |
| `tests/` | — | 按主题文件补（见 §3）；`TestRepoJobsFile` 改模板锁 |
| `docs/` + `AGENTS.md` | 文档 | 见 D6 的文档面清单（v1 只列 2 处，实际 6 处） |

**不碰**：DDL、reminder/push/nudge 既有链路、matcher 直连命令 ACL、`agentcore` 的分层（不得
import plugins）。**零新增依赖。**

## 2. 设计决策

### D1 技能 where 轴（修订 v1 的三处）

- **判定轴用 `group_id` 参数，不用 `current_route` contextvar**。`get_schemas/execute/is_allowed`
  的签名里本来就有 `group_id`（engine 也一直在传），用它：无时序/跨任务残留面、直调
  `registry.execute(..., group_id=...)` 的几十处既有测试不受影响、`/skills`（admin.py）与执行
  自动一致。`current_route` 继续只服务预算记账。
- **收窄在 `_is_allowed` 里按 `skill.permission` 计算，不在注册期写死**。理由：prompt 技能走
  `install()`、本地技能走 `local.py` 的包装，注册期算会漏。效果：`permission="superuser"`
  的技能在群里对**任何人**隐藏（除非走 extra 且是只读 + 调用者是 superuser）。
- **拒绝文案保持与 unknown 同款**（`"Error: unknown skill ..."`），WARNING 留痕含 `group_id`。
  注意：这条会让 tool-loop 的 `unknown_calls` 计数 +1（上限 3，`_MAX_UNKNOWN_CALLS`），
  群内模型重复尝试会被 breaker 拦，这是**期望行为**，写进用例备注。
- **visitor 白名单**：`guest=True` 标注 + fail-closed。标注面只有 ~15 个，且漏标的后果是
  "群友少一个工具"（可见、可修），而不是"多暴露一个面"（不可见）。
- **`AGENT_GROUP_EXTRA_SKILLS`**：`csv`、启动期校验（未知名 WARNING 一次）、去重、**只接受
  `read_only=True`**、只对"群内 superuser 回合"生效；登记进 `ENV_SPECS` + `.env.example`
  （`test_web.py::test_schema_covers_env_example_and_invariants` 要求两侧键集相等）。

### D2 cron 出沙箱（修订 v1）

- `data/cron/jobs.json`（配置，0600，gitignore）+ `data/cron/state.json`（运行态，0600）。
  `save()` 只补丁 `jobs` 键的既有纪律保留；state 由执行体原子写、损坏时回退"全部重算下次
  时刻"而不是丢 job。
- 模板入库 `docs/examples/cron-jobs.example.json`（只放占位号 + `group:<占位群号>` 字面量）；
  compose 首启（`compose_init`）缺文件才复制、已存在不覆盖。
- **口径修正**：不再是"LLM 全通道不可达"，而是"**去除 `fs_*` 通道**；`run_shell`（high 档）
  仍可在 owner 私聊被注入时写文件，由提示注入防线承担"。这也是本 AC 不宣称免疫注入的原因。
- 修改通道 = SSH 手改 / 未来 web 面（2FA + 审计）。**现状没有 web 面，也没有 QQ 命令**——
  v1 §0 的"文件/web 通道修改"要改成"主机文件 / SSH"。
- 旧内嵌 `state` 的迁移**不做写时删除**（避免启动期改用户文件）：`load()` 先按 sidecar 覆盖、
  旧内嵌 `state` 自然作为回落；下一次 `save()` 时 sidecar 落盘、`jobs.json` 重写即不再含
  `state`/`updatedAtMs`。幂等，坏 sidecar 只 WARNING 并回落内置 state。
- **迁移用复制**：`data/workspace/cron/jobs.json` 存在且新位置不存在 → 复制 + 告警一条；
  旧文件保留一个版本。启动期"旧位读回退"只在**读**路径生效（不重新打开写通道）。

### D3 人格出沙箱

- 根级 `SOUL.md` 与 `personas/<name>/` 落 `data/personas/`；`PERSONAS_DIR` 环境变量优先级更高
  （测试/高级部署靠它隔离，别让默认值改动把测试写进仓库）。
- web 人格面读写新落点，2FA/审计/覆盖备份契约不动；`compose_init` 的 SOUL 自举同步。
- `data/workspace` 回归纯 LLM 产物；P0 已加的**保留名**（`SOUL.md`/`personas`/`cron` 禁写）
  在迁移后保留，防回迁与"写了假的"。

### D4 agent_turn 三修复

- **M1（群目标 ACL）**：已在 `AgentTurnRunner` 前置判定，不跑引擎、不投递、`failed` + 去重
  WARNING、仍推进下次执行（防 60s 重试）。**P0 已完成并入本分支**，见 §7。
- **M2（会话隔离）**：`user_id="cron:<job_id>"`、`group_id=None` → 内存键 `p:cron:<job_id>`，
  PG 是 `sessions` 一行（`user_id='cron:…'`、`group_id IS NULL`）。**不要发明 `cron:` 裸键**：
  会话键命名空间是 `p:`/`g:`，facts 表 `session_id` 是整数，造新前缀会打破 store 契约。
  同时显式抑制：facts 抽取（`_remember_facts`）、growth（`maybe_trigger`）——它们是 engine
  内无条件调用的，不会因为换了会话键就自动关掉。
- **L3**：`sent` 后先记 pending 再投递，崩溃窗口不重投（不动出站三态语义）。

### D5 访客面准入标准（写进 AGENTS.md §4）

一个技能对访客可见，须**全部满足**：① 确定性或资源有界（含 LLM/网络成本）；② 按 user 隔离
（无跨用户信息流）；③ 无持久化副作用（reminder 除外：按 user 隔离 + 条数上限，是样板）；
④ 输出过围栏/脱敏既有不变量；⑤ 群内不需要 owner 上下文。
`guest=True` 是唯一入口；`public` ≠ 访客（`send_markdown_file` 这类就是反例）。
本地代码技能（`data/skills/*.py`）默认 `guest=False`，要开必须显式标。

### D6 守卫（可实现的版本）

- **单一事实源在代码**：`Skill.guest`。双向都要守，但**只比"已注册"的名字**：文档写了必须
  `guest=True`、标了 `guest` 必须进文档；插件条件注册（`play_music`/`my_group_review`）与
  reminder 三件套列入 `EXTERNAL` 单独断言，`wiki_*` 用前缀通配（站点由 `AGENT_WIKI_SITES` 决定）。
  不比较 public 集（随 env/依赖/prompt 技能变化，必然不稳）。
- `test_registry.py::TestGuestDocDrift`（3 条）：文档→代码、代码→文档、reminder 三件套；
  文档里的名字若既没注册也不在 `EXTERNAL` → 红（防笔误）。
- `test_repo_guards.py::TestRuntimeDataNotTracked`（3 条）：`git ls-files data/workspace data/cron
  data/personas` 必须为空；`git check-ignore` 四个运行期路径必须命中；`docs/examples/cron-jobs.example.json`
  必须被跟踪。行为侧由 `test_personas.py::TestPersonaOutOfWorkspace`（默认目录不在 workspace）与
  `test_workspace.py::TestFsReservedNames`（旧位写不进去）承担；字符串扫描不做。
- 部署面守卫：`test_compose_init::test_data_dirs_match_compose_mounts` 遍历**两份** compose
  断言每个 `DATA_DIRS` 都有 `/app/data/<name>`；`test_dockerfile_ships_cron_template_and_runtime_dirs`
  断言 Dockerfile 里 `mkdir` 了两目录且镜像内含模板。
- 密钥/隐私面：`check_privacy.py` 的 `_SHAPE_SCOPES` 扩 `docs/examples/`（模板里的号也归它管），
  `test_privacy_gate.py` 补 `test_workspace_still_scanned` 防"扩范围把原范围丢了"。

## 3. 验收项（真实用例名；2026-10-29 实施后逐条核对）

图例：✅ 已实现且有断言；⚠ 有覆盖但口径与本条不同；❌ 未做（写明理由）。

### A 组：技能 where 轴（`tests/test_permissions.py` + `tests/test_registry.py`）
- **A1** ✅ 群内 superuser：schema 不含 `fs_write` → `TestGuestSurface::test_group_superuser_no_superuser_schema`；
  `execute` 与 unknown 同文案 → `TestGuestSurface::test_group_superuser_execute_denied_as_unknown`。
  （`/skills` 名单走同一个 `registry.is_allowed`，未单独建群内渲染用例。）
- **A2** ✅ 群访客只看 `guest=True`：`TestGuestSurface::test_group_guest_only_guest_skills`、
  `TestGroupTrustModel::test_group_guest_sees_only_guest_marked`；reminder 三件套
  `TestGuestDocDrift::test_reminder_trio_is_guest_visible`。
- **A3** ✅ 私聊 superuser 全量 → `TestGroupTrustModel::test_private_superuser_keeps_full_surface`。
- **A4** ✅ `TestGroupExtraSkills`（5 条：分隔符 / 未设置 / 未知名 WARNING / 非只读 WARNING 且不可见 /
  只读项对群内 owner 可见）+ `TestGroupTrustModel::test_group_extra_only_applies_to_readonly`、
  `test_group_extra_not_a_superuser_upgrade`。
- **A5** ✅ 群内拒绝留痕但**按 `(技能, 群)` 去重**：
  `SkillRegistry._warn_denied_once`（`registry.py`）在拒绝分支打
  `WARNING 群内技能调用被拒：skill=… group=…（schema 已隐藏；同名同群只告警一次）`，
  响应仍是 `Error: unknown skill …`（无探测口；真正的 unknown 名字一条都不打）。
  用例 `TestGuestSurface::test_group_denial_warns_once_per_skill_and_group`；变异（去掉调用）→ 该用例红。
- **A6** ✅ 变异记录见 `review/FIX-group-guest-mode.md` §8：删 `or not guest` → 3 红；`guest=skill.guest`
  改 `False` → 1 红。

### B 组：出沙箱（`test_workspace.py`、`test_archive_skills.py`、`test_personas.py`、`test_migrate_layout.py`、`test_scheduler_jobs.py`、`test_privacy_gate.py`）
- **B1** ✅ `TestFsReservedNames`（7 条）：写 `SOUL.md`/`cron/jobs.json` 拒且规范位置字节不变、`soul.md`/`Cron`
  大小写不敏感、`mkdir personas` 拒、`delete`/`delete_abs` 拒、嵌套 `notes/SOUL.md` 允许、读取允许。
- **B2** ✅ `TestExtractReservedDest`（4 条：`dest=cron`/`personas`/`SOUL.md`/`Cron/jobs` 拒绝且零落盘 +
  `test_normal_dest_still_works` 正向对照）。条目穿越仍由既有
  `TestExtractRefused::test_zip_bad_entries_zero_landing` 守（预扫描即拒、零落盘）。
  **补丁**：`extract` 自己用 `os.open` 落盘、不经 `_assert_writable`，P0 的保留名守卫原本管不到它；
  本次让 `archive_skills._resolve_dest` 复用 `agentcore/workspace/fs.py:reserved_root`。
- **B3** ✅ `TestHandEditReload::test_tick_reads_edited_file_without_restart`：tick 跑第一版 → 手改 JSON
  文案 + 删状态侧车（把下次执行拨回立即）→ 再 tick 得第二版且投递 2 次。
  **同时修掉一个真缺口**：`AgentTurnRunner.tick()` 原先 `jobs_mod.load()` 读默认路径、与
  `update_state(path=self.jobs_file)` 不同源，`jobs_file` 指定的文件根本不参与 tick（`test_crash_during_send_
  is_not_redelivered` 因此曾是恒真断言）。现在 tick 与状态回写同源；变异（回退 `load()`）→ 本用例红。
- **B4** ⚠ `TestPersonaOutOfWorkspace` 覆盖默认目录/双布局/写回落，含
  `test_default_layout_writes_flat`（默认位平铺 `<名字>/SOUL.md`）与显式 `PERSONAS_DIR` 沿用
  `personas/<名字>/` 的既有 4 条；web 人格面未新增用例（既有页面测试 monkeypatch `PERSONAS_DIR`，
  Linux 上真跑落盘断言，本机被 2FA 的 `os.O_NOFOLLOW` 遮挡）。
- **B5** ✅ `TestPersonaOutOfWorkspace::test_legacy_personas_subdir_still_read`、
  `test_new_layout_wins_over_legacy_copy` + 迁移 7 条（复制且旧文件保留 / 不覆盖 / personas+soul /
  幂等 / 同目录 noop / 失败容错只 WARNING / `PERSONAS_DIR` 仍指旧位时整段跳过）。
- **B6** ✅ `TestStateSidecar`（7 条：不改写 jobs.json / 旧内嵌 state 回落 / sidecar 优先 / 坏 sidecar 告警回落 /
  save 迁出状态 / deleteAfterRun 清 entry / 不落空壳）+ `TestCronTemplateExample::test_repo_jobs_file_is_valid`。
- **B7** ✅ `tests/test_privacy_gate.py` 5 处改指 `docs/examples/cron-jobs.example.json` +
  `test_workspace_still_scanned`（老目录仍被规则 B 扫）。

### C 组：agent_turn（`tests/test_scheduler_jobs.py` + `tests/test_engine.py`）
- **C1** ✅ `TestTargetACL`（5 条）：白名单外 → failed + WARNING + 零引擎 + 零投递 + 下次时刻推进；
  白名单内 ok；空集拒；私聊免白名单且 `group_id` 为空；告警按 job 去重。
- **C2** ✅ `TestCronOwnerTurn::test_isolated_turn_skips_facts_and_growth`（spy：隔离回合 facts/growth 均 0，
  普通私聊回合作正向对照）+ `test_isolated_session_uses_private_namespace`：直接断言内存实现的会话键
  `p:cron:daily` 存在、`sessions` 里没有任何 `g:` 键（即不产生 `g:<gid>:<gid>` 自我对话键），且历史只落 cron 键。
  PG 侧同一代码路径（`resolve_session(user_id="cron:…", group_id=None)` → `scope='private'`、
  行 `user_id='cron:…'`、`group_id IS NULL`）由 store 契约锁着；本机无 PG（`docker` 不可用），
  **PG 实跑标 unknown**，留给 CI 的 `TEST_DATABASE_URL` 套件。
- **C3** ✅ `test_budget_route_is_cron_job`（handler 内读 `budget.current_route`，cron 回合为 `cron:daily`，
  对照回合为 `private:111`）。
- **C4** ✅ 变异 7 条（facts 抑制 / growth 抑制 / owner 传参 / route 回退 / owner 旁路 / pending 写入 /
  pending 落点），记录见 FIX §10。

### D 组：访客面与文档（`test_registry.py`、`test_repo_guards.py`）
- **D1** ✅ `TestGuestDocDrift`（3 条）：文档名单 ⊆ 已注册且 `guest=True`；`guest=True` ⊆ 文档 ∪ `wiki_*`；
  reminder 三件套 `guest=True`。
- **D2** ✅ 守点从 `TestSecretBearingPaths`（只认字面量文件名，判不了目录级规则）换成更硬的一组
  `TestRuntimeDataNotTracked`（3 条，已实跑绿）：`git ls-files data/workspace data/cron data/personas`
  必须为空 / `git check-ignore` 认下 `data/workspace/SOUL.md`、`data/cron/jobs.json`、
  `data/cron/state.json`、`data/personas/me/SOUL.md` 四条 / `docs/examples/cron-jobs.example.json`
  仍被跟踪。理由：`unignored_secrets()` 是「逐行字面量 + 通配」判定，`data/*` + `!docs/...` 这种
  顺序敏感的规则它读不懂，扩它会写成恒真断言；`git check-ignore` 直接问 git 本体。
- **D3** ✅ AGENTS.md §4「权限级别」行含 where 轴 + owner 轴 + cron 隔离；`docs/features-skills.md`
  「群聊访客模式（where 轴）」给出准入标准（漏标 = 不可见、群内 superuser 只见只读 extra、群授权叠加）。
- **D4** ⚠ `check_review_docs.py` 本体绿；`--check-stats` 在本机跑不了（pytest 返回非 0 即抛
  `RuntimeError("pytest 未通过或输出无法解析")`）。BACKLOG 计数块按「3674 收集 / 3601 通过 + 73 跳过」
  手写推导（收集数与通过数来自实跑，跳过数沿用上次 CI 记录；本机 84 跳过含 11 条 Windows 专属），
  **需 CI 复跑 `--write-stats` 对齐，勿手改**。

### R 组：回归与兼容
- **R1** ⚠ CI 未跑。本机全量 167 failed / 3419 passed / 84 skipped，逐条核对均为存量 POSIX-only
  （`os.O_NOFOLLOW`、权限位、msys `df`/`age`/`zip`）或 Windows 路径分隔符差异；本轮新增用例全绿。
  新写的原子写统一 `getattr(os, "O_NOFOLLOW", 0)`，`archive_skills` 的 `_O_NOFOLLOW` 同样收敛。
- **R2** ✅ `TestGroupExtraSkills::test_parse_separators`（`,` `;` 空白 tab 换行）+ `test_unknown_warns_and_not_effective`；
  该键是 csv，不走 `boolenv`。
- **R3** ✅ 复制式迁移 + 目录常量单点（`DEFAULT_PERSONAS_DIR`、`_DEFAULT_DIR`、`state_path`）；
  `TestMigrateLayout` 保证旧位数据存留、revert 后可启动。

## 4. 非目标

1. 多用户 RBAC / 按群差异化技能面（一个 env 白名单足够）。
2. 提示注入免疫（围栏/脱敏继续承载；本 AC 只收窄触发面与可写面）。
3. 群友 cron / 群友人格修改（零通道）。
4. `llm-providers`/`agent.json` 配置链重构（另立 AC）。
5. 给 cron 做 web 管理面（先 SSH，避免把 2FA + 审计 + 改前备份的量塞进本批）。

## 5. 风险与代价

| 风险 | 缓解 |
|---|---|
| owner 群内运维体验变化 | extra 名单（只读）；模型回"去私聊找我"（prompt 口径补一句） |
| 访客名单漏标 = 群友少工具（可见） | 文档 ⊇ 测试 + 新增 `guest=True` 未入文档即红 |
| extra 名单被写进 `fs_write` | 启动 WARNING + 忽略（fail-closed），用例钉死 |
| 旧布局迁移搬坏现网配置 | 复制不搬 + 旧位读回退 + 幂等 + 告警；失败不阻塞启动 |
| `run_shell` 残余通道 | 文档如实披露（D2 口径修正），不宣称"零通道" |
| 容器重建丢 cron/人格 | 两份 compose + `DATA_DIRS` + `MOUNTS` + Dockerfile + 冷备，五处齐改 + 守卫测试 |
| 群白名单漂移（现状：文档承诺、代码不查） | **P0 已修**；用例 `TestTargetACL` 覆盖 |

## 6. 工作量

| 批 | 内容 | 估计 |
|---|---|---|
| **P0** | cron 群目标 ACL + 工作区保留名 + 文档同步 | **已完成（约 0.5 天）** |
| P1 | D1 where 轴 + 访客白名单 + extra + A 组 | 2–3 天 |
| P2 | D2/D3 出沙箱 + 部署面六处 + 迁移 + B 组 | 2–3 天 |
| P3 | D4 M2/L3 + D5/D6 守卫 + 文档 + C/D/R 组 | 1–1.5 天 |

合计 **5–7 天**（v1 的 3–4 天没算部署面、store 契约、state 迁移与访客面审计）。

## 7. 执行记录（P0，本分支 `fix/guest-mode-p0`）

- **C1**：`AgentTurnRunner(allowed_groups=...)`，适配层注入 `acl.ALLOWED_GROUPS`；空集
  fail-closed；私聊目标不受群白名单约束。用例 `tests/test_scheduler_jobs.py::TestTargetACL`
  （5 条）。实测：白名单外 → `failed`、引擎 0 调用、投递 0 条、WARNING 含 job id、下次时刻推进。
- **B1**：`WorkspaceFS` 保留名（`SOUL.md`/`personas`/`cron`，大小写不敏感，根级）；读放行。
  用例 `tests/test_workspace.py::TestFsReservedNames`（7 条）。
- **变异复核**：分别把两处判定改成 `if False` → 8 条用例红（另 4 条正向对照仍绿）；还原后全绿。
- **全量套件**：`179 failed / 3349 passed / 84 skipped`（本机 Windows）。失败全是既有 POSIX-only
  类；把新判定改回 `if False` 后失败数**不变**（179），确认本次改动零新增失败。真实门禁以 CI 为准。

### 7.1 P1–P3 执行记录（同一分支，仍未提交）

- **P1（D1）**：`Skill.guest` 默认 `False`、`register(guest=...)`、manifest `guest:`；
  `PermissionChecker` 按 `group_id` 判 where 轴；`AGENT_GROUP_EXTRA_SKILLS` 只收 `read_only`
  且只对群内 superuser 生效（未知名/非只读一律 WARNING 忽略）。用例 23 条，变异 4 项。
- **P2（D2/D3）**：cron → `data/cron`（`state.json` 侧车，旧内嵌 state 读入即迁移）；人格 →
  `data/personas`（`migrate_layout.py` 复制不搬、幂等、失败只 WARNING）；部署面六处 + 隐私门禁
  扩 `docs/examples/` + `.gitignore` 改整目录 + `git rm --cached` 三个运行时文件。用例 20 条。
- **P3（D4/D6）**：owner 旁路（私聊 ∪ cron，群聊永不带）；cron 回合 `user_id="cron:<job>"`、
  `group_id=None`、显式跳过 `_remember_facts`/`maybe_trigger`；route `cron:<job>`；投递前落 `pending`。
  用例 6 条（含"崩在投递中间不重投"），变异 7 项。
- **补修（B2 旁支）**：`extract` 自己 `os.open` 落盘、不过 `_assert_writable`，保留名守卫原本被它绕过——
  改为 `archive_skills._resolve_dest` 复用 `workspace/fs.py:reserved_root`，并加 `TestExtractReservedDest`
  5 条（4 拒 + 正向对照）；顺带把该模块两处 `os.O_NOFOLLOW` 收敛成 `getattr(os, "O_NOFOLLOW", 0)`。
- **补修（A5/B3/C2 收尾）**：群内拒绝改为按 `(技能, 群)` 去重 WARNING（`_warn_denied_once`）；
  `AgentTurnRunner.tick()` 改为 `jobs_mod.load(self.jobs_file)`，与状态回写同源（此前 tick 读默认路径，
  "崩在投递中间不重投"的断言因此是恒真的），并补手改即生效用例；C2 直接断言会话键 `p:cron:daily`
  且 `sessions` 无任何 `g:` 键。三处变异均红。
- **门禁**：全量本机 `167 failed / 3423 passed / 84 skipped`——逐条核对全部是存量 POSIX-only
  （`os.O_NOFOLLOW`、权限位、msys `df`/`age`）与 Windows 路径分隔符类，零新增；ruff/pyright/
  `check_privacy`/`check_review_docs` 全绿。CI 未跑（分支未推送）。
- **唯一残留**：`.env.example` 补 `AGENT_CRON_DIR=data/cron` 与 `AGENT_GROUP_EXTRA_SKILLS=`，
  该文件被本机 DSH 凭据围栏挡住，改由用户手工补。
- 详细改法/变异/回滚见 `review/FIX-group-guest-mode.md`。