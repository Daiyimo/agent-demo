"""OpenClaw 兼容的 cron 任务：``data/cron/jobs.json``（2026-10-28 需求②）。

**为什么用 jobs.json 取代 env 里的 ``*_CRON``**：用户明确要求「以后都采用这个格式」。
OpenClaw / picoclaw 的 cron 就是 ``<workspace>/cron/jobs.json``，两边文件可直接互拷；
env 只能表达「一个表达式」，装不下 id / 开关 / 时区 / 投递目标 / 运行状态。

**与 env 驱动的系统任务的分工**（决策④，已确认）：jobs.json 只接管
``payload.kind == "agent_turn"`` 这一类——「到点让 agent 跑一轮并把结果投递到指定
会话」。``kb_digest`` / ``db_backup`` / 群统计 / 提醒轮询仍是**系统运维任务**，
继续走 env（``AGENT_KB_DIGEST_CRON`` 等），不迁进来：用 agent_turn 间接表达它们
只会更脆（多一层 LLM 依赖，失败时连备份都不会做）。

**文件形态**（未出现的字段忽略不报错，向前兼容 OpenClaw 的增量字段）::

    {
      "version": 1,
      "jobs": [{
        "id": "c2bfdcf1fba388b7",          # 缺省时由 name 派生
        "name": "每3小时用电用水报告",
        "enabled": true,
        "schedule": {"kind": "cron", "expr": "0 */3 * * *", "tz": "Asia/Shanghai"},
        "payload": {
          "kind": "agent_turn",
          "message": "执行 ... 把 stdout 原样发到群聊",
          "channel": "onebot",
          "to": "group:2000000005"          # 复用 push.parse_target 的 group:/private:
        },
        "createdAtMs": 0,
        "deleteAfterRun": false
      }]
    }

    data/cron/state.json              # 运行状态（执行体回写，别手改）
    {"version": 1, "jobs": {"<id>": {"nextRunAtMs": 0, "lastRunAtMs": 0,
                                     "lastStatus": ""}}}

**落盘纪律**：``save`` 只补丁 ``jobs`` 一个键（与 llm providers 同一套口径），
不碰 agent.json 之外的任何东西；原子写 + 0600 + 写后重读校验。
``state`` 由执行体回写（``lastRunAtMs`` / ``lastStatus`` / ``nextRunAtMs``），
但**不再写回 jobs.json**（2026-10-29）：每次跑完都重写配置文件会把「配置」与
「运行状态」搅在一起——备份 churn、与手改并发丢更新、OpenClaw 互拷时把本机
运行时间带过去。状态落在同目录 ``state.json``（0600、原子写）。
读的时候 sidecar 优先，**旧文件里内嵌的 ``state`` 仍作为回落**：升级后不必迁移，
首次回写就把它转存到 sidecar；``save`` 也顺手把内存里的状态刷进 sidecar。
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agentcore import tz as agent_tz
from agentcore.scheduler.push import parse_target

logger = logging.getLogger(__name__)

CRON_DIR_ENV = "AGENT_CRON_DIR"
JOBS_FILENAME = "jobs.json"
_JOBS_KEY = "jobs"
_DEFAULT_DIR = "data/cron"
STATE_FILENAME = "state.json"
_BACKUP_KEEP = 10

# payload.kind：本项目只实现 agent_turn；其余记 WARNING 跳过（不静默丢弃）。
_SUPPORTED_KINDS = {"agent_turn"}
# channel：本项目只有 onebot 一个渠道（OneBot v11 适配器）。
_SUPPORTED_CHANNELS = {"onebot"}

# id 允许 unicode 单词字符：中文任务名也能派生出可读 id（\w 在 py3 的 str
# 模式下默认含 CJK）。id 只作为 JSON 里的字符串值，不进路径、不进 apscheduler，
# 放宽不会扩大攻击面。
_ID_RE = re.compile(r"^[\w-]{1,64}$")
_MSG_MAX = 20000


class JobsError(ValueError):
    """jobs.json 不合法；message 面向管理员（HTTP 422 / 启动日志）。"""


@dataclass
class CronJob:
    id: str
    name: str
    enabled: bool
    cron: str
    tz: str | None
    message: str
    channel: str
    to: str
    delete_after_run: bool = False
    # 运行状态（由执行体回写）
    next_run_at_ms: int = 0
    last_run_at_ms: int = 0
    last_status: str = ""
    created_at_ms: int = 0
    updated_at_ms: int = 0
    raw: dict = field(default_factory=dict)

    def public(self) -> dict:
        """对外形态：不含 message 全文（可能很长），只给长度与前 80 字。"""
        return {
            "id": self.id,
            "name": self.name,
            "enabled": self.enabled,
            "cron": self.cron,
            "tz": self.tz,
            "channel": self.channel,
            "to": self.to,
            "delete_after_run": self.delete_after_run,
            "message_len": len(self.message),
            "message_head": self.message[:80],
            "last_run_at_ms": self.last_run_at_ms,
            "last_status": self.last_status,
            "next_run_at_ms": self.next_run_at_ms,
        }


# ---------------------------------------------------------------- 路径


def cron_dir() -> Path:
    """jobs.json 所在目录：env 显式值优先，空串/纯空白回落默认。"""
    raw = (os.getenv(CRON_DIR_ENV) or "").strip()
    return Path(raw or _DEFAULT_DIR)


def jobs_path() -> Path:
    return cron_dir() / JOBS_FILENAME


def state_path(path: Path | None = None) -> Path:
    """运行状态 sidecar：与 jobs.json 同目录（``AGENT_CRON_DIR`` 一起生效）。"""
    return (path or jobs_path()).with_name(STATE_FILENAME)


def _read_state_sidecar(p: Path) -> dict[str, dict]:
    """读状态 sidecar；缺失 = 全新部署（正常态），损坏告警后当空。"""
    sp = state_path(p)
    try:
        raw = json.loads(sp.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, json.JSONDecodeError) as e:
        logger.warning(
            "cron state sidecar 读不到，按内置 state 回落：%s", type(e).__name__
        )
        return {}
    jobs = raw.get("jobs") if isinstance(raw, dict) else None
    if not isinstance(jobs, dict):
        return {}
    return {str(k): v for k, v in jobs.items() if isinstance(v, dict)}


def _write_state_sidecar(
    p: Path, states: dict[str, dict], *, allow_empty: bool = False
) -> None:
    """原子写 0600。空状态默认不落文件（全新部署不留空壳）。"""
    clean = {
        str(k): {
            "nextRunAtMs": _as_ms(v.get("nextRunAtMs")),
            "lastRunAtMs": _as_ms(v.get("lastRunAtMs")),
            "lastStatus": str(v.get("lastStatus") or ""),
        }
        for k, v in states.items()
        if isinstance(v, dict)
    }
    clean = {
        k: v
        for k, v in clean.items()
        if v["nextRunAtMs"] or v["lastRunAtMs"] or v["lastStatus"]
    }
    if not clean and not allow_empty:
        return
    sp = state_path(p)
    sp.parent.mkdir(parents=True, exist_ok=True)
    nl = chr(10)
    text = json.dumps({"version": 1, "jobs": clean}, ensure_ascii=False, indent=2) + nl
    _atomic_write(sp, text)


# ---------------------------------------------------------------- 解析


def _now_ms() -> int:
    return int(time.time() * 1000)


def _slug(text: str) -> str:
    """从 name 派生 id：保留 unicode 单词字符（中文名得到中文 id），其余折叠成连字符。

    纯 ASCII 旧实现会把「每3小时用电用水报告」削成 ``"3"``——合法但不可读，且多个
    中文任务会撞成同一个 id。空结果回落 ``"job"``。
    """
    s = re.sub(r"[^\w]+", "-", (text or "").strip(), flags=re.UNICODE).strip("-")
    return s[:48] or "job"


def _validate_job(raw: Any, index: int) -> tuple[CronJob | None, str | None]:
    """把一段原始配置解析成 CronJob；返回 (job, 错误原因)，二者恰有一个非 None。"""
    if not isinstance(raw, dict):
        return None, f"jobs[{index}] 不是对象"
    name = str(raw.get("name") or "").strip() or f"job-{index + 1}"
    jid = str(raw.get("id") or "").strip() or _slug(name)
    if not _ID_RE.match(jid):
        return None, f"id 非法（64 位以内 A-Za-z0-9_-）：{jid!r}"
    enabled_raw = raw.get("enabled", True)
    enabled = (
        str(enabled_raw).strip().lower() not in {"0", "false", "no", "off", ""}
        if isinstance(enabled_raw, str)
        else bool(enabled_raw)
    )

    sched = raw.get("schedule")
    if not isinstance(sched, dict):
        return None, f"{name}: schedule 必须是对象"
    kind = str(sched.get("kind") or "cron").strip().lower()
    if kind != "cron":
        return None, f"{name}: schedule.kind 只支持 cron，实为 {kind!r}"
    cron = str(sched.get("expr") or "").strip()
    if not cron:
        return None, f"{name}: schedule.expr 不能为空"
    # 表达式合法性与执行侧同一判据（apscheduler 的 from_crontab）
    from apscheduler.triggers.cron import CronTrigger

    try:
        trigger = CronTrigger.from_crontab(cron)
    except Exception:
        return None, f"{name}: cron 无法解析：{cron!r}"
    tz_raw = str(sched.get("tz") or "").strip()
    tz = tz_raw or None
    # 「能解析」不等于「会有下次执行」：`0 0 30 2 *`（2 月 30 日）from_crontab
    # 成功，get_next_fire_time 却永远返回 None。这类 job 一旦放行，执行体算不出
    # nextRunAtMs（返 0），而 tick 的到点判断 `if next_run_at_ms and ...` 把 0 当
    # 「首次运行」——于是每 60s 跑一次完整 LLM 回合 + 投递，无限烧 token，且 job
    # 永远不会被标记 failed（评审遗留项）。装载期就拒掉，错误走现成的 per-job
    # errors 通道，由 AgentTurnRunner.tick 逐条告警。
    if trigger.get_next_fire_time(None, agent_tz.now()) is None:
        return None, f"{name}: cron 表达式永触发（不存在满足条件的日期）：{cron!r}"

    payload = raw.get("payload")
    if not isinstance(payload, dict):
        return None, f"{name}: payload 必须是对象"
    p_kind = str(payload.get("kind") or "").strip().lower()
    if p_kind not in _SUPPORTED_KINDS:
        return None, f"{name}: payload.kind 只支持 agent_turn，实为 {p_kind!r}"
    message = str(payload.get("message") or "")
    if not message.strip():
        return None, f"{name}: payload.message 不能为空"
    if len(message) > _MSG_MAX:
        return None, f"{name}: payload.message 过长（>{_MSG_MAX} 字）"
    channel = str(payload.get("channel") or "onebot").strip().lower()
    if channel not in _SUPPORTED_CHANNELS:
        return None, f"{name}: payload.channel 只支持 onebot，实为 {channel!r}"
    to = str(payload.get("to") or "").strip()
    if parse_target(to) is None:
        return None, (
            f"{name}: payload.to 非法（应为 group:<群号> / private:<QQ号>）：{to!r}"
        )

    # 显式注解 + 先取后判：内联三元会让 pyright 把 state 推成含 None 的联合
    raw_state = raw.get("state")
    state: dict = raw_state if isinstance(raw_state, dict) else {}
    job = CronJob(
        id=jid,
        name=name,
        enabled=enabled,
        cron=cron,
        tz=tz,
        message=message,
        channel=channel,
        to=to,
        delete_after_run=bool(raw.get("deleteAfterRun", False)),
        next_run_at_ms=_as_ms(state.get("nextRunAtMs")),
        last_run_at_ms=_as_ms(state.get("lastRunAtMs")),
        last_status=str(state.get("lastStatus") or ""),
        created_at_ms=_as_ms(raw.get("createdAtMs")),
        updated_at_ms=_as_ms(raw.get("updatedAtMs")),
        raw=raw,
    )
    return job, None


def _as_ms(value: Any) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def parse_jobs(data: Any) -> tuple[list[CronJob], list[str]]:
    """解析整个 jobs.json 的字典；返回 (jobs, 逐条错误原因)。

    坏条目**跳过并报告**，不让一个错 job 把其余 job 一起废掉（与 push 同口径）。
    """
    if not isinstance(data, dict):
        raise JobsError("jobs.json 顶层必须是对象")
    raw_jobs = data.get(_JOBS_KEY)
    if raw_jobs is None:
        return [], []
    if not isinstance(raw_jobs, list):
        raise JobsError("jobs 必须是数组")
    jobs: list[CronJob] = []
    errors: list[str] = []
    seen: set[str] = set()
    for i, raw in enumerate(raw_jobs):
        job, err = _validate_job(raw, i)
        # 判 None 而非只判 err：_validate_job 的契约是「二者恰有一个非 None」，
        # 只判 err 时 pyright 无法把 job 收窄成非空，后面 job.id 会报 optional。
        if job is None or err:
            errors.append(err or f"jobs[{i}] 解析失败")
            continue
        if job.id in seen:
            errors.append(f"id 重复：{job.id}")
            continue
        seen.add(job.id)
        jobs.append(job)
    return jobs, errors


def load(path: Path | None = None) -> tuple[list[CronJob], list[str]]:
    """读 jobs.json；文件缺失返回 ([], [])（全新部署还没建文件是正常态）。"""
    p = path or jobs_path()
    try:
        text = p.read_text(encoding="utf-8")
    except FileNotFoundError:
        return [], []
    except OSError as e:
        raise JobsError(f"读不到 {p}: {type(e).__name__}") from e
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise JobsError(f"{p} 不是合法 JSON: {e}") from e
    jobs, errors = parse_jobs(data)
    # sidecar 优先；旧文件内嵌的 state 只在该 id 还没进 sidecar 时生效（升级兼容）
    states = _read_state_sidecar(p)
    for job in jobs:
        st = states.get(job.id)
        if st is None:
            continue
        job.next_run_at_ms = _as_ms(st.get("nextRunAtMs"))
        job.last_run_at_ms = _as_ms(st.get("lastRunAtMs"))
        job.last_status = str(st.get("lastStatus") or "")
    return jobs, errors


# ---------------------------------------------------------------- 落盘


def _atomic_write(path: Path, text: str) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    try:
        fd = os.open(tmp, flags, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise


def _state_of(job: CronJob) -> dict:
    return {
        "nextRunAtMs": job.next_run_at_ms,
        "lastRunAtMs": job.last_run_at_ms,
        "lastStatus": job.last_status,
    }


def _dump_job(job: CronJob) -> dict:
    """导出回 OpenClaw 形态（与入参字段名一致，便于两边互拷）。"""
    return {
        "id": job.id,
        "name": job.name,
        "enabled": job.enabled,
        "schedule": {
            "kind": "cron",
            "expr": job.cron,
            **({"tz": job.tz} if job.tz else {}),
        },
        "payload": {
            "kind": "agent_turn",
            "message": job.message,
            "channel": job.channel,
            "to": job.to,
        },
        "createdAtMs": job.created_at_ms,
        "deleteAfterRun": job.delete_after_run,
    }


def save(jobs: list[CronJob], path: Path | None = None) -> None:
    """把 jobs 列表写回 jobs.json（原子 + 0600 + 写后重读校验）。

    刻意**不做增量补丁**：jobs 的权威形态就是整个数组。文件小（几条到几十条），
    全量写的代价可忽略，而增量补丁要处理「数组中间插入/删除」的下标漂移，
    复杂度不值。**运行状态不在这里**（见 ``state.json``），但内存里已有的状态会
    顺手刷进 sidecar，保证两侧不漂。
    """
    p = path or jobs_path()
    if p.is_symlink():
        raise JobsError("jobs_file_is_symlink")
    p.parent.mkdir(parents=True, exist_ok=True)
    now = _now_ms()
    # 读现文件 → 只替换 jobs 键，**其余顶层键原样保留**（与 llm providers 补丁
    # agent.json 同一口径）：OpenClaw 后续版本会往 jobs.json 加字段，用户的 `_说明`
    # 备注也不能因为一次状态回写被静默抹掉。
    try:
        current = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(current, dict):
            raise JobsError("jobs_json_not_object")
    except FileNotFoundError:
        current = {}
    except json.JSONDecodeError as e:
        raise JobsError(f"jobs_json_invalid: {type(e).__name__}") from e
    payload = dict(current)
    payload["version"] = current.get("version", 1)
    payload[_JOBS_KEY] = [_dump_job(j) for j in jobs]
    for dumped, job in zip(payload[_JOBS_KEY], jobs, strict=True):
        if not job.created_at_ms:
            job.created_at_ms = now
            dumped["createdAtMs"] = now
        job.updated_at_ms = now
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"

    backup = None
    if p.exists():
        bdir = p.parent / "backups"
        bdir.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d-%H%M%S") + f"-{time.time_ns() % 10**6:06d}"
        backup = bdir / f"{p.name}.{stamp}.bak"
        import shutil

        shutil.copy2(p, backup)
        os.chmod(backup, 0o600)
        for old in sorted(bdir.glob(f"{p.name}.*.bak"))[:-_BACKUP_KEEP]:
            old.unlink(missing_ok=True)

    _atomic_write(p, text)

    # 写后重读校验：落盘内容必须能被原样读回（防半截文件/序列化丢字段）
    try:
        check, _ = load(p)
    except Exception:
        if backup is not None:
            import shutil

            shutil.copy2(backup, p)
        else:
            p.unlink(missing_ok=True)
        raise JobsError("jobs_verify_failed_rolled_back") from None
    _write_state_sidecar(p, {j.id: _state_of(j) for j in jobs})
    if [j.id for j in check] != [j.id for j in jobs]:
        if backup is not None:
            import shutil

            shutil.copy2(backup, p)
        raise JobsError("jobs_verify_failed_rolled_back")
    logger.info("cron jobs saved: %d jobs", len(jobs))


def update_state(
    job_id: str, *, status: str, next_run_ms: int = 0, path: Path | None = None
) -> None:
    """执行体回写某条 job 的运行状态（只写 ``state.json``，不碰 jobs.json）。

    ``path`` 与 :func:`load`/:func:`save` 同参数名，测试必须显式传入——否则会写
    到仓库里那份真实 jobs.json（2026-10-28 实测踩过：忘传 path 的测试把夹具值
    写进了 ``data/workspace/cron/jobs.json``）。

    ``deleteAfterRun && ok`` 是唯一需要改 jobs.json 的路径（删任务）。
    失败只告警不抛：回写状态失败不该让「任务已经跑完」这件事本身失败。
    """
    try:
        jobs, _ = load(path)
        hit = next((j for j in jobs if j.id == job_id), None)
        if hit is None:
            return
        hit.last_run_at_ms = _now_ms()
        hit.last_status = status
        hit.next_run_at_ms = next_run_ms
        p = path or jobs_path()
        if hit.delete_after_run and status == "ok":
            jobs = [j for j in jobs if j.id != job_id]
            save(jobs, path)
            states = _read_state_sidecar(p)
            states.pop(job_id, None)
            _write_state_sidecar(p, states, allow_empty=True)
            return
        states = _read_state_sidecar(p)
        states[job_id] = _state_of(hit)
        _write_state_sidecar(p, states)
    except Exception:
        logger.warning("cron job %s 状态回写失败", job_id, exc_info=True)
