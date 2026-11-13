"""jobs.json 定时任务：解析 / 校验 / 落盘 / 状态回写 / agent_turn 执行。

2026-10-28 需求②：OpenClaw 兼容的 ``data/cron/jobs.json``（2026-10-29 从 data/workspace/
移出沙箱写面，运行态另存同目录 state.json），只接管
``payload.kind == "agent_turn"``（到点让 agent 跑一轮并投递到指定会话）；
kb_digest / db_backup / 群统计 / 提醒轮询仍是系统任务，继续走 env。

变异锚点（改坏实现必须红）：
1. 去掉 schedule.kind 校验 → 非 cron 被接受，用例红
2. 去掉 payload.to 校验 → 非法目标被接受，用例红
3. 去掉 save 的未知键保留 → 用户备注被抹掉，用例红
4. 去掉 enabled 过滤 → 停用的 job 照样跑，用例红
5. 去掉 _warn_once 去重 → 告警刷屏，用例红
6. 去掉写后重读校验 → 半截文件不回落，用例红
7. 去掉群目标白名单判定 → 白名单外的群照样跑引擎并投递，`TestTargetACL` 红
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

import pytest

from agentcore import boolenv
from agentcore.scheduler import jobs as J
from agentcore.scheduler.agent_turn import _NEVER_FIRE, AgentTurnRunner, _next_run_ms


@pytest.fixture(autouse=True)
def _clean_cron_env(monkeypatch):
    for key in ("AGENT_CRON_DIR", "AGENT_CONFIG_JSON"):
        monkeypatch.delenv(key, raising=False)
    yield
    for key in ("AGENT_CRON_DIR", "AGENT_CONFIG_JSON"):
        os.environ.pop(key, None)


def _job_dict(**over):
    base = {
        "id": "j1",
        "name": "测试任务",
        "enabled": True,
        "schedule": {"kind": "cron", "expr": "0 */3 * * *", "tz": "Asia/Shanghai"},
        "payload": {
            "kind": "agent_turn",
            "message": "执行脚本并发到群里",
            "channel": "onebot",
            "to": "group:123",
        },
    }
    base.update(over)
    return base


class TestPaths:
    def test_default_dir(self):
        assert J.cron_dir() == Path("data/cron")
        assert J.jobs_path() == Path("data/cron/jobs.json")

    def test_env_override(self, monkeypatch):
        monkeypatch.setenv("AGENT_CRON_DIR", "/tmp/mycron")
        assert J.cron_dir() == Path("/tmp/mycron")

    def test_blank_env_falls_back(self, monkeypatch):
        """M18 同型：env 空串/纯空白必须回落默认，不能变成 Path('') = '.'。"""
        for raw in ("", "   "):
            monkeypatch.setenv("AGENT_CRON_DIR", raw)
            assert J.cron_dir() == Path("data/cron")


class TestParseJobs:
    def test_valid_job(self):
        jobs, errors = J.parse_jobs({"version": 1, "jobs": [_job_dict()]})
        assert errors == []
        assert len(jobs) == 1
        j = jobs[0]
        assert j.id == "j1" and j.name == "测试任务"
        assert j.cron == "0 */3 * * *" and j.tz == "Asia/Shanghai"
        assert j.channel == "onebot" and j.to == "group:123"
        assert j.enabled is True and j.delete_after_run is False

    def test_enabled_dirty_value_warns_and_falls_back_to_default(self, caplog):
        """G（REVIEW 2026-11-02）：jobs.json 是手写主机配置，脏值不得静默按「开」。

        旧手解把 ``"enabled": "disabled"`` 判成 True 且无痕。
        """
        boolenv._warned.clear()
        with caplog.at_level(logging.WARNING, logger="agentcore.boolenv"):
            jobs, errors = J.parse_jobs({"jobs": [_job_dict(enabled="disabled")]})
        assert errors == [] and jobs[0].enabled is True
        assert "不是布尔值" in caplog.text and "disabled" in caplog.text

    def test_no_jobs_key_is_empty_not_error(self):
        jobs, errors = J.parse_jobs({"version": 1})
        assert jobs == [] and errors == []

    def test_id_derived_from_name(self):
        """中文任务名也要得到可读 id（旧 ASCII slug 会把它削成 "3"）。"""
        jobs, _ = J.parse_jobs({"jobs": [_job_dict(id="", name="每3小时用电用水报告")]})
        assert jobs[0].id == "每3小时用电用水报告"

    def test_id_derived_ascii_still_slugged(self):
        jobs, _ = J.parse_jobs({"jobs": [_job_dict(id="", name="My Daily Report!")]})
        assert jobs[0].id == "My-Daily-Report"

    def test_id_derived_fallback_when_no_word_chars(self):
        jobs, _ = J.parse_jobs({"jobs": [_job_dict(id="", name="！！！")]})
        assert jobs[0].id == "job"

    def test_rejects_non_cron_kind(self):
        jobs, errors = J.parse_jobs(
            {"jobs": [_job_dict(schedule={"kind": "interval", "expr": "60"})]}
        )
        assert jobs == [] and "kind" in errors[0]

    def test_rejects_bad_cron_expr(self):
        jobs, errors = J.parse_jobs(
            {"jobs": [_job_dict(schedule={"kind": "cron", "expr": "not a cron"})]}
        )
        assert jobs == [] and "cron" in errors[0]

    def test_rejects_never_fire_cron_expr(self):
        """能解析但永触发（2 月 30 日）必须拒：`_next_run_ms` 对这类表达式返 0，
        而 tick 的「首次运行」语义把 0 当没跑过 → 每 60s 跑一次完整 LLM 回合。"""
        jobs, errors = J.parse_jobs(
            {"jobs": [_job_dict(schedule={"kind": "cron", "expr": "0 0 30 2 *"})]}
        )
        assert jobs == [] and "永触发" in errors[0]

    def test_accepts_leap_day_cron_expr(self):
        """闰日（2 月 29）每 4 年真会触发，不是永触发，不能误拒。"""
        jobs, errors = J.parse_jobs(
            {"jobs": [_job_dict(schedule={"kind": "cron", "expr": "0 0 29 2 *"})]}
        )
        assert len(jobs) == 1 and errors == []

    def test_rejects_empty_cron(self):
        jobs, errors = J.parse_jobs(
            {"jobs": [_job_dict(schedule={"kind": "cron", "expr": "  "})]}
        )
        assert jobs == [] and errors

    def test_rejects_non_agent_turn_payload(self):
        jobs, errors = J.parse_jobs(
            {
                "jobs": [
                    _job_dict(
                        payload={"kind": "shell", "message": "x", "to": "group:1"}
                    )
                ]
            }
        )
        assert jobs == [] and "payload.kind" in errors[0]

    def test_rejects_bad_target(self):
        for bad in ("123", "chan:123", "group:１２３", "group:", ""):
            jobs, errors = J.parse_jobs(
                {
                    "jobs": [
                        _job_dict(
                            payload={"kind": "agent_turn", "message": "x", "to": bad}
                        )
                    ]
                }
            )
            assert jobs == [], bad
            assert errors, bad

    def test_accepts_private_target(self):
        jobs, errors = J.parse_jobs(
            {
                "jobs": [
                    _job_dict(
                        payload={
                            "kind": "agent_turn",
                            "message": "x",
                            "to": "private:456",
                        }
                    )
                ]
            }
        )
        assert errors == [] and jobs[0].to == "private:456"

    def test_rejects_empty_message(self):
        jobs, errors = J.parse_jobs(
            {
                "jobs": [
                    _job_dict(
                        payload={"kind": "agent_turn", "message": "  ", "to": "group:1"}
                    )
                ]
            }
        )
        assert jobs == [] and errors

    def test_rejects_oversized_message(self):
        jobs, errors = J.parse_jobs(
            {
                "jobs": [
                    _job_dict(
                        payload={
                            "kind": "agent_turn",
                            "message": "x" * 20001,
                            "to": "group:1",
                        }
                    )
                ]
            }
        )
        assert jobs == [] and errors

    def test_rejects_bad_channel(self):
        jobs, errors = J.parse_jobs(
            {
                "jobs": [
                    _job_dict(
                        payload={
                            "kind": "agent_turn",
                            "message": "x",
                            "channel": "feishu",
                            "to": "group:1",
                        }
                    )
                ]
            }
        )
        assert jobs == [] and "channel" in errors[0]

    def test_rejects_duplicate_id(self):
        jobs, errors = J.parse_jobs({"jobs": [_job_dict(), _job_dict()]})
        assert len(jobs) == 1 and "重复" in errors[0]

    def test_bad_entry_does_not_kill_good_ones(self):
        """一个坏 job 不该把其余的也废掉（与 push 同口径）。"""
        jobs, errors = J.parse_jobs(
            {
                "jobs": [
                    _job_dict(id="good"),
                    _job_dict(id="bad", schedule={"kind": "nope"}),
                ]
            }
        )
        assert [j.id for j in jobs] == ["good"]
        assert len(errors) == 1

    def test_top_level_not_object_raises(self):
        with pytest.raises(J.JobsError):
            J.parse_jobs([1, 2])

    def test_jobs_not_list_raises(self):
        with pytest.raises(J.JobsError, match="jobs"):
            J.parse_jobs({"jobs": "nope"})

    def test_enabled_string_forms(self):
        for raw, want in (("false", False), ("0", False), ("true", True), ("1", True)):
            jobs, _ = J.parse_jobs({"jobs": [_job_dict(enabled=raw)]})
            assert jobs[0].enabled is want, raw

    def test_default_enabled_true(self):
        d = _job_dict()
        del d["enabled"]
        jobs, _ = J.parse_jobs({"jobs": [d]})
        assert jobs[0].enabled is True

    def test_unknown_fields_ignored(self):
        """OpenClaw 增量字段（sessionTarget/announce 等）忽略不报错。"""
        d = _job_dict()
        d["sessionTarget"] = "isolated"
        d["announce"] = True
        jobs, errors = J.parse_jobs({"jobs": [d]})
        assert errors == [] and len(jobs) == 1


class TestLoad:
    def test_missing_file_is_empty(self, tmp_path):
        jobs, errors = J.load(tmp_path / "nope.json")
        assert jobs == [] and errors == []

    def test_bad_json_raises(self, tmp_path):
        p = tmp_path / "jobs.json"
        p.write_text("{not json", encoding="utf-8")
        with pytest.raises(J.JobsError, match="JSON"):
            J.load(p)

    def test_real_file_roundtrip(self, tmp_path):
        p = tmp_path / "jobs.json"
        J.save([_cron_job()], p)
        jobs, errors = J.load(p)
        assert errors == []
        assert [j.id for j in jobs] == ["j1"]


def _cron_job(**over):
    base = dict(
        id="j1",
        name="测试任务",
        enabled=True,
        cron="0 */3 * * *",
        tz="Asia/Shanghai",
        message="执行脚本并发到群里",
        channel="onebot",
        to="group:123",
    )
    base.update(over)
    return J.CronJob(**base)


class TestSave:
    def test_roundtrip(self, tmp_path):
        p = tmp_path / "jobs.json"
        J.save([_cron_job()], p)
        jobs, _ = J.load(p)
        j = jobs[0]
        assert j.id == "j1" and j.cron == "0 */3 * * *"
        assert j.tz == "Asia/Shanghai" and j.to == "group:123"
        assert j.message == "执行脚本并发到群里"

    def test_preserves_unknown_top_level_keys(self, tmp_path):
        """只补丁 jobs 键：用户备注与 OpenClaw 增量字段不能被抹掉。"""
        p = tmp_path / "jobs.json"
        p.write_text(
            json.dumps(
                {"_说明": "我的手写备注", "version": 1, "sessionTarget": "isolated"},
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        J.save([_cron_job()], p)
        data = json.loads(p.read_text(encoding="utf-8"))
        assert data["_说明"] == "我的手写备注"
        assert data["sessionTarget"] == "isolated"

    def test_creates_dir(self, tmp_path):
        p = tmp_path / "deep" / "deeper" / "jobs.json"
        J.save([_cron_job()], p)
        assert p.is_file()

    def test_0600_when_posix(self, tmp_path):
        p = tmp_path / "jobs.json"
        J.save([_cron_job()], p)
        if os.name == "posix":
            assert p.stat().st_mode & 0o777 == 0o600

    def test_backup_written(self, tmp_path):
        p = tmp_path / "jobs.json"
        J.save([_cron_job()], p)
        J.save([_cron_job(cron="0 4 * * *")], p)
        backups = list((tmp_path / "backups").glob("jobs.json.*.bak"))
        assert backups
        if os.name == "posix":
            assert backups[0].stat().st_mode & 0o777 == 0o600

    def test_symlink_fail_closed(self, tmp_path, symlinks_supported):
        target = tmp_path / "real.json"
        J.save([_cron_job()], target)
        link = tmp_path / "link.json"
        link.symlink_to(target)
        with pytest.raises(J.JobsError, match="symlink"):
            J.save([_cron_job()], link)

    def test_verify_failure_rolls_back(self, tmp_path, monkeypatch):
        p = tmp_path / "jobs.json"
        J.save([_cron_job()], p)
        original = p.read_text(encoding="utf-8")
        real_load = J.load

        def broken(path=None):
            jobs, _ = real_load(path)
            jobs[0].id = "other"
            return jobs, []

        monkeypatch.setattr(J, "load", broken)
        with pytest.raises(J.JobsError, match="rolled_back"):
            J.save([_cron_job(cron="0 5 * * *")], p)
        assert p.read_text(encoding="utf-8") == original

    def test_dump_is_openclaw_shape(self, tmp_path):
        """落盘字段名必须与 OpenClaw 一致（camelCase + schedule/payload 嵌套）。"""
        p = tmp_path / "jobs.json"
        J.save([_cron_job()], p)
        raw = json.loads(p.read_text(encoding="utf-8"))["jobs"][0]
        assert raw["schedule"] == {
            "kind": "cron",
            "expr": "0 */3 * * *",
            "tz": "Asia/Shanghai",
        }
        assert raw["payload"]["kind"] == "agent_turn"
        assert raw["payload"]["to"] == "group:123"
        assert "deleteAfterRun" in raw and "createdAtMs" in raw
        # 运行状态自 2026-10-29 起落在 state.json，配置面不再掺运行期数据
        assert "state" not in raw and "updatedAtMs" not in raw

    def test_tz_omitted_when_none(self, tmp_path):
        p = tmp_path / "jobs.json"
        J.save([_cron_job(tz=None)], p)
        raw = json.loads(p.read_text(encoding="utf-8"))["jobs"][0]
        assert "tz" not in raw["schedule"]


class TestUpdateState:
    def test_writes_status(self, tmp_path):
        p = tmp_path / "jobs.json"
        J.save([_cron_job()], p)
        J.update_state("j1", status="ok", next_run_ms=1793192400000, path=p)
        jobs, _ = J.load(p)
        assert jobs[0].last_status == "ok"
        assert jobs[0].last_run_at_ms > 0
        assert jobs[0].next_run_at_ms == 1793192400000

    def test_delete_after_run_removes_on_ok(self, tmp_path):
        p = tmp_path / "jobs.json"
        J.save([_cron_job(delete_after_run=True)], p)
        J.update_state("j1", status="ok", path=p)
        jobs, _ = J.load(p)
        assert jobs == []

    def test_delete_after_run_keeps_on_failure(self, tmp_path):
        p = tmp_path / "jobs.json"
        J.save([_cron_job(delete_after_run=True)], p)
        J.update_state("j1", status="failed", path=p)
        jobs, _ = J.load(p)
        assert [j.id for j in jobs] == ["j1"]

    def test_unknown_id_is_noop(self, tmp_path):
        p = tmp_path / "jobs.json"
        J.save([_cron_job()], p)
        before = p.read_text(encoding="utf-8")
        J.update_state("nope", status="ok", path=p)
        assert p.read_text(encoding="utf-8") == before

    def test_without_path_targets_default_location(self, tmp_path, monkeypatch):
        """不传 path 时走 AGENT_CRON_DIR：绝不能默认写到仓库那份真实文件。"""
        monkeypatch.setenv("AGENT_CRON_DIR", str(tmp_path))
        J.save([_cron_job()])
        J.update_state("j1", status="ok")
        jobs, _ = J.load()
        assert jobs[0].last_status == "ok"


class TestNextRun:
    def test_valid(self):
        assert _next_run_ms("0 */3 * * *", None) > 0

    def test_with_tz(self):
        assert _next_run_ms("0 9 * * 1", "Asia/Shanghai") > 0

    def test_bad_expr_returns_zero(self):
        assert _next_run_ms("not a cron", None) == 0

    def test_never_fire_returns_negative_sentinel(self):
        """永触发必须与「解析失败」分开：0 是「从没跑过」的合法值。"""
        assert _next_run_ms("0 0 30 2 *", None) == _NEVER_FIRE
        assert _NEVER_FIRE < 0

    def test_leap_day_is_not_never_fire(self):
        assert _next_run_ms("0 0 29 2 *", None) > 0


class _FakeEngine:
    def __init__(self, text="报告内容"):
        self.text = text
        self.calls = []

    async def run(self, context, message, *a, **kw):
        self.calls.append((context, message))
        return self.text


class _FakeSink:
    def __init__(self, outcome="sent"):
        self.outcome = outcome
        self.sent = []

    async def send_once(self, target, message, *, ref: str = "") -> str:
        self.sent.append((target, message))
        return self.outcome


class _InspectingSink:
    """投递时读一次 jobs.json，记录此刻落盘的状态（验证 pending 先于 send）。"""

    def __init__(self, path, *, crash=False):
        self.path = path
        self.crash = crash
        self.seen = []

    async def send_once(self, target, message, *, ref: str = "") -> str:
        jobs, _ = J.load(self.path)
        self.seen.append((jobs[0].last_status, jobs[0].next_run_at_ms))
        if self.crash:
            raise RuntimeError("boom")
        return "sent"


class TestAgentTurnRunner:
    @pytest.mark.asyncio
    async def test_runs_and_delivers(self, tmp_path):
        p = tmp_path / "jobs.json"
        J.save([_cron_job()], p)
        eng, sink = _FakeEngine(), _FakeSink()
        runner = AgentTurnRunner(eng, sink, allowed_groups={"123"}, jobs_file=p)
        status = await runner.run_job(J.load(p)[0][0])
        assert status == "ok"
        assert eng.calls[0][1] == "执行脚本并发到群里"
        # D4 M2：cron 回合是隔离的 owner 代理——会话键用 cron:<job_id>，不是目标群号
        assert eng.calls[0][0] == {
            "user_id": "cron:j1",
            "group_id": None,
            "owner": True,
            "isolated": True,
            "route": "cron:j1",
        }
        assert sink.sent == [("group:123", "报告内容")]

    @pytest.mark.asyncio
    async def test_empty_output_not_delivered(self, tmp_path):
        p = tmp_path / "jobs.json"
        J.save([_cron_job()], p)
        eng, sink = _FakeEngine(text="   "), _FakeSink()
        runner = AgentTurnRunner(eng, sink, allowed_groups={"123"}, jobs_file=p)
        assert await runner.run_job(J.load(p)[0][0]) == "failed"
        assert sink.sent == []

    @pytest.mark.asyncio
    async def test_uncertain_is_not_failure(self, tmp_path):
        """结果不确定绝不重发：记 uncertain 而非 failed（出站铁律）。"""
        p = tmp_path / "jobs.json"
        J.save([_cron_job()], p)
        runner = AgentTurnRunner(
            _FakeEngine(),
            _FakeSink(outcome="uncertain"),
            allowed_groups={"123"},
            jobs_file=p,
        )
        assert await runner.run_job(J.load(p)[0][0]) == "uncertain"

    @pytest.mark.asyncio
    async def test_engine_exception_is_caught(self, tmp_path):
        p = tmp_path / "jobs.json"
        J.save([_cron_job()], p)

        class _Boom:
            async def run(self, *a, **kw):
                raise RuntimeError("boom")

        runner = AgentTurnRunner(
            _Boom(), _FakeSink(), allowed_groups={"123"}, jobs_file=p
        )
        assert await runner.run_job(J.load(p)[0][0]) == "failed"

    @pytest.mark.asyncio
    async def test_tick_skips_disabled(self, tmp_path, monkeypatch):
        p = tmp_path / "jobs.json"
        J.save([_cron_job(enabled=False)], p)
        monkeypatch.setenv("AGENT_CRON_DIR", str(tmp_path))
        eng, sink = _FakeEngine(), _FakeSink()
        await AgentTurnRunner(eng, sink).tick()
        assert eng.calls == [] and sink.sent == []

    @pytest.mark.asyncio
    async def test_tick_missing_file_is_noop(self, tmp_path, monkeypatch):
        monkeypatch.setenv("AGENT_CRON_DIR", str(tmp_path / "nope"))
        eng, sink = _FakeEngine(), _FakeSink()
        await AgentTurnRunner(eng, sink).tick()
        assert eng.calls == []

    @pytest.mark.asyncio
    async def test_tick_respects_next_run(self, tmp_path, monkeypatch):
        """nextRunAtMs 在未来 → 不到点不跑。"""
        p = tmp_path / "jobs.json"
        job = _cron_job(next_run_at_ms=9999999999999)
        J.save([job], p)
        monkeypatch.setenv("AGENT_CRON_DIR", str(tmp_path))
        eng, sink = _FakeEngine(), _FakeSink()
        await AgentTurnRunner(eng, sink).tick()
        assert eng.calls == []

    @pytest.mark.asyncio
    async def test_tick_bad_json_warns_once(self, tmp_path, monkeypatch, caplog):
        import logging

        p = tmp_path / "jobs.json"
        p.write_text("{broken", encoding="utf-8")
        monkeypatch.setenv("AGENT_CRON_DIR", str(tmp_path))
        runner = AgentTurnRunner(_FakeEngine(), _FakeSink())
        with caplog.at_level(logging.WARNING, logger="agentcore.scheduler.agent_turn"):
            await runner.tick()
            await runner.tick()
            await runner.tick()
        assert caplog.text.count("读取失败") == 1, caplog.text

    @pytest.mark.asyncio
    async def test_run_job_rejects_never_fire_expr(self, caplog):
        """永触发表达式不能跑引擎：装载期已拒，run_job 这道闸要接住直调方。

        run_job 是执行一条 job 的唯一入口（tick 也走它），所以守卫放这里而
        不是只放 tick——放 tick 的版本在装载期修复后不可达，用例会退化成
        恒真断言（删掉守卫照样绿）。
        """
        import logging

        eng, sink = _FakeEngine(), _FakeSink()
        runner = AgentTurnRunner(eng, sink, allowed_groups={"123"})
        with caplog.at_level(logging.WARNING, logger="agentcore.scheduler.agent_turn"):
            status = await runner.run_job(_cron_job(cron="0 0 30 2 *"))
        assert status == "failed"
        assert eng.calls == [] and sink.sent == []
        assert caplog.text.count("永触发") == 1, caplog.text

    def test_warn_once_dedups(self):
        runner = AgentTurnRunner(None, None)
        runner._warn_once("same")
        runner._warn_once("same")
        assert runner._last_error == "same"

    def test_register_requires_scheduler(self):
        assert AgentTurnRunner(None, None).register() is False


class TestTargetACL:
    """群目标必须命中 ALLOWED_GROUPS（2026-10-29）。

    此前文档承诺「不在白名单不会投递」，代码完全不看白名单：手滑写一个真实群号，
    agent 就会在未授权群里跑一轮并说话（既有 bug，不是新功能）。
    变异锚点：删掉 ``run_job`` 里的 ``_target_allowed`` 分支 → 本类全部红。
    """

    @pytest.mark.asyncio
    async def test_group_outside_whitelist_not_run(self, tmp_path, monkeypatch, caplog):
        p = tmp_path / "jobs.json"
        J.save([_cron_job()], p)
        # update_state 不回写 jobs.json 的 path 参数，只能靠 env 把它导向 tmp，
        # 否则会去读仓库里那份真实文件（jobs.update_state 的既有坑）。
        monkeypatch.setenv("AGENT_CRON_DIR", str(tmp_path))
        eng, sink = _FakeEngine(), _FakeSink()
        runner = AgentTurnRunner(eng, sink, allowed_groups={"456"}, jobs_file=p)
        with caplog.at_level(logging.WARNING, logger="agentcore.scheduler.agent_turn"):
            status = await runner.run_job(J.load(p)[0][0])
        assert status == "failed"
        assert eng.calls == [], "白名单外的目标不得跑引擎（省 token，也不外泄模型输出）"
        assert sink.sent == [], "零投递"
        assert "ALLOWED_GROUPS" in caplog.text and "j1" in caplog.text
        # 拦截同样要推进下次执行时刻：否则 tick 每 60s 重试一次，日志与备份都刷屏
        jobs, _ = J.load(p)
        assert jobs[0].last_status == "failed"
        assert jobs[0].next_run_at_ms > 0

    @pytest.mark.asyncio
    async def test_group_inside_whitelist_runs(self, tmp_path):
        p = tmp_path / "jobs.json"
        J.save([_cron_job()], p)
        eng, sink = _FakeEngine(), _FakeSink()
        runner = AgentTurnRunner(eng, sink, allowed_groups={"123"}, jobs_file=p)
        assert await runner.run_job(J.load(p)[0][0]) == "ok"
        assert sink.sent == [("group:123", "报告内容")]

    @pytest.mark.asyncio
    async def test_empty_whitelist_denies_group(self, tmp_path):
        """空集 = 一律拒绝（fail-closed），与 acl.is_allowed 同口径。"""
        p = tmp_path / "jobs.json"
        J.save([_cron_job()], p)
        eng, sink = _FakeEngine(), _FakeSink()
        runner = AgentTurnRunner(eng, sink, jobs_file=p)
        assert await runner.run_job(J.load(p)[0][0]) == "failed"
        assert eng.calls == [] and sink.sent == []

    @pytest.mark.asyncio
    async def test_private_target_allowed_without_group_whitelist(self, tmp_path):
        """私聊目标不受群白名单约束（jobs.json 是部署者本机的配置）。"""
        p = tmp_path / "jobs.json"
        job = _cron_job(to="private:10001")
        J.save([job], p)
        eng, sink = _FakeEngine(), _FakeSink()
        runner = AgentTurnRunner(eng, sink, jobs_file=p)
        assert await runner.run_job(J.load(p)[0][0]) == "ok"
        assert sink.sent == [("private:10001", "报告内容")]
        assert eng.calls[0][0] == {
            "user_id": "cron:j1",
            "group_id": None,
            "owner": True,
            "isolated": True,
            "route": "cron:j1",
        }

    @pytest.mark.asyncio
    async def test_acl_warning_deduped_per_job(self, tmp_path, monkeypatch, caplog):
        """ACL 是启动期常量，告警按 (job, 目标) 去重，不随 tick 刷屏。"""
        job = _cron_job()
        p = tmp_path / "jobs.json"
        J.save([job], p)
        monkeypatch.setenv("AGENT_CRON_DIR", str(tmp_path))
        runner = AgentTurnRunner(
            _FakeEngine(), _FakeSink(), allowed_groups={"456"}, jobs_file=p
        )
        with caplog.at_level(logging.WARNING, logger="agentcore.scheduler.agent_turn"):
            await runner.run_job(job)
            await runner.run_job(job)
        assert caplog.text.count("ALLOWED_GROUPS") == 1, caplog.text


class TestPendingBeforeSend:
    """L3：投递前先落 pending + 推进下次执行，崩溃窗口不重投（2026-10-29）。"""

    @pytest.mark.asyncio
    async def test_pending_written_before_send(self, tmp_path):
        p = tmp_path / "jobs.json"
        J.save([_cron_job()], p)
        sink = _InspectingSink(p)
        runner = AgentTurnRunner(
            _FakeEngine(), sink, allowed_groups={"123"}, jobs_file=p
        )
        assert await runner.run_job(J.load(p)[0][0]) == "ok"
        status, next_ms = sink.seen[0]
        assert status == "pending", "send_once 之前状态必须是 pending（崩溃窗口标记）"
        assert next_ms > 0
        jobs, _ = J.load(p)
        assert jobs[0].last_status == "ok", "正常路径随后被最终状态覆盖"

    @pytest.mark.asyncio
    async def test_crash_during_send_is_not_redelivered(self, tmp_path, monkeypatch):
        monkeypatch.setenv("AGENT_CRON_DIR", str(tmp_path))
        p = tmp_path / "jobs.json"
        J.save([_cron_job()], p)
        eng, sink = _FakeEngine(), _InspectingSink(p, crash=True)
        runner = AgentTurnRunner(eng, sink, allowed_groups={"123"}, jobs_file=p)
        with pytest.raises(RuntimeError):
            await runner.run_job(J.load(p)[0][0])
        # 崩在投递中途：状态停在 pending，但下次执行已推进
        jobs, _ = J.load(p)
        assert jobs[0].last_status == "pending"
        assert jobs[0].next_run_at_ms > 0
        # tick 不再重跑这一轮（否则用户会收到两遍）
        await runner.tick()
        assert len(eng.calls) == 1
        assert len(sink.seen) == 1


class TestHandEditReload:
    """「手改 jobs.json 下轮 tick 生效」必须真的重读文件（B3，2026-10-29 补）。

    此前 tick 只读默认路径，测试传 ``jobs_file`` 时读的却是另一份文件——
    「不重投」那条用例因此没真正验到 state，本条把读路径也锁住。
    """

    @pytest.mark.asyncio
    async def test_tick_reads_edited_file_without_restart(self, tmp_path):
        p = tmp_path / "jobs.json"
        J.save([_cron_job(message="第一版")], p)
        eng, sink = _FakeEngine(), _FakeSink()
        runner = AgentTurnRunner(eng, sink, allowed_groups={"123"}, jobs_file=p)
        await runner.tick()
        assert [m for _c, m in eng.calls] == ["第一版"]
        # 模拟管理员直接编辑：改文案，并把下次执行时刻拨回「立即」（状态侧车挡着）
        raw = json.loads(p.read_text(encoding="utf-8"))
        raw["jobs"][0]["payload"]["message"] = "第二版"
        p.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
        side = J.state_path(p)
        if side.exists():
            side.unlink()
        await runner.tick()
        assert [m for _c, m in eng.calls] == ["第一版", "第二版"], "手改必须下轮生效"
        assert len(sink.sent) == 2


class TestCronTemplateExample:
    """看守仓库自带的模板 ``docs/examples/cron-jobs.example.json``（2026-10-29 搬出 data/）。

    模板不入 ``data/cron/``：那是运行时目录（gitignore），且真实群号必须留在本机。
    """

    def test_repo_jobs_file_is_valid(self):
        p = (
            Path(__file__).resolve().parents[1]
            / "docs"
            / "examples"
            / "cron-jobs.example.json"
        )
        assert p.is_file(), "仓库应自带一份 jobs.json 样例"
        jobs, errors = J.load(p)
        assert errors == [], errors
        assert jobs, "样例至少要有一条"
        for j in jobs:
            assert j.enabled is False, "样例默认停用，避免一上线就误触发"
            assert j.channel == "onebot"
            assert J.parse_target(j.to) is not None

    def test_repo_jobs_file_is_committable_and_runtime_is_ignored(self):
        """模板必须入库（不被 ignore）；``data/cron/`` 是运行时目录，必须被 ignore。"""
        import subprocess

        root = str(Path(__file__).resolve().parents[1])

        def ignored(rel: str) -> bool:
            return (
                subprocess.run(
                    ["git", "check-ignore", "-q", rel],
                    cwd=root,
                    capture_output=True,
                    text=True,
                ).returncode
                == 0
            )

        assert not ignored("docs/examples/cron-jobs.example.json")
        assert ignored("data/cron/jobs.json")
        assert ignored("data/cron/state.json")


class TestStateSidecar:
    """运行状态落 ``state.json``（2026-10-29），jobs.json 保持纯配置。

    变异锚点：把 ``update_state`` 改回写 jobs.json、或去掉 sidecar 读回落，
    本类必须红。
    """

    @staticmethod
    def _write(p, jobs, state_map=None):
        import json

        data = {"version": 1, "jobs": jobs}
        if state_map is not None:
            for job in data["jobs"]:
                if job["id"] in state_map:
                    job["state"] = state_map[job["id"]]
        p.write_text(json.dumps(data), encoding="utf-8")

    def test_update_state_does_not_touch_jobs_json(self, tmp_path):
        p = tmp_path / "jobs.json"
        J.save([_cron_job()], p)
        before = p.read_bytes()
        J.update_state("j1", status="ok", next_run_ms=1234, path=p)
        assert p.read_bytes() == before
        assert J.state_path(p) == tmp_path / "state.json"
        states = json.loads(J.state_path(p).read_text(encoding="utf-8"))["jobs"]
        assert states["j1"]["lastStatus"] == "ok"
        assert states["j1"]["nextRunAtMs"] == 1234
        # 读回来时 sidecar 被叠加到 job 上
        jobs, _ = J.load(p)
        assert jobs[0].last_status == "ok" and jobs[0].next_run_at_ms == 1234

    def test_legacy_embedded_state_is_read_fallback(self, tmp_path):
        p = tmp_path / "jobs.json"
        self._write(
            p,
            [_job_dict()],
            {"j1": {"nextRunAtMs": 7, "lastRunAtMs": 8, "lastStatus": "failed"}},
        )
        jobs, _ = J.load(p)
        assert (
            jobs[0].last_status,
            jobs[0].last_run_at_ms,
            jobs[0].next_run_at_ms,
        ) == (
            "failed",
            8,
            7,
        )

    def test_sidecar_wins_over_embedded(self, tmp_path):
        p = tmp_path / "jobs.json"
        self._write(p, [_job_dict()], {"j1": {"lastStatus": "failed"}})
        J.state_path(p).write_text(
            json.dumps({"version": 1, "jobs": {"j1": {"lastStatus": "ok"}}}),
            encoding="utf-8",
        )
        jobs, _ = J.load(p)
        assert jobs[0].last_status == "ok"

    def test_corrupt_sidecar_warns_and_falls_back(self, tmp_path, caplog):
        p = tmp_path / "jobs.json"
        self._write(p, [_job_dict()], {"j1": {"lastStatus": "failed"}})
        J.state_path(p).write_text("{not json", encoding="utf-8")
        with caplog.at_level(logging.WARNING, logger="agentcore.scheduler.jobs"):
            jobs, _ = J.load(p)
        assert jobs[0].last_status == "failed"
        assert "state sidecar" in caplog.text

    def test_save_persists_existing_state(self, tmp_path):
        p = tmp_path / "jobs.json"
        self._write(p, [_job_dict()], {"j1": {"lastStatus": "ok", "lastRunAtMs": 5}})
        jobs, _ = J.load(p)
        J.save(jobs, p)
        raw = json.loads(p.read_text(encoding="utf-8"))["jobs"][0]
        assert "state" not in raw
        states = json.loads(J.state_path(p).read_text(encoding="utf-8"))["jobs"]
        assert states["j1"]["lastStatus"] == "ok" and states["j1"]["lastRunAtMs"] == 5

    def test_delete_after_run_clears_sidecar_entry(self, tmp_path):
        p = tmp_path / "jobs.json"
        J.save([_cron_job(delete_after_run=True)], p)
        J.update_state("j1", status="ok", path=p)
        jobs, _ = J.load(p)
        assert jobs == []
        states = json.loads(J.state_path(p).read_text(encoding="utf-8"))["jobs"]
        assert "j1" not in states

    def test_no_state_file_written_for_fresh_save(self, tmp_path):
        """全是空状态时不留空壳 sidecar（全新部署的目录保持干净）。"""
        p = tmp_path / "jobs.json"
        J.save([_cron_job()], p)
        assert not J.state_path(p).exists()


class TestNotifyBudgetGate:
    """P3：agent_turn 也受全局打扰预算约束（此前 jobs.json 完全没有上限）。

    变异锚点：去掉 ``run_job`` 里的预算闸 -> 前两条红；去掉 ``outcome == "sent"``
    分支的 ``record`` -> 记账那条红；把 record 挪到 uncertain 分支 -> 不记账那条红。
    """

    @staticmethod
    def _exhaust(runner, target="group:123"):
        """把全局额度用光（用 push 占位：模拟"别的主动投递先用掉了"）。"""
        from agentcore.scheduler.notify_budget import NotifyBudget

        runner._budget = NotifyBudget(runner._budget.path, daily_limit=1)
        runner._budget.record(target, "push")
        return runner._budget

    @pytest.mark.asyncio
    async def test_exhausted_budget_skips_engine_run(
        self, tmp_path, monkeypatch, caplog
    ):
        p = tmp_path / "jobs.json"
        J.save([_cron_job()], p)
        monkeypatch.setenv("AGENT_CRON_DIR", str(tmp_path))
        eng, sink = _FakeEngine(), _FakeSink()
        runner = AgentTurnRunner(eng, sink, allowed_groups={"123"}, jobs_file=p)
        budget = self._exhaust(runner)
        with caplog.at_level(logging.WARNING, logger="agentcore.scheduler.agent_turn"):
            status = await runner.run_job(J.load(p)[0][0])
        assert status == "failed"
        assert eng.calls == [], "撞预算闸不得跑引擎（省 LLM 调用，也不刷屏）"
        assert sink.sent == [], "零投递"
        assert budget.by_kind("group:123") == {"push": 1}, "被拦的一轮不记账"
        assert "打扰预算" in caplog.text
        # 被拦同样要推进下次执行时刻：否则 tick 每 60s 重试一次
        jobs, _ = J.load(p)
        assert jobs[0].last_status == "failed"
        assert jobs[0].next_run_at_ms > 0

    @pytest.mark.asyncio
    async def test_sent_records_budget(self, tmp_path):
        p = tmp_path / "jobs.json"
        J.save([_cron_job()], p)
        runner = AgentTurnRunner(
            _FakeEngine(), _FakeSink(), allowed_groups={"123"}, jobs_file=p
        )
        assert await runner.run_job(J.load(p)[0][0]) == "ok"
        assert runner._budget.by_kind("group:123") == {"agent_turn": 1}

    @pytest.mark.asyncio
    async def test_uncertain_is_not_recorded(self, tmp_path):
        """结果不确定可能没到用户手上：记了会让预算凭空少一格。"""
        p = tmp_path / "jobs.json"
        J.save([_cron_job()], p)
        runner = AgentTurnRunner(
            _FakeEngine(),
            _FakeSink(outcome="uncertain"),
            allowed_groups={"123"},
            jobs_file=p,
        )
        assert await runner.run_job(J.load(p)[0][0]) == "uncertain"
        assert runner._budget.by_kind("group:123") == {}

    @pytest.mark.asyncio
    async def test_budget_warning_deduped_per_job(self, tmp_path, monkeypatch, caplog):
        """预算每天会重置，恢复后要能重新报；同一 (job, 目标) 不重复报。"""
        p = tmp_path / "jobs.json"
        J.save([_cron_job()], p)
        monkeypatch.setenv("AGENT_CRON_DIR", str(tmp_path))
        runner = AgentTurnRunner(
            _FakeEngine(), _FakeSink(), allowed_groups={"123"}, jobs_file=p
        )
        self._exhaust(runner)
        with caplog.at_level(logging.WARNING, logger="agentcore.scheduler.agent_turn"):
            await runner.run_job(J.load(p)[0][0])
            await runner.run_job(J.load(p)[0][0])
        assert caplog.text.count("打扰预算") == 1, caplog.text

    @pytest.mark.asyncio
    async def test_blocked_is_counted_separately(self, tmp_path, monkeypatch, caplog):
        """P4：被拦下的那一轮要单独记账（blocked 段），且不占 spent。"""
        p = tmp_path / "jobs.json"
        J.save([_cron_job()], p)
        monkeypatch.setenv("AGENT_CRON_DIR", str(tmp_path))
        runner = AgentTurnRunner(
            _FakeEngine(), _FakeSink(), allowed_groups={"123"}, jobs_file=p
        )
        budget = self._exhaust(runner)
        with caplog.at_level(logging.WARNING, logger="agentcore.scheduler.agent_turn"):
            await runner.run_job(J.load(p)[0][0])
        # 被拦计数落 blocked 段；days 段只有占位的那一次 push
        assert budget.blocked_by_kind("group:123") == {"agent_turn": 1}
        assert budget.by_kind("group:123") == {"push": 1}
        # 拦下不占额度：上限还是 1，已用 1，剩余 0（不是 -1）
        assert budget.spent("group:123") == 1
        snap = budget.blocked_snapshot()
        assert snap["targets"]["group:123"] == {"total": 1, "agent_turn": 1}
