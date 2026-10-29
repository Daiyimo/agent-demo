"""隐私门禁：真实 QQ 号 / 群号 / 内网地址不得进入仓库。

用法::

    python scripts/check_privacy.py              # 扫 git ls-files（CI 与本地同款）
    python scripts/check_privacy.py --root DIR   # 换扫描根（测试 / 外部目录用）
    python scripts/check_privacy.py --sync       # 读 real-ids.txt 生成 id-hashes.txt

2026-10-29 全历史脱敏整改的 Phase 6：脱敏只解决「已经进去的值」，不解决「下一次
又提交进去」。本脚本是那道闸门，两条规则：

* **规则 A（哈希块名单）**：已跟踪文件里出现的「编号 / 地址候选」token 逐个
  SHA-256，与 ``data/privacy/id-hashes.txt`` 比对，命中即失败。块名单**只存哈希**——
  门禁自己不能成为新的泄漏点（把真实值写进脚本等于把要防的东西抄进仓库，且本仓库
  是公开的）。候选形态 = 5~12 位连续数字 + 点分 IPv4；时间戳、十进制 IP、占位号的
  哈希与真实值不同，零误报。
* **规则 B（形态检查，窄范围）**：``data/workspace/**`` 与 ``config/**`` 是运行期
  配置，入库内容只能是模板——出现 9~11 位连续数字即失败，唯一例外是仓库通用占位号
  （``PLACEHOLDER_TOKENS``，例如 ``data/workspace/cron/jobs.json`` 模板里的
  ``group:123456789``）。范围窄是刻意的：文档与测试里合法的长数字（时间戳、
  十进制 IP 的 SSRF 用例）不该被这条误伤。

命中的值一律**不回显**（文件 + 行号 + 形态说明即可定位），否则 CI 日志本身就是新的
泄漏面。退出码：0 = 通过，1 = 检出问题。
"""

from __future__ import annotations

import argparse
import hashlib
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PRIVACY_DIR = REPO_ROOT / "data" / "privacy"
HASH_FILE = PRIVACY_DIR / "id-hashes.txt"
REAL_IDS_FILE = PRIVACY_DIR / "real-ids.txt"

# 规则 A 的候选 token：点分 IPv4 优先（否则会被 5~12 位数字切成碎片），再取连续数字。
_TOKEN_RE = re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}\b|\b\d{5,12}\b")
# 规则 B：运行期配置里只允许模板，9~11 位连续数字一律视为真实群号 / QQ 号。
_SHAPE_RE = re.compile(r"\b\d{9,11}\b")
_SHAPE_SCOPES = ("data/workspace/", "config/")

# 仓库通用占位号（AGENTS.md §4 的脱敏纪律）：与真实号段的取值域刻意重叠，靠
# 「只在窄范围生效 + 显式白名单」区分。新增占位号要同时改这里与文档，别偷偷放行。
PLACEHOLDER_TOKENS = frozenset(
    {
        "123456789",  # data/workspace/cron/jobs.json 模板的 group:<占位号>
        "13800138000",  # 通用假手机号
        "1000000000",
        "0123456789",
        "999999999",
        "99999999999",
    }
)


def digest(token: str) -> str:
    """token 的 SHA-256 十六进制（块名单与扫描必须同源）。"""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def load_blocklist(path: Path) -> set[str]:
    """读哈希块名单：每行一个 hex，``#`` 开头为注释，空行忽略。"""
    if not path.is_file():
        return set()
    hashes: set[str] = set()
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        hashes.add(line.lower())
    return hashes


def candidate_tokens(text: str) -> list[str]:
    return [m.group(0) for m in _TOKEN_RE.finditer(text)]


