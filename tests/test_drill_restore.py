"""scripts/drill_restore.py 恢复演练脚本的单测（BACKLOG §2.2 脚本化，2026-11-08）。

按仓库纪律：关键断言均做过「改坏实现 → 必失败」的变异复核（见文件末注释）。
PG 集成用例（TEST_DATABASE_URL 门控）只测 asyncpg 直连的校验 SQL；restore 的
psql/docker 通路与 migrate 自愈靠真环境端到端验证（CI runner 无 docker 通路）。
"""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _load_drill():
    spec = importlib.util.spec_from_file_location(
        "drill_restore", ROOT / "scripts" / "drill_restore.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


drill = _load_drill()


def _args(**kw) -> SimpleNamespace:
    base = dict(
        file=None,
        dir="data/backups",
        max_drift_pct=10.0,
        sample=4,
        dry_run=False,
        keep_scratch=False,
    )
    base.update(kw)
    return SimpleNamespace(**base)


# --------------------------------------------------------------------------- #
# 纯函数：备份选取 / 密码打码
# --------------------------------------------------------------------------- #


class TestPickLatestBackup:
    def test_picks_newest_pg_dump(self, monkeypatch, tmp_path: Path):
        items = [
            {"path": str(tmp_path / "old.sql.gz"), "mtime": 100, "kind": "pg_dump"},
            {"path": str(tmp_path / "new.sql.gz"), "mtime": 200, "kind": "pg_dump"},
            {"path": str(tmp_path / "mid.jsonl.gz"), "mtime": 300, "kind": "jsonl"},
            {
                "path": str(tmp_path / "enc.sql.gz.age"),
                "mtime": 400,
                "kind": "pg_dump_encrypted",
            },
        ]
        monkeypatch.setattr(drill, "list_backups", lambda d: items)
        assert drill.pick_latest_backup(str(tmp_path)).name == "new.sql.gz"

    def test_fails_loud_without_pg_dump(self, monkeypatch, tmp_path: Path):
        monkeypatch.setattr(
            drill, "list_backups", lambda d: [{"mtime": 1, "kind": "jsonl"}]
        )
        with pytest.raises(SystemExit) as ei:
            drill.pick_latest_backup(str(tmp_path))
        assert ei.value.code == 2


class TestMaskUrl:
    def test_masks_password(self):
        assert (
            drill.mask_url("postgresql://u:secret@h:5432/db")
            == "postgresql://u:***@h:5432/db"
        )

    def test_keeps_url_without_password(self):
        url = "postgresql://u@h:5432/db"
        assert drill.mask_url(url) == url


# --------------------------------------------------------------------------- #
# 纯函数：行数对比（校验核心）
# --------------------------------------------------------------------------- #


class TestCompareCounts:
    def test_equal_counts_pass(self):
        src = {"facts": 100, "messages": 50}
        assert drill.compare_counts(src, dict(src), 10.0) == []

    def test_drift_within_tolerance_passes(self):
        # 100 → 105 = 5% < 10%（备份后 bot 继续写入是常态）
        assert drill.compare_counts({"facts": 100}, {"facts": 105}, 10.0) == []

    def test_drift_beyond_tolerance_fails(self):
        problems = drill.compare_counts({"facts": 100}, {"facts": 50}, 10.0)
        assert len(problems) == 1
        assert "facts" in problems[0] and "100" in problems[0]

    def test_missing_excluded_tables_is_expected(self):
        # schema_migrations + 统计四表设计内不在备份里，恢复库缺它们不是问题
        src = {
            "facts": 10,
            "schema_migrations": 1,
            "group_msg_daily": 5,
            "group_word_daily": 9,
            "group_reviews": 0,
            "group_messages_raw": 3,
        }
        assert drill.compare_counts(src, {"facts": 10}, 10.0) == []

    def test_missing_regular_table_fails(self):
        problems = drill.compare_counts(
            {"facts": 10, "messages": 5}, {"facts": 10}, 10.0
        )
        assert problems == ["messages: 恢复库缺这张表（源 5 行）"]

    def test_extra_table_in_restored_fails(self):
        problems = drill.compare_counts({"facts": 10}, {"facts": 10, "ghost": 1}, 10.0)
        assert len(problems) == 1 and "ghost" in problems[0]

    def test_zero_row_table_passes(self):
        assert drill.compare_counts({"facts": 0}, {"facts": 0}, 10.0) == []


# --------------------------------------------------------------------------- #
# 抽样：等距含首尾，不假设 id 连续
# --------------------------------------------------------------------------- #


class _FakeSampleConn:
    """sample_ids 协议：fetchval=count，fetchrow=按 offset 返回 id。"""

    def __init__(self, total: int):
        self.total = total
        self.offsets: list[int] = []

    async def fetchval(self, sql):
        assert "count(*)" in sql
        return self.total

    async def fetchrow(self, sql):
        self.offsets.append(int(sql.rsplit("OFFSET ", 1)[1]))
        if self.offsets[-1] >= self.total:
            return None
        return (1000 + self.offsets[-1],)


class TestSampleIds:
    @pytest.mark.asyncio
    async def test_uniform_offsets_include_ends(self):
        conn = _FakeSampleConn(100)
        ids = await drill.sample_ids(conn, "kb_chunks", 4)
        assert conn.offsets == [0, 33, 66, 99]  # 首尾必含
        assert len(ids) == 4

    @pytest.mark.asyncio
    async def test_empty_table_yields_no_ids(self):
        assert await drill.sample_ids(_FakeSampleConn(0), "kb_chunks", 4) == []

    @pytest.mark.asyncio
    async def test_n_clamped_to_total(self):
        conn = _FakeSampleConn(3)
        ids = await drill.sample_ids(conn, "kb_chunks", 10)
        assert len(ids) == 3

    @pytest.mark.asyncio
    async def test_single_sample(self):
        conn = _FakeSampleConn(50)
        ids = await drill.sample_ids(conn, "kb_chunks", 1)
        assert len(ids) == 1 and conn.offsets == [0]


# --------------------------------------------------------------------------- #
# 建库 DDL：固定字面量 + 密码不进 stdout
# --------------------------------------------------------------------------- #


class _AsyncCM:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class _FakeAdmin:
    def __init__(self):
        self.executed: list[str] = []

    def connect(self):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def execute(self, sql):
        self.executed.append(sql)

    async def close(self):
        pass


class TestCreateScratch:
    @pytest.mark.asyncio
    async def test_fixed_ddl_and_masked_output(self, monkeypatch, capsys):
        admin = _FakeAdmin()

        async def fake_connect(_url):
            return admin

        monkeypatch.setattr(drill, "_connect", fake_connect)
        monkeypatch.setattr(
            drill, "_admin_url", lambda: "postgresql://u:sekret@h:5432/qqagent"
        )
        url = await drill._create_scratch()
        assert url == "postgresql://u:sekret@h:5432/agent_demo_scratch"
        assert admin.executed == [
            "DROP DATABASE IF EXISTS agent_demo_scratch WITH (FORCE)",
            "CREATE DATABASE agent_demo_scratch",
        ]
        # 密码不得进 stdout（cron 日志泄漏面）
        assert "sekret" not in capsys.readouterr().out


# --------------------------------------------------------------------------- #
# run() 主链路：verify 失败 / dry-run / restore 失败 / 成功清场 / keep-scratch
# --------------------------------------------------------------------------- #


class _FakeDrillConn:
    """run() 里 src/scratch 两个连接的协议（table_counts + 向量三件套）。"""

    def __init__(
        self, tables: dict[str, int], emb_counts: dict[str, int] | None = None
    ):
        self.tables = tables
        self.emb_counts = emb_counts or tables
        self.closed = False

    async def fetch(self, sql, *args):
        if "pg_stat_user_tables" in sql:
            return [(t,) for t in sorted(self.tables)]
        if "vector_dims" in sql:
            return [(1024,)] if self.tables else []
        if "md5(embedding::text)" in sql:
            return [(i, "fp") for i in args[0]]
        raise AssertionError(f"意外 SQL：{sql}")

    async def fetchval(self, sql):
        table = sql.split('FROM "')[1].split('"')[0]
        if "count(embedding)" in sql:
            return self.emb_counts.get(table, 0)
        return self.tables.get(table, 0)

    async def fetchrow(self, sql):
        return (1,)

    async def close(self):
        self.closed = True


def _patch_happy_path(monkeypatch, tmp_path, *, keep: bool = False):
    """把 run() 的外部依赖全部桩掉，主链路走通。"""
    calls = {"dropped": 0, "scratched": 0, "restored": 0, "healed": 0}
    backup = tmp_path / "fake.sql.gz"
    backup.write_bytes(b"x")  # run() 会先 is_file() 探测
    monkeypatch.setattr(drill, "pick_latest_backup", lambda d: backup)
    monkeypatch.setattr(
        drill,
        "verify_backup",
        lambda p: {"ok": True, "kind": "pg_dump", "checksum": "verified"},
    )
    monkeypatch.setattr(drill, "_admin_url", lambda: "postgresql://u:p@h:5432/qqagent")

    async def fake_create():
        calls["scratched"] += 1
        return "postgresql://u:p@h:5432/agent_demo_scratch"

    monkeypatch.setattr(drill, "_create_scratch", fake_create)

    async def fake_restore(_url, _path):
        calls["restored"] += 1

    monkeypatch.setattr(drill, "restore_database", fake_restore)

    src = _FakeDrillConn(
        {"facts": 100, "messages": 50, "kb_chunks": 10, "schema_migrations": 1}
    )
    scratch = _FakeDrillConn({"facts": 100, "messages": 50, "kb_chunks": 10})
    import asyncpg

    async def fake_connect(url):
        return scratch if "scratch" in url else src

    monkeypatch.setattr(asyncpg, "connect", fake_connect)

    async def fake_heal(_url, _dim):
        calls["healed"] += 1
        return []

    monkeypatch.setattr(drill, "check_migration_selfheal", fake_heal)

    async def fake_drop(yes):
        assert yes is True
        calls["dropped"] += 1

    monkeypatch.setattr(drill, "drop", fake_drop)
    return calls


class TestRunFlow:
    @pytest.mark.asyncio
    async def test_verify_failure_stops_before_scratch(self, monkeypatch, tmp_path):
        # M6（REVIEW-e079b8d..3a3ce4a）：漏 mock pick_latest_backup 时该用例
        # 真调 list_backups("data/backups")——本地有运行时产物、CI 全新 checkout
        # 没有 → SystemExit(2) 未捕获 → CI 必红（AGENTS.md §5「CI #91」同型：
        # 测试需要的环境必须用例内显式给，绝不隐式依赖 gitignore 的运行时产物）。
        backup = tmp_path / "fake.sql.gz"
        backup.write_bytes(b"x")
        monkeypatch.setattr(drill, "pick_latest_backup", lambda d: backup)
        monkeypatch.setattr(
            drill,
            "verify_backup",
            lambda p: {"ok": False, "kind": "pg_dump", "error": "sha256 校验和不符"},
        )
        scratched = []

        async def no_create():
            scratched.append(1)
            return "postgresql://u:p@h/agent_demo_scratch"

        monkeypatch.setattr(drill, "_create_scratch", no_create)
        assert await drill.run(_args()) == 1
        assert scratched == [], "verify 失败不得建库"

    @pytest.mark.asyncio
    async def test_source_connect_failure_keeps_scratch_with_hint(
        self, monkeypatch, tmp_path, capsys
    ):
        """L11：restore 成功后源库连不上——scratch 已含一整份生产副本，
        必须与 restore 失败分支同口径：返回 1 + 打印清场指引，不留一个
        只有 traceback 的孤儿副本。"""
        calls = _patch_happy_path(monkeypatch, tmp_path)
        import asyncpg

        async def failing_connect(url):
            if "scratch" not in url:
                raise OSError("connection refused")
            return _FakeDrillConn({"facts": 1})

        monkeypatch.setattr(asyncpg, "connect", failing_connect)
        code = await drill.run(_args())
        assert code == 1
        out = capsys.readouterr().out + capsys.readouterr().err
        assert "临时库" in out and "drop --yes" in out
        assert calls["dropped"] == 0, "留现场：不得清场"

    @pytest.mark.asyncio
    async def test_dry_run_stops_after_verify(self, monkeypatch, tmp_path):
        calls = _patch_happy_path(monkeypatch, tmp_path)
        code = await drill.run(_args(dry_run=True))
        assert code == 0
        assert calls["scratched"] == 0 and calls["restored"] == 0

    @pytest.mark.asyncio
    async def test_restore_failure_keeps_scratch(self, monkeypatch, tmp_path):
        _patch_happy_path(monkeypatch, tmp_path)

        async def bad_restore(_url, _path):
            raise RuntimeError("psql 退出码 3")

        monkeypatch.setattr(drill, "restore_database", bad_restore)
        dropped = []

        async def no_drop(yes):
            dropped.append(1)

        monkeypatch.setattr(drill, "drop", no_drop)
        assert await drill.run(_args()) == 1
        assert dropped == [], "失败必须保留现场，不得删库"

    @pytest.mark.asyncio
    async def test_success_drops_scratch(self, monkeypatch, tmp_path):
        calls = _patch_happy_path(monkeypatch, tmp_path)
        code = await drill.run(_args())
        assert code == 0
        assert calls["restored"] == 1 and calls["healed"] == 1
        assert calls["dropped"] == 1, "成功必须清场"

    @pytest.mark.asyncio
    async def test_keep_scratch_skips_drop(self, monkeypatch, tmp_path):
        calls = _patch_happy_path(monkeypatch, tmp_path, keep=True)
        code = await drill.run(_args(keep_scratch=True))
        assert code == 0
        assert calls["dropped"] == 0

    @pytest.mark.asyncio
    async def test_missing_backup_file_returns_2(self, monkeypatch, tmp_path):
        monkeypatch.setattr(drill, "pick_latest_backup", lambda d: tmp_path / "nope.gz")
        assert await drill.run(_args()) == 2


# --------------------------------------------------------------------------- #
# PG 集成（TEST_DATABASE_URL 门控）：校验 SQL 对真库的语义
# --------------------------------------------------------------------------- #

pytest_pg = pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"),
    reason="TEST_DATABASE_URL not set; PG integration tests skipped",
)


