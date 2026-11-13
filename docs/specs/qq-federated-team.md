# agent-demo 框架吸收与 QQ 群联邦协作 Spec

- 版本：0.1（评估草案，尚未实施）
- 评估日期：2026-11-13（Asia/Shanghai）
- 承载项目：agent-demo，当前 UGREEN 分支
- 部署前提：A 在本人绿联 NAS，B 在朋友的独立服务器；两个不同 QQ 账号，同一 QQ 群，运行同版 agent。
- 通信约束：Bot 间只通过该 QQ 群通信；不要求互通内网、开放新端口、共享数据库、VPN 或中继服务。
- 评估范围：阅读代码、可行性评估、设计与验收标准；评估阶段没有修改三个项目的代码、配置、分支或部署，没有提交或推送。
- 风险分级：本轮为设计文档；后续实现属于 High，涉及跨所有者授权、消息幂等、并发、生命周期及数据库迁移。

归档说明：本文件记录 2026-11-13 的只读评估；§12 的工作区状态与探测结果属于该次评估记录。后续 CI 修复见 BACKLOG §6.18。仓库内引用使用相对路径，外部参考固定到评估时的 Git commit。

## 1. 评定结论

| 目标 | 评定 | 依据与边界 |
| --- | --- | --- |
| 吸收 dsh-superagent-prototype 的好框架 | 可行，high | 移植领域模型和约束，在 Python 中实现；保留现有 NoneBot 薄适配层、agentcore、PG、记忆、预算与权限体系。不是把 TypeScript/DSH 插件直接装进来 |
| 借鉴 DeepSeekBot 的 Team 协作 | 可行，high | 借鉴可信发送者、持久 Inbox、Assignment 回报、因果链与防循环；其 Host/DSH、LAN/Connect 传输不是当前 QQ 通道的现成实现 |
| 两台不同服务器、同一个 QQ 群互相派工 | 有条件可行，high；真实收发 unknown | 群充当传输介质，双方各自运行任务与保存状态。先实测 A→B、B→A 原生群消息与 @ 段，不假定协议端或 QQ 会保证可达 |
| 互相 review、校验、提 issue | 分阶段可行，high | 先结构化文字与工件审核、issue 草稿；代码执行需独立工作目录和受限执行器；外部 issue 发布需单独的仓库凭据、权限和去重 |
| 强一致调度、可靠离线队列、任意服务器远控 | 不纳入本方案承诺 | 纯 QQ 无法据此证明可靠投递或全局一致性。任务管理不等于获得朋友机器或本人 NAS 的管理员权限 |

建议结论：进入 G0 双机通信验证和 M1 本地任务模型设计是合理的；G0 未过，不进入跨机正式实现。不要一次搬入两个参考项目的完整运行时。

状态标记：
- verified：本次实际执行得到，写明执行范围。
- high / low：静态代码分析的高 / 低置信推断。
- unknown：本轮环境或部署未验证。
- 本文全部 MUST、需求与验收标准都是拟议目标，不表示现有功能或已通过测试。

## 2. 本次证据与核查范围

本地快照：agent-demo UGREEN / aaa8d0c9bc4bcdc7284401058acbedf4669850d0 / 1.0.3b1；dsh-superagent-prototype main / 8c32a9d；DeepSeekBot main / ecd53b773。两个参考仓库是本地快照，后续实现前须重新核对变化。