def _line_of(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def scan_text(rel: str, text: str, blocklist: set[str]) -> list[str]:
    """单文件扫描：返回问题列表（空 = 干净）。命中值一律不回显。"""
    problems: list[str] = []
    for m in _TOKEN_RE.finditer(text):
        if digest(m.group(0)) in blocklist:
            problems.append(
                f"{rel}:{_line_of(text, m.start())}: 命中哈希块名单"
                "（编号已隐去）——真实标识不得入库，见 AGENTS.md §4 脱敏纪律"
            )
    if rel.replace("\\", "/").startswith(_SHAPE_SCOPES):
        for m in _SHAPE_RE.finditer(text):
            if m.group(0) in PLACEHOLDER_TOKENS:
                continue
            problems.append(
                f"{rel}:{_line_of(text, m.start())}: 运行期配置里出现 9~11 位数字"
                "（疑似真实群号 / QQ 号，值已隐去）——入库内容只能是模板"
            )
    return problems


def iter_tracked(root: Path) -> list[str]:
    """``git ls-files`` 的相对路径清单（只扫入库内容，运行期产物不参与）。"""
    proc = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-z"],
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            "git ls-files 失败（不是 git 仓库？）："
            + proc.stderr.decode("utf-8", "replace").strip()
        )
    return [p for p in proc.stdout.decode("utf-8", "replace").split("\0") if p]


def scan(root: Path, blocklist: set[str]) -> tuple[int, list[str]]:
    """扫 root 下全部已跟踪文件；返回 (文件数, 问题列表)。"""
    problems: list[str] = []
    files = iter_tracked(root)
    for rel in files:
        path = root / rel
        try:
            data = path.read_bytes()
        except OSError as e:  # 已跟踪但磁盘缺失（稀疏检出等）→ 跳过，不误报
            print(f"[warn] 读不到 {rel}：{e}", file=sys.stderr)
            continue
        if b"\x00" in data:  # 二进制（字体 / 图片）不参与
            continue
        problems.extend(scan_text(rel, data.decode("utf-8", "replace"), blocklist))
    return len(files), problems


def sync(root: Path) -> tuple[int, Path]:
    """读 ``real-ids.txt``（本地专用、gitignore）生成只含哈希的块名单。"""
    real = root / REAL_IDS_FILE.relative_to(REPO_ROOT)
    target = root / HASH_FILE.relative_to(REPO_ROOT)
    values = [
        line.strip()
        for line in real.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    hashes = sorted({digest(v) for v in values})
    body = "\n".join(hashes)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        "# 隐私门禁块名单（scripts/check_privacy.py 读取）——**只存 SHA-256**。\n"
        "# 真实值写本机的 data/privacy/real-ids.txt（gitignore），再跑\n"
        "#   python scripts/check_privacy.py --sync\n"
        "# 重新生成本文件；手改哈希没有意义（改错了等于放行）。\n"
        f"{body}\n",
        encoding="utf-8",
    )
    # 自检：输出里绝不能出现原值（否则门禁自己成了泄漏点）
    text = target.read_text(encoding="utf-8")
    leaked = [v for v in values if v in text]
    if leaked:
        raise RuntimeError(f"--sync 生成的文件里出现了 {len(leaked)} 个原值，已中止")
    return len(hashes), target


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="隐私门禁：真实 QQ 号 / 群号 / 内网地址不得入库"
    )
    ap.add_argument("--root", default=str(REPO_ROOT), help="扫描根（默认仓库根）")
    ap.add_argument(
        "--sync",
        action="store_true",
        help="读 data/privacy/real-ids.txt 重新生成 data/privacy/id-hashes.txt",
    )
    args = ap.parse_args(argv)
    root = Path(args.root).resolve()

    if args.sync:
        n, target = sync(root)
        print(f"[ok] 已写入 {target}（{n} 条哈希，无原值）")
        return 0

    blocklist = load_blocklist(root / HASH_FILE.relative_to(REPO_ROOT))
    if not blocklist:
        print(
            "[warn] 块名单为空（data/privacy/id-hashes.txt 缺失或没跑过 --sync）："
            "规则 A 形同关闭，只剩规则 B 的形态检查",
            file=sys.stderr,
        )
    try:
        n_files, problems = scan(root, blocklist)
    except RuntimeError as e:
        print(f"[error] {e}", file=sys.stderr)
        return 1

    if problems:
        print(f"[fail] 隐私门禁：{len(problems)} 处问题（{n_files} 个文件）")
        for p in problems:
            print(f"  - {p}")
        print(
            "修法：真实值改为占位号（AGENTS.md §4 脱敏纪律）；"
            "若确实是新的已知值，写进 data/privacy/real-ids.txt 后跑 --sync"
        )
        return 1
    print(f"[ok] 隐私门禁通过：{n_files} 个文件，{len(blocklist)} 条块名单")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