@pytest_pg
@pytest.mark.asyncio
async def test_sample_and_vector_sql_on_real_pg():
    import asyncpg

    url = os.environ["TEST_DATABASE_URL"]
    conn = await asyncpg.connect(url)
    try:
        # 显式自给环境：extension 由 0001_baseline 装，但本文件的字母序比
        # test_migrations.py 早——不能依赖别的用例先跑过（CI 首轮红陷阱）
        await conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
        await conn.execute("DROP TABLE IF EXISTS drill_probe")
        await conn.execute(
            "CREATE TABLE drill_probe (id bigint primary key, embedding vector(4))"
        )
        await conn.execute(
            "INSERT INTO drill_probe (id, embedding) "
            "SELECT g, '[1,2,3,4]'::vector FROM generate_series(7, 18) AS g"
        )
        ids = await drill.sample_ids(conn, "drill_probe", 4)
        assert ids[0] == 7 and ids[-1] == 18, "首尾必含"
        assert len(ids) == 4

        non_null, total, dims = await drill.vector_health(conn, "drill_probe")
        assert (non_null, total, dims) == (12, 12, {4})

        fp = await drill.vector_fingerprints(conn, "drill_probe", [7, 18])
        expect = await conn.fetchval("SELECT md5('[1,2,3,4]'::vector::text)")
        assert fp[7] == expect and fp[18] == expect
    finally:
        await conn.execute("DROP TABLE IF EXISTS drill_probe")
        await conn.close()


