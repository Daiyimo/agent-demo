"""agent_turn 执行体：到点让 agent 跑一轮，把结果投递到 jobs.json 指定的会话。

与 push/nudge 的分工：那两者是「配置里写死 prompt/模板，到点生成正文投递」；
agent_turn 是「把 message 当一轮用户输入丢给 AgentEngine」——agent 可以自己调
skill（执行脚本、查数据），产出什么就投什么。用户给的样例正是这个形态
（``执行 sh .../energy_report.sh，把 stdout 原样发到群聊``）。

**为什么复用 ``engine.run`` 而不是 ``generate_proactive``**：后者不带工具、
不写历史，是「一句话主动搭讪」用的；而 agent_turn 的 message 明确要求调用工具
（exec / message），必须走完整的 tool-loop。

**人格与历史**：人格走 default 分支（需求①改造后 = 根级 SOUL.md）；**不带历史**
——jobs.json 是无人值守任务，隔离单轮更可预期，也不会把群里几天的聊天灌进去。

**投递三态**：与 push/nudge 共用 ``Sink.send_once`` 的 sent/failed/uncertain。
结果不确定时**绝不重发**（出站铁律），状态记 ``uncertain`` 而非 ``ok``。

**群目标 ACL**（2026-10-29）：群目标必须在 ``ALLOWED_GROUPS`` 里，否则**不跑引擎、
不投递**，job 记 ``failed`` 并告警（按 job+目标去重，不刷屏）。此前只靠文档承诺，
代码完全不看白名单——一个手滑的真实群号就能让 agent 在未授权群里说话。
白名单由适配层注入（``agentcore`` 不得 import ``plugins``）；空集 = 一律拒绝
（fail-closed，与 ``acl.is_allowed`` 同口径）。私聊目标不受群白名单约束：jobs.json
是部署者本机的配置文件，发给谁本就是运维决定（与 ``PushService._target_allowed`` 一致）。
"""

from __future__ import annotations

import logging

from agentcore import tz
from agentcore.scheduler.jobs import CronJob, parse_target, update_state

logger = logging.getLogger(__name__)


def _zone_for(tz_name: str | None):
    """取 job 的时区对象：job 自带 tz 优先，缺省/非法回退进程统一时区。

    ``agentcore.tz.zoneinfo()`` 只接受 0 个参数（返回进程统一时区），所以命名时区
    必须自己构造 ZoneInfo——但**不能用裸 ``datetime.now()``**：仓库不变量要求时钟
    统一走 tz，否则 UTC 容器上「每天9点」会拖到北京时间 17:00 才响。
    """
    if not tz_name:
        return tz.zoneinfo()
    try:
        from zoneinfo import ZoneInfo

        return ZoneInfo(tz_name)
    except Exception:
        logger.warning(
            "cron job 时区 %r 不可用，回退进程统一时区（%s）",
            tz_name,
            tz.zoneinfo(),
        )
        return tz.zoneinfo()


# 「算不出下次执行时刻」与「解析失败」必须分开：前者是永触发表达式
# （`0 0 30 2 *` = 2 月 30 日，from_crontab 能解析但 get_next_fire_time 永远
# None）。tick 的到点判断 `if next_run_at_ms and ...` 把 0 当「首次运行」——
# 于是这类 job 每 60s 跑一次完整 LLM 回合 + 投递，无限烧 token 且永不标记
# failed。负哨兵让调用方能区分两者；0 仍表示「从没跑过 / 依赖缺失」。
_NEVER_FIRE = -1


def _next_run_ms(cron: str, tz_name: str | None) -> int:
    """算下次执行时刻（epoch ms）；解析失败返回 0，永触发返回 ``_NEVER_FIRE``。

    时区口径：**job 自带 tz 优先，缺省用进程统一时区**（``agentcore.tz``，
    ``AGENT_SCHEDULER_TZ`` 可覆盖）——与 ``reminder.next_cron_time`` 同一套判据。
    """
    try:
        from apscheduler.triggers.cron import CronTrigger
    except Exception:  # pragma: no cover
        return 0
    zone = _zone_for(tz_name)
    try:
        trigger = CronTrigger.from_crontab(cron, timezone=zone)
    except Exception:
        logger.warning("cron job 表达式无法解析：%r", cron)
        return 0
    # 基准时刻取自统一时钟再转到目标时区：两边同源，「下次执行」才准
    base = tz.now().astimezone(zone)
    nxt = trigger.get_next_fire_time(None, base)
    return int(nxt.timestamp() * 1000) if nxt else _NEVER_FIRE


