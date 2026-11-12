#!/usr/bin/env python
"""恢复演练（BACKLOG §2.2）：把最新备份灌进固定名临时库，校验后清理。

    export $(grep -E '^DATABASE_URL=' .env | head -1)      # 源库（只读对比基准）
    python scripts/drill_restore.py                        # 全流程演练
    python scripts/drill_restore.py --dry-run              # 只选最新备份 + verify
    python scripts/drill_restore.py --file data/backups/xxx.sql.gz
    python scripts/drill_restore.py --keep-scratch         # 成功也保留现场

流程：find（最新 .sql.gz）→ verify（SHA256 + 可读）→ 建临时库 → restore →
行数对比（源 vs 临时库，容忍备份后的正常增量 --max-drift-pct）→ 向量抽查
（等距样本 md5 + 非空率 + 维度）→ migrate 账本自愈（备份排除 schema_migrations，
恢复库必须能从空账本重建到代码最新版）→ 删临时库。
成功清场并退出 0；失败保留临时库现场退出 1，供排查。

安全边界：写面只有 ``agent_demo_scratch``（固定名，与 scratch_db 同款
``DROP ... WITH (FORCE)``）；源库只读（count / 抽样 SELECT）；restore 显式传
临时库连接串，不读 DATABASE_URL；不与运行中的 bot 互斥（L20 探测针对的是
「恢复到生产库」，本脚本恢复目标是一次性临时库）。建库刻意向 scratch_db.create()
看齐但独立实现：后者会把含密码的连接串 print 到 stdout，进 cron 日志就是泄漏面。
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import urllib.parse as up
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import find_dotenv, load_dotenv  # noqa: E402
from scratch_db import SCRATCH_DB, _admin_url, _connect, drop  # noqa: E402

from agentcore.backup import (  # noqa: E402
    db_backup as _db_backup,
)
from agentcore.backup import (
    list_backups,
    restore_database,
    verify_backup,
)

DEFAULT_DIM = 1024
VECTOR_TABLE = "kb_chunks"
_CHECKSUM_NOTE = {
    "verified": "SHA256 一致",
    "missing": "无 .sha256 sidecar（旧备份，仅可读性检查）",
    "mismatch": "校验和不符",
}


def _source_url() -> str:
    """源库连接串（只读对比基准）。复用 scratch_db 的显式导出闸：缺 DATABASE_URL
    直接 SystemExit，绝不猜。"""
    return _admin_url()


def _scratch_url() -> str:
    return up.urlparse(_source_url())._replace(path="/" + SCRATCH_DB).geturl()


def mask_url(url: str) -> str:
    """连接串密码打码（报告与 cron 日志不落明文密码）。"""
    parts = up.urlparse(url)
    if parts.password is None:
        return url
    netloc = parts.netloc.replace(f":{parts.password}@", ":***@", 1)
    return parts._replace(netloc=netloc).geturl()


def pick_latest_backup(directory: str) -> Path:
    """选目录里最新的 pg_dump 备份；没有就 fail-loud。"""
    items = [i for i in list_backups(directory) if i["kind"] == "pg_dump"]
    if not items:
        print(
            f"目录里没有可演练的（非加密）pg_dump 备份：{directory}。"
            "加密备份（.sql.gz.age）需先按 restore 同口径解密再演练，"
            "或用 --file 指定单个备份",
            file=sys.stderr,
        )
        raise SystemExit(2)
    return Path(max(items, key=lambda i: i["mtime"])["path"])


async def _create_scratch() -> str:
    """建临时库（幂等），返回连接串。DDL 与 scratch_db.create 同款字面量。"""
    admin = await _connect(_admin_url())
    try:
        await admin.execute(f"DROP DATABASE IF EXISTS {SCRATCH_DB} WITH (FORCE)")
        await admin.execute(f"CREATE DATABASE {SCRATCH_DB}")
    finally:
        await admin.close()
    return _scratch_url()


async def table_counts(conn) -> dict[str, int]:
    """逐表精确 count（pg_stat_user_tables 的 n_live_tup 是估算值，不能用于对账）。"""
    tables = [
        r[0]
        for r in await conn.fetch(
            "SELECT relname FROM pg_stat_user_tables ORDER BY relname"
        )
    ]
    return {t: await conn.fetchval(f'SELECT count(*) FROM "{t}"') for t in tables}


def compare_counts(
    source: dict[str, int],
    restored: dict[str, int],
    max_drift_pct: float,
) -> list[str]:
    """行数对比：临时库每张表都要能对上源库，差值在容忍范围内。

    - 设计内排除表（BACKUP_EXCLUDED_TABLES）不在备份里，恢复库缺它们是预期；
    - 源库在备份之后还会继续写入（bot 在跑），小差值是常态——只拦超阈值的
      （默认 10%）：那个量级说明恢复不完整，而不是"备份后有新消息"。
    """
    problems: list[str] = []
    for table, n in sorted(restored.items()):
        if table not in source:
            problems.append(f"{table}: 源库没有这张表（两边库结构不同代？）")
            continue
        base = max(source[table], 1)
        diff = abs(source[table] - n)
        pct = diff / base * 100
        if pct > max_drift_pct:
            problems.append(
                f"{table}: 源 {source[table]} vs 恢复 {n}（差 {diff} 行 / "
                f"{pct:.1f}% > 容忍 {max_drift_pct}%）"
            )
    for table in sorted(set(source) - set(restored)):
        if table in _db_backup.BACKUP_EXCLUDED_TABLES:
            continue  # 设计内排除（schema_migrations + 统计四表）
        problems.append(f"{table}: 恢复库缺这张表（源 {source[table]} 行）")
    return problems


async def sample_ids(conn, table: str, n: int) -> list[int]:
    """等距抽 n 个 id（含首尾）：按行数均分偏移，不假设 id 连续。"""
    total = await conn.fetchval(f'SELECT count(*) FROM "{table}"')
    if not total:
        return []
    n = max(1, min(n, total))
    if n == 1:
        offsets = [0]
    else:
        offsets = [round((total - 1) * i / (n - 1)) for i in range(n)]
    seen: set[int] = set()
    ids: list[int] = []
    for off in offsets:
        row = await conn.fetchrow(
            f'SELECT id FROM "{table}" ORDER BY id LIMIT 1 OFFSET {int(off)}'
        )
        if row is not None and row[0] not in seen:
            seen.add(row[0])
            ids.append(row[0])
    return ids


async def vector_fingerprints(conn, table: str, ids: list[int]) -> dict[int, str]:
    rows = await conn.fetch(
        f'SELECT id, md5(embedding::text) AS fp FROM "{table}" '
        f"WHERE id = ANY($1::bigint[])",
        ids,
    )
    return {r[0]: r[1] for r in rows}


async def vector_health(conn, table: str) -> tuple[int, int, set[int]]:
    """返回 (非空向量数, 总行数, 出现过的维度集合)。"""
    total = await conn.fetchval(f'SELECT count(*) FROM "{table}"')
    non_null = await conn.fetchval(f'SELECT count(embedding) FROM "{table}"')
    dims = {
        r[0]
        for r in await conn.fetch(
            f'SELECT DISTINCT vector_dims(embedding) FROM "{table}" '
            "WHERE embedding IS NOT NULL"
        )
    }
    return non_null, total, dims


async def check_migration_selfheal(scratch_url: str, dim: int) -> list[str]:
    """账本自愈：备份刻意排除 schema_migrations，恢复库必须能从空账本
    migrate 到代码最新版——这是"恢复完能不能直接开机"的判据。"""
    import asyncpg

    from agentcore.memory.migrate import migrate
    from agentcore.memory.migrations import latest_version

    pool = await asyncpg.create_pool(scratch_url)
    try:
        result = await migrate(pool, dim=dim)
    except Exception as exc:
        return [f"migrate 失败（恢复库无法自愈账本）：{type(exc).__name__}: {exc}"]
    finally:
        await pool.close()
    expected = str(latest_version())
    if str(result.current) != expected:
        problems = [f"账本版本 {result.current} != 代码最新 {expected}（自愈不完整）"]
        return problems
    return []


def _dim_from_env() -> int:
    try:
        return int(os.getenv("EMBEDDING_DIM") or DEFAULT_DIM)
    except ValueError:
        return DEFAULT_DIM


async def run(args) -> int:
    problems: list[str] = []

    backup = Path(args.file) if args.file else pick_latest_backup(args.dir)
    if not backup.is_file():
        print(f"备份文件不存在：{backup}", file=sys.stderr)
        return 2
    print(f"[1/6] 备份：{backup}")

    check = verify_backup(backup)
    if not check.get("ok"):
        print(f"[2/6] verify 失败：{check.get('error') or '未知原因'}", file=sys.stderr)
        return 1
    print(f"[2/6] verify：{check['kind']}，校验和：{_CHECKSUM_NOTE[check['checksum']]}")
    if args.dry_run:
        print("（--dry-run）到此为止，不建库不恢复")
        return 0

    source_url = _source_url()
    scratch_url = await _create_scratch()
    print(f"[3/6] 临时库：{SCRATCH_DB}（{mask_url(scratch_url)}）")

    print("[4/6] restore …")
    try:
        await restore_database(scratch_url, backup)
    except Exception as exc:
        print(f"[4/6] restore 失败：{type(exc).__name__}: {exc}", file=sys.stderr)
        print(
            f"\n❌ 演练未通过。临时库 {SCRATCH_DB} 已保留现场，排查后："
            f"python scripts/scratch_db.py drop --yes"
        )
        return 1
    print("[4/6] restore 完成")

    import asyncpg

    try:
        src = await asyncpg.connect(source_url)
    except Exception as exc:
        # L11（REVIEW-e079b8d..3a3ce4a）：源库连不上时 scratch 已含一整份
        # 生产数据副本——与 restore 失败分支同口径：留现场 + 打印清场指引，
        # 不留一个只有 traceback 的孤儿副本。
        print(f"[5/6] 源库连接失败：{type(exc).__name__}: {exc}", file=sys.stderr)
        print(
            f"\n❌ 演练未通过。临时库 {SCRATCH_DB} 已保留现场，排查后："
            f"python scripts/scratch_db.py drop --yes"
        )
        return 1
    scratch = await asyncpg.connect(scratch_url)
    try:
        src_counts = await table_counts(src)
        scratch_counts = await table_counts(scratch)
        drift = compare_counts(src_counts, scratch_counts, args.max_drift_pct)
        problems += drift
        print(
            f"[5/6] 行数：{len(scratch_counts)} 张表对比完成"
            + (f"，{len(drift)} 处超阈" if drift else "（差值均在容忍内）")
        )

        dim = _dim_from_env()
        if VECTOR_TABLE in scratch_counts:
            s_health = await vector_health(scratch, VECTOR_TABLE)
            r_health = await vector_health(src, VECTOR_TABLE)
            if s_health[1] and s_health[0] != s_health[1]:
                problems.append(
                    f"{VECTOR_TABLE}: 恢复库向量非空 {s_health[0]}/{s_health[1]}"
                )
            if s_health[2] != r_health[2]:
                problems.append(
                    f"{VECTOR_TABLE}: 维度集合不一致 恢复{sorted(s_health[2])} "
                    f"vs 源{sorted(r_health[2])}"
                )
            if s_health[2]:
                dim = sorted(s_health[2])[0]
            ids = await sample_ids(scratch, VECTOR_TABLE, args.sample)
            if ids:
                s_fp = await vector_fingerprints(scratch, VECTOR_TABLE, ids)
                r_fp = await vector_fingerprints(src, VECTOR_TABLE, ids)
                bad = [i for i in ids if s_fp.get(i) != r_fp.get(i)]
                if bad:
                    problems.append(f"{VECTOR_TABLE}: 向量指纹不一致的样本 id={bad}")
            print(
                f"[6/6] 向量：非空 {s_health[0]}/{s_health[1]}，维度 "
                f"{sorted(s_health[2]) or '∅'}，抽查 {len(ids)} 个样本"
            )
        else:
            print(f"[6/6] 向量：恢复库无 {VECTOR_TABLE}，跳过（dim 回落 {dim}）")

        if not problems:
            heal = await check_migration_selfheal(scratch_url, dim)
            problems += heal
            print(
                f"    账本自愈：{'通过' if not heal else '失败'}（migrate(dim={dim})）"
            )
    finally:
        await scratch.close()
        await src.close()

    if problems:
        print("\n❌ 演练未通过：")
        for p in problems:
            print(f"  - {p}")
        print(
            f"\n临时库 {SCRATCH_DB} 已保留现场，排查后："
            f"python scripts/scratch_db.py drop --yes"
        )
        return 1

    if not args.keep_scratch:
        await drop(True)
    print(
        "\n✅ 恢复演练通过：备份可用，恢复库可直接启动（账本自愈 OK）"
        + ("" if args.keep_scratch else "，已清场")
    )
    return 0


def main() -> None:
    # usecwd：从当前工作目录向上找 .env（在哪个部署目录跑就演练哪个部署）。
    # 默认行为是从本脚本文件位置向上找——跨目录调用时会读到另一份部署的
    # .env，源库对不上备份，演练必然红。
    load_dotenv(find_dotenv(usecwd=True))
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--dir", default=os.getenv("AGENT_BACKUP_DIR", "data/backups"))
    parser.add_argument("--file", default=None, help="指定备份（默认选最新 pg_dump）")
    parser.add_argument(
        "--max-drift-pct",
        type=float,
        default=10.0,
        help="行数差容忍百分比（源库在备份后还会写入，差值是常态；默认 10）",
    )
    parser.add_argument(
        "--sample", type=int, default=4, help="向量抽查样本数（等距含首尾，默认 4）"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="只选最新备份 + verify，不建库"
    )
    parser.add_argument(
        "--keep-scratch", action="store_true", help="成功也保留临时库（调试用）"
    )
    args = parser.parse_args()
    try:
        code = asyncio.run(run(args))
    except KeyboardInterrupt:
        # L11：中断时 scratch 可能已含副本——与 run() 内失败分支同口径提示
        print(
            f"\n❌ 演练被中断。临时库 {SCRATCH_DB} 可能已保留现场，排查后："
            f"python scripts/scratch_db.py drop --yes",
            file=sys.stderr,
        )
        code = 130
    raise SystemExit(code)


if __name__ == "__main__":
    main()