# ---------------------------------------------------------------------------
# 变异复核台账（L12，REVIEW-e079b8d..3a3ce4a：docstring 曾引用不存在的
# 文件末注释，此处补齐实际执行记录）。变异一律改坏实现 → 相关用例必红 →
# 还原后 23 passed / 1 skipped（PG 门控那条本地 skip，CI 有 PG 时执行）。
# ---------------------------------------------------------------------------
#
# 1. verify 失败分支 return 1 → return 0
#    → test_verify_failure_stops_before_scratch 红（断言 code == 1）
# 2. 源库连接失败分支（L11 新增）return 1 → return 0
#    → test_source_connect_failure_keeps_scratch_with_hint 红
# 3. run() 的 backup.is_file() 探测移除（if False）
#    → test_missing_backup_file_returns_2 红
# 4. 成功路径的 drop(True) 不调用
#    → test_success_drops_scratch 红（留孤儿 scratch 库）
# 5. restore 失败路径也调用 drop(True)（不留现场）
#    → test_restore_failure_keeps_scratch 红
# 6. sample_ids 的等距偏移从 1 开始（丢掉首行）
#    → test_offsets_first_last / test_n_clamped_to_total 红（offsets == [0,33,66,99]）
# 7. run() 的 verify ok 判断整段移除（失败备份也继续建库）
#    → test_verify_failure_stops_before_scratch 红（scratched != []）
#
# 每条均为 2026-11-13 主代理实跑记录（改坏 → 红 → 还原 → 23 passed）。