class AgentTurnRunner:
    """持有一组 agent_turn job，到点逐个执行。"""

    def __init__(
        self,
        engine,
        sink,
        *,
        scheduler=None,
        allowed_groups: set[str] | frozenset[str] | None = None,
        jobs_file=None,
    ):
        self.engine = engine
        self.sink = sink
        self.scheduler = scheduler
        # 状态回写的落点。显式传入（而不是每次 update_state 走 env）有两个原因：
        # 测试必须能写到自己的 tmp 文件（否则会污染仓库里那份真实 state.json），
        # 且 tick 读的是同一个文件——两边不一致会让 pending 标记写到别处。
        self.jobs_file = jobs_file
        # 群目标白名单（由适配层从 acl.ALLOWED_GROUPS 注入）。缺省空集 = 群目标
        # 一律不投递：漏注入的接线错误必须是「不发」而不是「全发」（fail-closed）。
        self.allowed_groups = {str(g) for g in (allowed_groups or ())}
        # 坏文件/坏条目的告警去重：tick 是 60s 一轮，不去重会把同一条错误刷
        # 1440 次/天，把真正的告警埋掉（与 personas._warn_once 同思路）。
        self._last_error: str | None = None
        # ACL 告警单独去重：复用 _last_error 会被「配置错误 → 恢复」流程清掉，
        # 而且两者的恢复条件不同（配置错误恢复后要重新报，白名单是启动期常量）。
        self._acl_warned: set[tuple[str, str]] = set()
        # 永触发表达式告警按 job 去重：tick 是 60s 一轮，不去重会把同一条错误
        # 刷 1440 次/天，把真正的告警埋掉。
        self._dead_warned: set[str] = set()

    def _warn_once(self, msg: str) -> None:
        if msg == self._last_error:
            return
        self._last_error = msg
        logger.warning("%s", msg)

    def _warn_dead_once(self, job: CronJob) -> None:
        """永触发表达式按 job 去重告警（与 _warn_acl_once 同思路）。"""
        if job.id in self._dead_warned:
            return
        self._dead_warned.add(job.id)
        logger.warning(
            "cron job %s (%s) 的表达式 %r 永触发（不存在满足条件的日期），"
            "已跳过；请改 schedule.expr 或把 enabled 置为 false",
            job.id,
            job.name,
            job.cron,
        )

    def _target_allowed(self, kind: str, ident: int) -> bool:
        """群目标必须在白名单里；私聊目标不受群 ACL 约束（见模块 docstring）。

        ``parse_target`` 把标识统一解析成 int，而白名单是字符串集合（env 来源），
        所以比较时统一 ``str()``。
        """
        if kind == "private":
            return True
        return str(ident) in self.allowed_groups

    def _warn_acl_once(self, job: CronJob, target: str) -> None:
        key = (job.id, target)
        if key in self._acl_warned:
            return
        self._acl_warned.add(key)
        logger.warning(
            "cron job %s (%s) 的目标 %s 不在 ALLOWED_GROUPS 白名单，"
            "本轮不执行也不投递（ACL 按 job 去重告警）",
            job.id,
            job.name,
            target,
        )

    async def run_job(self, job: CronJob) -> str:
        """执行一条 job，返回三态：``ok`` / ``failed`` / ``uncertain``。"""
        # 永触发表达式（`0 0 30 2 *`）：from_crontab 能解析，get_next_fire_time
        # 却永远 None，_next_run_ms 因此返 _NEVER_FIRE。装载期已在
        # jobs._validate_job 拒掉这类 job；这里是第二道闸——run_job 是执行一条
        # job 的唯一入口，挡住绕过装载期的调用方。不跑引擎也不推进 next_run：
        # 一条永远不会有下次执行的 job，写任何 next_run_at_ms 都是假的。
        if _next_run_ms(job.cron, job.tz) == _NEVER_FIRE:
            self._warn_dead_once(job)
            return "failed"
        target = parse_target(job.to)
        if target is None:
            # 构造期已校验，正常到不了；防御性兜底避免把 None 解包炸掉整个 tick
            logger.warning("cron job %s (%s) 目标非法：%r", job.id, job.name, job.to)
            return "failed"
        kind, ident = target
        # ACL 先于引擎：不放行时连 agent 回合都不跑（省 LLM/token，也不让未授权群
        # 的模型输出出现在日志里）。仍推进下次执行时刻，否则 tick 会每 60s 重试一次。
        if not self._target_allowed(kind, ident):
            self._warn_acl_once(job, job.to)
            update_state(
                job.id,
                status="failed",
                next_run_ms=_next_run_ms(job.cron, job.tz),
                path=self.jobs_file,
            )
            return "failed"
        # D4 M2：会话隔离。user_id 用 ``cron:<job_id>``、group_id 为空，走的是
        # 私聊命名空间（内存键 ``p:cron:<job_id>``、PG 里 group_id IS NULL），
        # 因此任务输出既不进任何真实用户的私聊历史，也不进目标群的历史。不要
        # 直接拿 target 当 user_id：旧实现把群号当 user/group 双写，等于让 cron
        # 借用那个群的历史与事实（``g:<gid>:<gid>`` 这种自我对话键）。
        # owner=True：jobs.json 是 owner 手写的主机配置，属可信指令，与私聊
        # owner 同权（否则需要 run_command 的定时任务会全部取不到工具）。
        # isolated=True：一次性会话，不抽长期事实、不推进人格成长。
        # route 显式给：预算报表按 cron:<job_id> 分开记账。
        context = {
            "user_id": f"cron:{job.id}",
            "group_id": None,
            "owner": True,
            "isolated": True,
            "route": f"cron:{job.id}",
        }
        status = "failed"
        try:
            text = await self.engine.run(context, job.message)
        except Exception:
            logger.exception("cron job %s (%s) agent_turn 执行失败", job.id, job.name)
            text = ""
        next_ms = _next_run_ms(job.cron, job.tz)
        if not text or not str(text).strip():
            logger.warning("cron job %s (%s) 产出为空，不投递", job.id, job.name)
        else:
            # L3：投递**之前**先把「本轮已开始 + 下次执行已推进 + 状态 pending」
            # 落盘。崩在 send_once 中间时，重启后这条 job 的 nextRunAtMs 已经过期
            # 但状态是 pending——tick 的到点判断看的是推进后的时刻，不会把它当成
            # 「没跑过」再投一遍（出站铁律：结果不确定绝不重发）。pending 只覆盖
            # 崩溃窗口，正常路径紧接着就会被 ok/failed/uncertain 覆盖。
            update_state(
                job.id,
                status="pending",
                next_run_ms=next_ms,
                path=self.jobs_file,
            )
            outcome = await self.sink.send_once(job.to, str(text))
            if outcome == "sent":
                status = "ok"
            elif outcome == "uncertain":
                # 已发出、响应丢失：不当失败（不触发重试计数），但也不算成功
                status = "uncertain"
            else:
                logger.warning("cron job %s (%s) 投递失败", job.id, job.name)
        update_state(job.id, status=status, next_run_ms=next_ms, path=self.jobs_file)
        return status

    async def tick(self) -> None:
        """扫描 jobs.json 并执行所有 enabled 的 agent_turn job。

        由 apscheduler 的 interval 触发器驱动（默认 60s）。真正的「到点」判断在
        这里做而不是依赖 apscheduler 的 cron 触发器——因为 cron 表达式带 **tz**，
        而 AgentScheduler 只有一个全局时区；让 apscheduler 按 UTC/本地触发会让
        带 tz 的 job 在错误时刻跑。interval + 自己算下次时刻更直白，也顺带
        支持「手改 jobs.json 后无需重启即生效」（下次 tick 重读文件）。
        """
        from agentcore.scheduler import jobs as jobs_mod

        try:
            # 与 update_state 同落点：显式 jobs_file 时读同一份（否则测试/embedding
            # 场景会读到默认路径，tick 与状态回写不一致——「手改即生效」也就无从谈起）
            jobs, errors = jobs_mod.load(self.jobs_file)
        except jobs_mod.JobsError as e:
            self._warn_once(f"cron jobs.json 读取失败，本轮跳过：{e}")
            return
        if errors:
            # 坏条目逐条报告（一个错 job 不该把其余的也废掉），按内容去重
            self._warn_once("cron job 配置错误，已跳过：" + "；".join(errors))
        else:
            self._last_error = None  # 恢复后重新报下一次故障
        # 到点判断用统一时钟（tz.now），与 next_run_at_ms 的写入同源：
        # 一边用进程时区、一边用裸 datetime.now() 会让「下次执行」永远算不准。
        now_ms = int(tz.now().timestamp() * 1000)
        for job in jobs:
            if not job.enabled:
                continue

            # 到点判断：nextRunAtMs 缺省/已过期（<=now）即执行。首次运行
            # （next_run_at_ms == 0）立即跑一次——新加的 job 不该等到下个周期。
            if job.next_run_at_ms and job.next_run_at_ms > now_ms:
                continue
            await self.run_job(job)

    def register(self, seconds: int = 60) -> bool:
        """把 tick 注册进 scheduler（interval）。"""
        if self.scheduler is None:
            return False
        return self.scheduler.add_interval(
            "cron_jobs", seconds, self.tick, name="jobs.json 定时任务"
        )