| 编号 | 发现 | 等级 | 一手依据 |
| --- | --- | --- | --- |
| E01 | 当前分支 UGREEN，工作区最初干净；agentcore/multiagent 只有空壳 __init__.py | verified | git status --short --branch；本次文件枚举；[空壳](../../agentcore/multiagent/__init__.py) |
| E02 | 当前聊天过滤自己，但 peer @ 本 bot 会通过 trigger_rule；peer 还会被群上下文记录器接收 | verified（合成事件） | 对 [matcher.py](../../plugins/qq_agent_adapter/matcher.py) 的三个真实函数做 AST 提取执行，输出见 §12；未运行完整 NoneBot 生命周期 |
| E03 | 群入口 ACL 与管理员技能是两层检查，不能把 peer QQ 填进 SUPERUSERS 来“打通协作” | high | [ACL](../../plugins/qq_agent_adapter/acl.py)、[registry](../../agentcore/skills/registry.py)、[permissions](../../agentcore/skills/permissions.py) |
| E04 | 现有 Engine 主要按 user/group 解析会话，没有现成的独立任务执行模型 | high | [engine.py](../../agentcore/loop/engine.py) 的 AgentEngine.run 与 resolve_session；本轮列举的 skills 中没有专门的 GitHub issue 发布工具 |
| E05 | 原项目已有预算、围栏、三态出站、PG 迁移与停机顺序，应复用 | high | [outbound](../../plugins/qq_agent_adapter/outbound.py)、[lifecycle](../../plugins/qq_agent_adapter/lifecycle.py)、[migrations](../../agentcore/memory/migrations/__init__.py)、[safety](../../agentcore/safety.py) |
| E06 | superagent 已将 Source/Trigger、Policy/Mandate、Ticket/Assignment、Executor 分开，核心通过 ports 解耦 | high | [model.ts](https://github.com/deepseek-ai/dsh-superagent-prototype/blob/8c32a9dc5d72c033816c6a8110b37f40cf94fba4/src/core/model.ts)、[ports.ts](https://github.com/deepseek-ai/dsh-superagent-prototype/blob/8c32a9dc5d72c033816c6a8110b37f40cf94fba4/src/core/ports.ts)、[intake.ts](https://github.com/deepseek-ai/dsh-superagent-prototype/blob/8c32a9dc5d72c033816c6a8110b37f40cf94fba4/src/core/intake.ts)、[policy.ts](https://github.com/deepseek-ai/dsh-superagent-prototype/blob/8c32a9dc5d72c033816c6a8110b37f40cf94fba4/src/policy.ts) |
| E07 | superagent Outbox 有持久回执和重试；其执行准备支持 shell，不宜照搬本项目权限与未知结果语义 | high | [outbox.ts](https://github.com/deepseek-ai/dsh-superagent-prototype/blob/8c32a9dc5d72c033816c6a8110b37f40cf94fba4/src/app/outbox.ts)、[effects.ts](https://github.com/deepseek-ai/dsh-superagent-prototype/blob/8c32a9dc5d72c033816c6a8110b37f40cf94fba4/src/app/effects.ts)、[执行文档](https://github.com/deepseek-ai/dsh-superagent-prototype/blob/8c32a9dc5d72c033816c6a8110b37f40cf94fba4/docs/003-execution.md) |
| E08 | DeepSeekBot Assignment 经 Inbox 回报，ask 结束当前 turn，后续 answer 再恢复，不阻塞主协调器 | high | [ADR-0059](https://github.com/BotHarness/DeepSeekBot/blob/ecd53b7730ba05616fd080a5fcba5d5dfb47ef42/docs/adr/0059-assignment-collaboration-round-trips-through-the-bot-inbox.md)、[assignment-collaboration 测试源码](https://github.com/BotHarness/DeepSeekBot/blob/ecd53b7730ba05616fd080a5fcba5d5dfb47ef42/packages/core/test/assignment-collaboration.test.ts)；本次未运行该套件 |
| E09 | DeepSeekBot 有跨 Host 收信、发送者绑定、因果跳数和未知投递结果定义；LAN/Connect 需要各自资格验证 | high | [bot-network.ts](https://github.com/BotHarness/DeepSeekBot/blob/ecd53b7730ba05616fd080a5fcba5d5dfb47ef42/packages/core/src/runtime/bot-network.ts)、[bot-peer-channel.ts](https://github.com/BotHarness/DeepSeekBot/blob/ecd53b7730ba05616fd080a5fcba5d5dfb47ef42/packages/core/src/devices/bot-peer-channel.ts)、[ADR-0277](https://github.com/BotHarness/DeepSeekBot/blob/ecd53b7730ba05616fd080a5fcba5d5dfb47ef42/docs/adr/0277-cross-host-bot-dms-use-online-communication-without-outgoing-queues.md)、[架构](https://github.com/BotHarness/DeepSeekBot/blob/ecd53b7730ba05616fd080a5fcba5d5dfb47ef42/docs/architecture/botharness-architecture.md) |
| E10 | 两台实际部署是否收到对方的群消息，QQ 限流/禁言、离线补发、可承载长度、NAS 执行能力 | unknown | 本轮未连接实际 QQ、NAS 或朋友服务器；不据静态代码宣称双机验收通过 |

协议依据：OneBot v11 群事件提供外层 user_id/group_id/self_id/message_id，[消息事件规范](https://github.com/botuniverse/onebot-11/blob/master/event/message.md)；群发送接口返回 message_id，[公开 API](https://github.com/botuniverse/onebot-11/blob/master/api/public.md)。这些字段支持寻址和来源检查，不构成本方案的送达保证；标准 API 清单也不提供可依赖的通用群历史重放队列。NoneBot 可用优先级和阻断隔离协议入口，[官方 matcher 文档](https://nonebot.dev/docs/advanced/matcher)。

## 3. 具体吸收什么

| 来源 | 吸收设计 | 在 agent-demo 中的落点 | 明确保留 / 不直接迁入 |
| --- | --- | --- | --- |
| superagent | Trigger → Gate → Ticket → Assignment → Report | agentcore/multiagent 下的纯 Python 领域对象与服务 | 普通 QQ 聊天继续现有路径；只有显式“任务”进入工单路径 |
| superagent | 确定性授权先于模型判断，Mandate 不可变 | 接单策略、资源范围、预算、截止时间、策略版本快照 | 文本说“管理员已批准”不等于授权；范围扩大必须新任务 |
| superagent | 任务状态独立于 LLM 会话；执行器为 port | TaskService、ExecutorPort；每个 Assignment 独立会话 | 不用一次 engine.run 返回值充当整张工单生命周期 |
| superagent | 隔离目录、并发槽、恢复与人工 attention | 本地受限执行器与任务队列 | 不搬任意 shell prepare；不换成 DSH/Node 运行时 |
| superagent | 持久 Effects / Outbox 的责任划分 | 事务写入任务事实与出站意图，实际发送在事务外 | 不照搬重试规则；未知结果保持未知，不自动重发 |
| DeepSeekBot | canonical event + per-recipient Inbox + 状态投影 | 每端的 TeamEvent / Inbox / TaskStore | 不跨机做数据库事务，不复制整个聊天历史或记忆 |
| DeepSeekBot | 非阻塞 Assignment 报告与 ask/answer | 先返回接单事实，后台执行；等待问题释放活跃 turn | 已收到、已接单、已完成、已验证分别记录 |
| DeepSeekBot | 来源身份、membership epoch、因果 root/parent/hop | peer 注册、撤销代际、任务因果链 | 同版本、同昵称、同群均不自动成为可信 peer |
| DeepSeekBot | 只选一个通道发送，未知结果不换路补发 | 本方案只有 QQ 群传输 | 不引入其 LAN 多播、Connect、Noise HTTP 或手机配对体系 |
| 现有 agent-demo | 分层、双实现、迁移、权限、预算、围栏、生命周期 | 沿用现有基础设施与装配入口 | 不整库改写，不替换人格/记忆作用域，不开放管理员技能给友军 |

三个本地仓库的 LICENSE 均为 MIT（静态阅读）。后续若复制具体代码/文档片段，保留相应版权与许可证声明；领域思想迁移仍需适配本项目不变量。

## 4. 推荐架构：群传输 + 各端本地权威

~~~mermaid
flowchart LR
  H[群内人类：明确选 A 或 B] --> Q[同一个 QQ 群]
  Q <--> PA[A 端 OneBot / QQ 协作适配器]
  Q <--> PB[B 端 OneBot / QQ 协作适配器]
  PA <--> CA[A 端 TeamService / 本地 PG]
  PB <--> CB[B 端 TeamService / 本地 PG]
  CA --> XA[A 的受限执行器 / 独立工作目录]
  CB --> XB[B 的受限执行器 / 独立工作目录]
~~~

部署 A、B 完全对等：任意一端都能成为某个任务的 owner；同一根任务只有一个 owner，没有全局主节点选举。owner 管范围、委派与最终结论，worker 管自己实际执行过什么。A 的数据库是 A 的权威，B 的数据库是 B 的权威；通过签名事件交换事实，群聊天记录不是唯一任务数据库。

入站顺序：原始群事件 → 协作分类 → 外层身份/群检查 → 严格解码/验签/去重/权限 → 持久 Inbox → 明确接单或拒绝 → 专用 Executor。协议分类必须早于聊天、防抖、群上下文、人格成长与记忆抽取；已识别协议帧即使校验失败也不回落普通 LLM 聊天。普通群聊仍只按既有唤醒词/@ 规则处理。

出站分为机器帧与人类摘要。机器帧必须保持完整，复用现有节流与三态错误分类，但不走长回复的自动拆段/合并转发/文件降级；那会改变协议。协调者在有结果或需要人介入时才发简洁摘要。

## 5. 核心 Spec 表

下面是实施需求，全部状态为“拟定、待验收”。P0 表示首版必须守住，P1 表示后续能力。G0/M1–M4 的含义见 §10。

| ID | 阶段 / 优先级 | 需求与边界 | 可判定验收标准 |
| --- | --- | --- | --- |
| S01 | M2 / P0 | 协作默认关闭，独立于普通聊天 | 关闭后同一普通请求与当前行为一致；协议帧不启动任务或 LLM；开启配置缺失时明确拒绝启用 |
| S02 | G0 / P0 | 两端经原生 QQ 群消息收发，不新增 Bot 间网络服务 | 双端各低速发送 10 次探测，记录 20 次独立 probe 的原始外层 sender/group、到达与回执；无 peer IP 连接 |
| S03 | G0 / P0 | peer 显式登记：agent_id、QQ 号、允许群、公钥、relationship epoch | 同名普通群友、未知公钥、换 QQ 号、未登记群均不能成为友军；两端管理员分别配置后才能互通 |
| S04 | G0 / P0 | 所有机器帧绑定外层 sender、收件方、群、epoch 并验签 | 修改任一签名字段、复制到别群、引用转发或冒名 QQ 均拒绝；不调用 LLM，不自动回复风暴 |
| S05 | M2 / P0 | 协作入口优先隔离，格式或签名失败不得降级聊天 | 向 bot @ 发送坏帧，计数断言普通 chat、群上下文、记忆抽取和主动联系路径均未收到该帧 |
| S06 | M1 / P0 | 人类请求必须有现有 ACL 加 task/能力许可；模型不发明授权 | 白名单群内无 task 权限者不能启动有副作用任务；不改 SUPERUSERS、不恢复通配、不信正文里的身份声明 |
| S07 | M2 / P0 | 接收方按本地服务委托授权接单，权限取交集 | peer 宣称 origin_user=超管、请求 run_shell/重启/数据库等均不能越过本地 grant；本地 owner 的身份不被伪造 |
| S08 | M1 / P0 | 本地 Ticket/Mandate 与 Assignment 分离 | 一个任务从创建到报告具备固定范围、授权来源、预算和结果；worker 退出不自动等于工单完成 |
| S09 | M2 / P0 | task_id 全局带 owner 命名空间，单根任务唯一 owner | A/B 同时创建 UUID 不串单；B 不能改 A 的范围或终结另一条根任务；重复委派不创建第二份 Assignment |
| S10 | M1 / P0 | 每个 Assignment 独立会话、受限工具与 workspace | 同一 peer 的两任务无历史/文件串用；群人格和用户记忆不被当作任务级管理员授权 |
| S11 | M2 / P0 | Inbox 去重、任务接单、必要回执意图在本地同一事务 | 同一消息注入 100 次只接单一次；并发双插入只有一个赢；accepted 只在持久提交后发出 |
| S12 | M2 / P0 | 崩溃恢复区分未尝试、正在发送、已接单、已执行 | 每个故障点重启后无第二次外部副作用；sending 变 unknown；读写状态能说明待核查事项 |
| S13 | M2 / P0 | 超时/断连/缺回执是未知，不自动补发或另派执行 | 模拟发送后抛超时，发送次数保持 1；不改写为 failed，不转普通聊天、不换通道、不自动改派 |
| S14 | M2 / P0 | 帧有 TTL，任务另有截止时间；不承诺 QQ 离线补发 | 过期委派不执行；超时只标 waiting_peer/unknown；已接单任务重启可恢复其本地状态 |
| S15 | M2 / P0 | owner 规格版本、worker 报告序号分别单写；结果绑定 Assignment | 乱序旧 progress 不覆盖 completed；旧 Assignment 结果不能关新任务；终态后同范围不自动重新执行 |
| S16 | M2 / P0 | ask/answer 持久化且非阻塞 | worker 提问后释放当前 turn；answer_to 精确匹配后继续；重启仍看到原问题；重复 answer 不重复执行 |
| S17 | M2 / P0 | 因果链、委派深度、回合、消息、时间与费用限额 | A→B→A 循环在 host 硬限制处终止；ACK 不再 ACK；超过配额不开 LLM、不继续派工 |
| S18 | M2 / P0 | roster 只展示登记身份、公开能力和最近观察状态 | hello 不能增加权限；last_seen 过期显示“未确认可达”；不同 build 的兼容协议可协作，不兼容明确拒绝 |
| S19 | M2 / P0 | 工件内容经 QQ 传递或为双方可独立授权读取的引用；不传本地路径当内容 | B 收到 A 的路径不能直接 fs_read；分片缺失/哈希错则 needs_input；不把部分 diff 当完整工件 |
| S20 | M3 / P1 | 改代码任务使用本地登记 repo 的隔离 checkout / 执行器 | 远端不能给任意 cwd、命令或 Git 地址；每任务独立目录与分支；测试不带宿主秘密；没有 grant 就只分析 |
| S21 | M2–M3 / P0 | review 是独立 Assignment，锁定工件版本 | 审核报告注明 digest/commit、发现位置与置信度；A 换版本后旧 review 自动失效；无证据不写 verified |
| S22 | M3 / P1 | verify 报告区分运行结果与推断 | 有命令、环境、工件版本、退出码与日志引用才标“远端声明 verified”；A 未复跑不冒充自己的验证；不能执行则 unknown |
| S23 | M2 / P0 | 先支持 issue 草稿与本地问题台账 | 输出标题、复现/证据、影响、AC、关联任务；使用 repo+工件+问题指纹去重；不依赖 GitHub 写权限 |
| S24 | M4 / P1 | 外部 issue 发布是独立受控动作，默认关闭 | 指定本地登记仓库与凭据；管理员批准精确标题/正文后发布；超时先查询已发 marker，未知时不重复创建 |
| S25 | M2 / P0 | 本地主人可查 roster/task、暂停、取消、撤销 peer | 查询无私钥/敏感正文；远端不能管理本机 roster、提取 /2fa 或取消其他人的任务；取消有确认事实 |
| S26 | M2 / P0 | 审计记录 provenance、授权判定、任务边与投递状态 | 审计能从人类请求追到 peer 结果；日志不含 key、私聊记忆或默认完整源码；拒绝风暴日志有界 |
| S27 | M1–M2 / P0 | TaskStore 端口与内存/PG 语义一致，DDL 走现有迁移链 | 全新 qqagent_test/scratch 上验收，合同用例覆盖唯一性/事务/版本；生产持久协作无 PG 则拒绝接单 |
| S28 | M2 / P0 | 保留原停机顺序，将任务停止准入与 checkpoint 接入 | 调度停止后不再启动任务；dequeue 停止、在途 checkpoint 完成后才关 store；超时与重复 shutdown 可判定 |
| S29 | G0–M2 / P0 | 协议独立版本和 capability 协商，严格闭合 schema | major 不兼容或缺 required capability 明确拒绝；未知 kind、重复 JSON 键、非 ASCII QQ 标识和超限输入拒绝 |
| S30 | M2 / P0 | 撤销/换钥更换 epoch，旧任务不能借重新配对复活 | 撤销立即拦新接单和后续副作用/发送；重启后仍有效；已发生副作用留审计；旧 epoch answer/result 不复活任务 |
| S31 | M2 / P0 | 群内明确选一个根任务协调者，避免双重受理 | 人类发起 team 任务必须唯一 @ 或显式选定 owner；同时 @ 两 bot 的模糊指令不自动双跑；普通聊天不改语义 |
| S32 | 全阶段 / P0 | 文档、双机验证、错误注入和变异复核作为交付门槛 | 新用例故意改坏实现后必须失败，再恢复精确修改；最终带 PG 全套件、lint/type 门禁及 G0 双机记录，不能以 mock 替代 |

## 6. 协议与数据契约草案

### 6.1 身份与信任

每个部署有独立 agent_id、持久密钥和 QQ 号；同版代码不意味着同身份。管理员在各自机器登记准确的 peer QQ、公钥指纹、允许群和授权能力；群里看到 hello 只更新已登记对象的公开能力/last_seen，不自动信任新对象。首次登记与换钥需要两位主人核对指纹，不把一个可自行声明的群名片当信任根。私钥与信任策略不放入可由 fs_write 写入的 workspace，不在群里发送秘密。

建议使用成熟库的 Ed25519 签名（[RFC 8032](https://www.rfc-editor.org/rfc/rfc8032)）及 JCS 规范化 JSON（[RFC 8785](https://www.rfc-editor.org/rfc/rfc8785.txt)），不自实现密码算法。签名证明登记私钥持有者发出该帧，不证明任务内容正确，也不提供内容保密。QQ 账号/OneBot 入口被攻破是剩余信任风险；协议不能将其消除。

最小授权分两段：
1. A 从真正的 QQ 事件检查人类请求和本机 task 权限，生成有界 Mandate。
2. B 只信“A 是登记的服务主体，且我本地允许它请求这些能力”。A 带来的 origin_user 是审计来源，不能在 B 冒充该用户，更不能变成 B 的 SUPERUSER。

有效能力 = A 的可委派范围 ∩ B 给该 peer 的本地服务 grant ∩ 本次任务范围 ∩ B 的权限级别/资源限制。现有管理员技能保持仅管理员使用；新的 peer 执行器只暴露单独实现、可验证边界的任务能力。不得通过改 user_id 或添加友军到 SUPERUSERS 复用管理员通道。

### 6.2 消息格式

传输形态：原生 @收件 bot + 一个 text 段，text 是固定前缀 [AGENT-TEAM/1] 加 base64url 编码的完整签名 JSON。只接受外层正常群 message 事件中的直接帧；禁止从引用、合并转发、图片 OCR 或历史摘要解析可执行帧。适配器可能调整 @ 段，需 G0 同时验证原始事件与预处理事件；若 @ 丢失，只可在已验签且 to/group 精确匹配的协议入口寻址，不能放宽普通聊天唤醒规则。

| 字段 | 语义与约束 |
| --- | --- |
| v / kind | 协议 major / 闭合消息类型；v1 不兼容时拒绝，不降级成自然语言协作 |
| msg_id | 发送端生成的 UUID；不依赖两端 OneBot message_id 一致 |
| from / to / group_id | 登记的发送者、收件者和指定群；与真实外层 user_id/group_id、本机配置交叉检查 |
| epoch / kid | 本次信任关系代际与登记密钥；撤销后旧代际永久无效 |
| root_id / task_id / assignment_id / parent_id | 根任务、具体工单/派工与因果父事件；所有引用必须存在或进入有界等待 |
| hop / owner_revision / report_seq | 继承因果深度；任务 owner 固定规格版本；worker 的单调报告序号，彼此不争写一个全局 revision |
| issued_at / expires_at | 帧有效时间；与任务 deadline 分开；有限时钟偏差，明显偏差拒绝并诊断 |
| body / artifacts | 有界、严格校验的结构化请求或报告；正文仍是不可信内容 |
| sig | 对除 sig 外完整对象做域分离后的规范化签名；重编码不能改变规范化内容 |

消息类型首版限定：HELLO、TASK_OFFER、TASK_ACCEPT、TASK_REJECT、TASK_REPORT、TASK_ASK、TASK_ANSWER、TASK_CANCEL、TASK_CANCEL_ACK、TASK_STATUS_QUERY、TASK_STATUS、ARTIFACT_PART。报告再区分 progress/completed/blocked/failed；不让模型直接拼签名、决定 ACL 或执行协议状态迁移。

机器帧初始设计上限为完整文本 1800 字符且 UTF-8 不超过 8 KiB，实际取该上限与 G0 观测安全阈值的较小者。该值是候选工程限额，不是 QQ 官方保证。正文带大小限制、禁止重复键/无穷数字、嵌套上限；先做便宜的来源与长度校验，再解码验签，不让垃圾帧耗尽 CPU。

小工件采用单独签名分片：artifact_id、sha256、总字节数、index/count 与内容。候选限额为每工件 16 KiB、最多 32 帧、10 分钟组装窗口、每 peer 最多 2 个未完成工件；不压缩、不自动解压。只有收齐、长度与 hash 一致后才进入任务。大仓库/长 diff 拒绝并要求缩小范围；QQ 群文件是未来可选扩展，未做双端验证前不作为首版依赖。

群成员能看到所有机器帧内容，base64 和签名不加密。只发送可向该群公开的最小文本/工件；不发 API key、私聊记忆、数据库导出或未经允许的私有源码。若以后要求保密代码协作，需另做加密内容与密钥管理设计，不能宣称首版已经具备。

### 6.3 本地数据对象

| 对象 | 唯一权威及用途 |
| --- | --- |
| PeerRegistration | 本机登记的 QQ/agent/key/epoch/group/grants；远端 hello 不能改权限 |
| Trigger / Mandate | 原始可信入站元数据与不可变授权；外部正文单独作为不可信数据 |
| Task | owner_agent_id + UUID；kind、immutable scope、deadline、budget、artifact revision、最终结论 |
| Assignment | 一次将具体任务绑定到 local/peer executor；记录接单、执行、等待、取消与结果 |
| TeamEvent / Inbox | 不可变消息事实、接收去重、处理状态与唤醒指针；不把接收直接记为完成 |
| OutboxReceipt | 准备/发送中/确定未发/已发送/未知、关联 QQ message_id；不是无限自动补发队列 |
| ArtifactManifest | 内容 hash、版本、大小、来源、有限保留期与引用；远端绝对路径仅是文本 |
| IssueDraft / AuditEvent | 问题草稿、去重指纹；独立的操作与授权审计，不成为第二份私有聊天记忆 |

TaskStore 是独立领域端口，可有 InMemoryTeamStore 与 PgTeamStore，测试双实现合同；复用 PG 装配/事务基础设施，不私自抓 PgMemoryStore 的私有连接池，也不另开 SQLite 事实源。新增表注册到现有 migrations，不修改已应用 SQL。生产协作要求持久 PG；内存实现只服务测试或明确的临时演示，不能对外承诺重启恢复。任务事实与最小 Inbox/Outbox 元数据保留策略必须与去重 TTL 一起定义；不得清掉去重后允许旧帧再次执行。候选帧 TTL 5 分钟、时钟宽容 2 分钟，去重/撤销 tombstone 至少保留 30 天；任务有独立 deadline，上述数值待 G0/容量评估后冻结。

## 7. 状态、恢复与未知结果

业务任务状态与消息投递状态分别建模：
- 任务：proposed → offered → accepted → running → waiting_peer / waiting_human → completed / failed / cancelled。未收到回执可停在 offered + delivery_unknown，不推断对方失败。
- 投递：prepared → sending → sent / known_unsent / unknown。sent 只表示本地发送 API 的结果；accepted 只表示对方持久接单；completed 是 worker 的完成报告；verified 还需要可审查证据。
- scope 不可变；范围扩大创建新 Task。owner 规格和 worker 报告分别单写；不实现跨机全局锁或共享自增状态。

| 故障场景 | 必须行为 |
| --- | --- |
| 事件回调重复 / 同帧换一个 QQ message_id 重发 | 按 receiver+peer+epoch+msg_id 及 Assignment 唯一约束去重，不二次执行 |
| B 已落库但 ACCEPT 丢了 | A 标未知或 waiting_peer；必要时发新的只读 STATUS_QUERY；不得自动重派原副作用 |
| 发送 API 超时 / 连接断开 | 不知道是否送出，记 unknown；不重发、不换形式；ACK 不触发 ACK 链 |
| 重启前 prepared 尚未调用外部接口 | 恢复为待确认/重新检查授权的意图；首版不自动补发，等待 owner 明确继续 |
| 重启前已记 sending，未记结果 | 恢复为 unknown；先核查对端和外部副作用，不自动重放 |
| 明确在本地拒绝、尚未发送 | 可在重新检查权限后人工重试；首版不引入自动运输重试队列 |
| B 离线、被禁言或消息过期 | 不能承诺自动恢复投递；已接单的本地工作可持久恢复；新发送必须仍在授权和期限内 |
| CANCEL 未确认 | 显示 cancel_pending；不能据此认为 B 已停止，也不能自动找别的 bot 执行同一写动作 |
| 已完成后才收到 CANCEL / 旧 progress | 保留完成和取消事实；不回滚成 running，不假装撤销已发生的外部操作 |
| peer 被撤销、换钥、恢复旧备份 | 旧 epoch 不复活；旧备份恢复后协作先关闭，核对任务与信任代际后再开启，避免重复副作用 |

初始限额候选：每端 1 个活跃远端 Assignment、2 个根任务、每根最多 4 次跨 bot 委派、8 个模型 turn、64 条协议消息（包含工件分片）、15 分钟任务 deadline；每 peer 每小时最多接收 128 帧，叠加本地费用硬上限；不启用自动再委派。分片发送前预计算帧数及剩余额度，不足就拒绝整个工件，不发送半套；上限不表示每轮应耗尽额度。控制响应只回到原发送者，不开启新任务，且不请求对控制响应再回执；所有消息含控制帧也计入消息总额。后续允许再委派时保留 root/parent，host 计算深度并检测 A→B→A 回路，模型不能通过新建 root 绕过。新 root 只能由真实本地人类请求或明确的本地授权入口创建；执行中的模型调用由 host 继承既有因果链，不能自填 root。远端可能谎报自己的链，因此独立的 peer 小时额度与费用闸门必须兜底，不能只信 hop。额度是提议默认值，需纳入配置 schema 并经双机负载验证。

不默认周期 heartbeat 刷群；HELLO 按启用/明确查询触发并限频。最近看到不等于在线。主协调器等待远端时释放活跃 LLM 槽，继续处理本机人类消息；每端费用由各自主人承担，按 peer/root 记账并受各自本地预算约束。

## 8. 派工、Review、校验与 Issue 的真实含义

推荐第一条端到端旅程：
1. 人类唯一 @A：“分析这段可公开 diff，找 B 做一次独立 review，输出 issue 草稿。”
2. A 检查权限并生成本地 Ticket/Mandate，锁定 diff 的 hash，建立 B 的 review Assignment。
3. A 经 QQ 发送任务与必要工件；B 校验 A 的服务身份和本地 grant，持久接单。
4. B 独立分析；无代码执行能力就标静态 high/low，不虚构测试。需要补充时发 ASK，结束 turn。
5. B 回传带工件 hash、发现位置、依据和置信度的结构化 REPORT。结果是外部不可信内容，进入 prompt 仍需围栏与脱敏。
6. A 核对 Assignment、版本、完整性与范围，确认有依据的问题，形成 issue 草稿并给群里一条摘要。
7. 未来启用发布能力时，由本地登记的 issue 发布主体执行独立审批；不把 B 的报告当作发布授权。

| 能力 | 首版可做 | 必需补齐 / 不能混淆 |
| --- | --- | --- |
| 相互指派干活 | 文字分析、设计、资料整理、小工件审核、issue 草稿；A/B 可交换角色 | 自主改代码、测试执行需要 M3；不能因为有 run_shell 就认为已有安全编码工作流 |
| review | 针对同一 commit/diff hash 的独立判断与发现 | 两个 bot 同意不是正确性证明；同模型可能同错；更换工件必须重新 review |
| 校验 | 验签、schema、工件 hash、断言检查；具备环境时另行实跑命令 | “哈希一致”不等于“功能通过”；远端报告与本地复跑分别标记 |
| 提 issue | 本地问题台账 + 群内草稿，含来源、影响、证据、AC | 外部 GitHub 等站点 API 是可选动作；仍可只用 QQ 做 bot 间通信，但两端需各自独立访问被授权的外部服务 |
| 分布式管理 agent | 公共能力、任务状态、队列、取消与撤销、自身限额 | 不远控对方宿主机，不同步全部人格/记忆，不要求共享文件系统 |

新建外部 issue 需要仓库级凭据与最小授权；去重使用目标 repo + finding 指纹与持久操作 ID/正文 marker。调用后丢响应时先查询；查不到也不等于一定未发布，无法确定就交给人处理，不能盲重发。QQ 群里不能完成管理员 /2fa 取码；复用本项目私聊管理员取码及现有安全流程，peer 无权取得或代填。

## 9. 拟议代码落点与项目纪律

| 模块 | 拟议职责 | 边界 |
| --- | --- | --- |
| agentcore/multiagent/model.py、policy.py、service.py | Task/Mandate/Assignment、确定性状态机与能力授权 | 纯 Python，不 import nonebot |
| agentcore/multiagent/protocol.py、identity.py | 严格 schema、签名验证、peer/epoch 与因果检查 | 宿主提供可信外层元数据；正文不创建身份 |
| agentcore/multiagent/store.py、inbox.py、outbox.py | 事务、去重、接收事实、投递三态和恢复 | 不把未知结果视为失败；生产需持久 PG |
| agentcore/multiagent/executor.py、artifacts.py | 有界任务执行、独立上下文、工件版本及分片 | 不直接复用聊天用户的管理员权限；无任意目录/命令 |
| plugins/qq_agent_adapter/team_route.py、team_transport.py | 协议帧优先分类、真实 QQ 身份、群收发、节流 | 平台逻辑只在 plugins；新路由要真实装配/注册测试 |
| plugins/qq_agent_adapter/__init__.py、lifecycle.py | 服务装配、后台 worker 生命周期与停机接线 | 任务停止接入/检查点应在 store 关闭前；不破坏 scheduler→flush→aclose |
| migrations 新文件与装配 | 新 TaskStore 表、约束、版本登记 | 只增迁移，不改已用迁移；空测试库验证，不复制生产隐私数据 |
| 后续 web 只读投影 | roster、task、unknown、audit | peer 管理/授权写入首版留本地配置；若增加 web 写入必须补 2FA、审计、改前备份 |

静态配置沿用 UGREEN 的 config/agent.json、config/agent.env 与 .env 到 os.environ 的现有装配链，优先级遵守现有配置文档；候选入口为 AGENT_TEAM_ENABLED（默认 false）、AGENT_TEAM_PEERS_FILE、AGENT_TEAM_KEY_FILE，结构化 peer/grant 登记放在本地受保护配置目录。所有新开关走 boolenv；新增 env 同步 .env.example 和 settings_spec.ENV_SPECS。信任注册、密钥位置、能力 grant 是安全配置，首版不放入 web 通用可写设置。容器沿用 config 目录挂载和运行时子目录策略，密钥不被整卷 data 挂载或 workspace 覆盖；NAS 部署不通过协作偷偷接出宿主机管理通道。

M3 的代码执行必须使用部署管理员预置的隔离执行环境：仅挂载该任务目录，不挂宿主秘密、其他任务目录或 Docker socket；限制 CPU/内存/PID/时间，默认关闭测试代码网络。仅清理环境变量或换 cwd 不构成执行隔离。现有 bot 容器的宿主机操作限制保持生效；没有合格执行器就拒绝“实跑测试/改代码”，只提供静态分析。

## 10. 分期与交付门槛

| 阶段 | 可观察结果 | 大致改造量 / 风险 | 进入下一阶段的条件 |
| --- | --- | --- | --- |
| G0：通信与信任可行性验证 | 两台真实设备同群的双向签名探测、假冒拒绝、超时记录；不执行工作 | 小 / High 安全边界 | 两端稳定拿到真实 sender/group，帧与 @ 行为可解释；公开信息与指纹配对经过双方主人核对 |
| M1：本地吸收框架 | 一个本地分析任务能以 Ticket→Assignment→Report 完成；可重启查看；普通聊天不受影响 | 中 / High 并发、schema | 独立会话与权限、TaskStore 合同和空 PG 迁移通过；尚不靠 QQ 自动派工 |
| M2：最小 QQ Team 闭环 | A 派文字/小工件给 B review，B 回报，A 生成 issue 草稿；B 同样可做 owner | 大 / High 跨所有者授权与幂等 | §5 首版 P0 通过；双机未知结果、重启、撤销、限额和循环用例通过 |
| M3：真实代码协作与验证 | 各自在授权 repo 的隔离执行环境工作，交换锁版本工件，独立 review/复跑 | 大 / High 代码执行和数据隔离 | NAS/朋友服务器资源、仓库权限、隔离目录、凭据隔离和实际命令证据通过 |
| M4：外部 issue 与管理面 | 可审阅批准后的正式 issue 发布；必要的 web 操作面 | 中 / High 外部副作用 | 仓库级凭据、2FA/审计/备份、未知结果核查与去重全部落地 |

顺序建议：先 G0 再 M1，随后 M2；M3/M4 可以按需要选择。不要一开始做自动选主、全群自动发现、全量记忆共享、任意代码远控、多 transport fallback、大文件分发或完整 DSH UI。

这里的改造量是基于静态阅读的相对估计，不是工时承诺。G0 的实际 QQ 行为和 M1 的会话/权限接口结果，可能明显改变后续工作量。

## 11. 验证计划（未来实现，尚未执行）

| 层次 | 必测负例与断言 |
| --- | --- |
| 身份/协议 | 假 QQ、假公钥、换群、换收件者、旧 epoch、过期帧、重复键、畸形 base64、超大/深 JSON、引用转发，全部零 LLM / 零副作用 |
| 状态/存储 | 重复 100 次接单、并发插入、乱序终态、scope 扩大、跨 Assignment 报告、缺分片、hash 冲突；内存/PG 同合同 |
| 故障注入 | 外部调用前/后、接单提交前/后、worker 执行前/后、报告/取消回执丢失、store 关闭中重启；检查没有二次副作用 |
| 权限 | peer 伪造管理员来源、读 .env、读别任务、取 /2fa、改配置、重启宿主、任意 curl/URL/cwd；本地明确拒绝 |
| 成本/循环 | A↔B 循环、ACK 链、重建 root、超额与离线；host 硬闸门生效，普通人类消息仍可处理 |
| 双机 G0/M2 | 真实 A/B 不同设备、不同数据库、各自协议端，同群双向请求；禁言/断网/重启、旧报文与换钥，不以同进程 mock 代替 |
| 变异复核 | 故意删验签、去重、grant、unknown 防重发、终态保护中的一处，相关用例必须失败，再精确恢复；不能 git checkout 丢失已有修改 |

实施后的候选命令（这些新增测试文件目前不存在，本轮没有运行）：

~~~text
python -m pytest tests/test_team_protocol.py tests/test_team_policy.py tests/test_team_state.py tests/test_team_route.py -q
TEST_DATABASE_URL=<只指向空 qqagent_test> python -m pytest tests/test_team_store_contract.py -q
TEST_DATABASE_URL=<只指向空 qqagent_test> python -m pytest -q
python -m ruff check agentcore plugins tests bot.py scripts
python -m ruff format --check agentcore plugins tests bot.py scripts
pyright agentcore
python scripts/check_review_docs.py
~~~

命令中的环境变量写法为示意，PowerShell/Linux 按各自 shell 设置；环境、Python、ruff/pyright 版本遵守 pyproject.toml 与 CI。若修改现有 MemoryStore，额外跑现有 test_store_contract.py / test_store_parity.py 与带 PG 套件。新增用例归入模块主题测试文件，不另起 test_review 批次文件。

## 12. 本轮实际验证与交付验收

本轮已执行：
- git status --short --branch：agent-demo 为 UGREEN...origin/UGREEN，初始无改动。
- git log / pyproject / 文件枚举：核对 §2 的本地基线和 multiagent 空壳。
- 对真实 matcher 的 _is_self_message、trigger_rule、_record_group_rule 做 AST 提取，在不加载 .env、不连接 NoneBot/QQ 的合成事件下执行，断言输出：
~~~json
{
  "self_message_triggered": false,
  "peer_at_triggered": true,
  "peer_no_at_triggered": false,
  "peer_recorded_as_context": true,
  "multiagent_python_files": ["agentcore\\multiagent\\__init__.py"]
}
~~~
以上只验证三个函数在该输入下的行为，不证明完整插件路由、真实 QQ 收发、ACL 或循环已被端到端验证。

可复跑的等价探测（在 agent-demo 根目录以 Python 执行）：
~~~python
import ast
from pathlib import Path
tree = ast.parse(Path("plugins/qq_agent_adapter/matcher.py").read_text(encoding="utf-8"))
class MessageEvent:
    def __init__(self, sender, receiver, at=False):
        self.self_id, self.sender, self.at = receiver, sender, at
    def get_user_id(self): return self.sender
    def get_message(self):
        return [type("Seg", (), {"type": "at", "data": {"qq": "111"}})()] if self.at else []
    def is_tome(self): return self.at
class GroupMessageEvent(MessageEvent): pass
class PrivateMessageEvent(MessageEvent): pass
names = {"_is_self_message", "trigger_rule", "_record_group_rule"}
ns = dict(MessageEvent=MessageEvent, GroupMessageEvent=GroupMessageEvent,
          PrivateMessageEvent=PrivateMessageEvent, _match_wake_words=lambda _: False,
          _plain_text=lambda _: "", _raw_dump_enabled=lambda: False)
module = ast.Module(body=[n for n in tree.body if isinstance(n, ast.FunctionDef)
                         and n.name in names], type_ignores=[])
exec(compile(ast.fix_missing_locations(module), "<matcher-probe>", "exec"), ns)
checks = [ns["trigger_rule"](GroupMessageEvent("111", "111", True)),
          ns["trigger_rule"](GroupMessageEvent("222", "111", True)),
          ns["trigger_rule"](GroupMessageEvent("222", "111", False)),
          ns["_record_group_rule"](GroupMessageEvent("222", "111", True))]
assert checks == [False, True, False, True], checks
print(checks)
~~~

本轮文档 AC：S01–S32 唯一且完整；每行包含阶段/优先级、需求、可判定验收；本文本地引用存在；§12 探测可以复跑；三个 Git 工作区不因本次评估产生代码/配置变更。交付前通过独立文档校验执行。

交付自检实测（verified）：以 python - 执行独立检查，排除代码围栏后核对需求表和本地链接，并执行本文内嵌探测。退出码 0；32 条需求顺序完整且唯一，23 个本地引用全部存在，探测输出 [False, True, False, True]。另对三个仓库执行 git status --short --branch / git diff --stat，均无文件改动，agent-demo 仍为 UGREEN。评估原稿当时独立保存在仓库外的 specs 目录；本文件是其入库版本，路径已适配。

未执行：三个项目的完整测试套件、真实双机 QQ、NAS 性能、PG 迁移或任何新协作实现。当前 PATH 的 Python 为 3.10.11，低于项目 >=3.11，且未发现项目 .venv/Scripts/python.exe；本轮没有为了设计评估安装运行环境。这不是功能失败证据，也不能写成测试通过。

## 13. 待实施时补齐的信息

以下不阻碍当前 spec，但分别是相关阶段的前置输入：
- G0：双方 bot QQ 号、允许群、双方主人身份；两端协议实现/版本及消息上报设置；只在部署配置登记，不写进公开 spec。
- M1/M2：首版允许的 task 发起者、每 peer 服务 grant 与费用上限；同一 bot 账号不得在两个部署同时复用同一 agent 身份。
- M3：授权仓库、各自主机可访问的 checkout、代码是否可向该群公开、NAS CPU/内存、可用隔离执行环境、实际测试命令。
- M4：目标 issue 平台/仓库与本地发布者凭据；若禁止一切 QQ 之外的外部服务访问，则保持 issue 草稿，不承诺正式发布。
- 后续：是否需要保密工件、大文件、更多 bots；出现真实需求后再扩展协议与授权，不把扩展预设为首版范围。
