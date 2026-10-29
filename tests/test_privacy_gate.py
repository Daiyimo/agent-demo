"""scripts/check_privacy.py 的单测：脱敏纪律的 CI 门禁（Phase 6）。

两条规则的判别力都要能过「改坏实现 → 必失败」的变异复核（清单见文件末注释）。
用例本身**不得**包含任何真实号码——这里一律用临时构造的假值，块名单也现算。

Windows 兼容：全部走 tmp_path + 文本读写，唯一外部依赖是 ``git``（用 ``git add``
把文件放进索引即可，不必 commit，故无需 git user 身份）。
"""

from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load_script():
    spec = importlib.util.spec_from_file_location(
        "check_privacy_script", ROOT / "scripts" / "check_privacy.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


cp = _load_script()

# 假值（与真实号段无关，只为演示形态）：10 位用户号 / 10 位群号 / 点分 IPv4。
FAKE_USER = "1900000123"
FAKE_GROUP = "2900000456"
FAKE_IP = "10.123.45.67"


def _make_tree(tmp_path: Path, files: dict[str, str]) -> Path:
    """建一个临时 git 仓库（只 add，不 commit）并写入给定文件。"""
    for rel, text in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    subprocess.run(["git", "-C", str(tmp_path), "init", "-q"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "add", "-A"], check=True)
    return tmp_path


def _blocklist(*values: str) -> set[str]:
    return {cp.digest(v) for v in values}


class TestTokenExtraction:
    def test_matches_ids_and_dotted_ipv4(self):
        assert cp.candidate_tokens("群 2900000456 与 10.123.45.67") == [
            FAKE_GROUP,
            FAKE_IP,
        ]

    def test_ignores_too_short_and_too_long_digits(self):
        # 4 位（端口）、5 位（正常数字）、12 位是上限，13 位超上限不参与
        assert cp.candidate_tokens("端口 8080，超长 1234567890123，边界 12345") == [
            "12345",
        ]


class TestRuleAHashes:
    def test_hit_reports_location_without_echoing_value(self, tmp_path):
        blocklist = _blocklist(FAKE_GROUP)
        text = "第一行\n群号在第二行：2900000456\n"
        problems = cp.scan_text("docs/x.md", text, blocklist)
        assert len(problems) == 1
        assert problems[0].startswith("docs/x.md:2:")
        assert FAKE_GROUP not in problems[0]  # 门禁日志本身不得成为泄漏面

    def test_dotted_ipv4_is_covered(self):
        problems = cp.scan_text(
            "docs/deploy.md", f"内网 {FAKE_IP} 实测", _blocklist(FAKE_IP)
        )
        assert len(problems) == 1
        assert FAKE_IP not in problems[0]

    def test_placeholder_and_unrelated_digits_are_clean(self):
        blocklist = _blocklist(FAKE_GROUP)
        text = "占位 1000000001、时间戳 1750000999、十进制 IP 2130706433"
        assert cp.scan_text("docs/x.md", text, blocklist) == []


class TestRuleBShape:
    def test_flags_9_to_11_digits_in_runtime_config(self):
        problems = cp.scan_text(
            "data/workspace/cron/jobs.json", '{"to": "group:2900000456"}', set()
        )
        assert len(problems) == 1
        assert "data/workspace/cron/jobs.json:1:" in problems[0]
        assert "2900000456" not in problems[0]

    def test_placeholder_group_in_template_is_allowed(self):
        """jobs.json 模板随仓库分发，占位号必须放行，否则门禁无法在自身上通过。"""
        text = '{"to": "group:123456789"}'
        assert cp.scan_text("data/workspace/cron/jobs.json", text, set()) == []

    def test_scope_is_narrow(self):
        """同一条 10 位数字写在文档里不触发规则 B（那是规则 A 的职责）。"""
        assert cp.scan_text("docs/x.md", "group:2900000456", set()) == []
        assert cp.scan_text("config/agent.json", '{"g": 2900000456}', set()) != []

    def test_digit_length_bounds(self):
        # 8 位与 12 位都不在 9~11 区间（12 位是规则 A 的边界，不是规则 B 的）
        assert cp.scan_text("data/workspace/cron/jobs.json", "12345678", set()) == []
        assert (
            cp.scan_text("data/workspace/cron/jobs.json", "123456789012", set()) == []
        )


class TestEndToEnd:
    def test_clean_tree_passes(self, tmp_path):
        root = _make_tree(tmp_path, {"docs/x.md": "占位 1000000001\n"})
        n_files, problems = cp.scan(root, _blocklist(FAKE_GROUP))
        assert n_files >= 1
        assert problems == []

    def test_leaked_value_fails_via_main(self, tmp_path, capsys):
        root = _make_tree(
            tmp_path,
            {
                "BACKLOG.md": f"真实群号 {FAKE_GROUP}\n",
                "data/privacy/id-hashes.txt": "# 块名单\n"
                + cp.digest(FAKE_GROUP)
                + "\n",
            },
        )
        assert cp.main(["--root", str(root)]) == 1
        out = capsys.readouterr().out
        assert "[fail]" in out
        assert FAKE_GROUP not in out

    def test_empty_blocklist_warns_but_allows_clean_tree(self, tmp_path, capsys):
        root = _make_tree(tmp_path, {"docs/x.md": "nothing\n"})
        assert cp.main(["--root", str(root)]) == 0
        assert "块名单为空" in capsys.readouterr().err

    def test_binary_files_are_skipped(self, tmp_path):
        root = tmp_path
        (root / "data" / "fonts").mkdir(parents=True)
        (root / "data" / "fonts" / "f.bin").write_bytes(b"\x00" + FAKE_GROUP.encode())
        subprocess.run(["git", "-C", str(root), "init", "-q"], check=True)
        subprocess.run(["git", "-C", str(root), "add", "-A"], check=True)
        _, problems = cp.scan(root, _blocklist(FAKE_GROUP))
        assert problems == []


class TestSync:
    def test_generates_hashes_only_and_is_idempotent(self, tmp_path):
        root = tmp_path
        privacy = root / "data" / "privacy"
        privacy.mkdir(parents=True)
        (privacy / "real-ids.txt").write_text(
            f"# 注释行被忽略\n\n{FAKE_USER}\n{FAKE_GROUP}\n{FAKE_USER}\n{FAKE_IP}\n",
            encoding="utf-8",
        )
        n, target = cp.sync(root)
        assert n == 3  # 去重后 3 条
        text = target.read_text(encoding="utf-8")
        for value in (FAKE_USER, FAKE_GROUP, FAKE_IP):
            assert value not in text  # 只存哈希，绝不回显原值
        lines = [ln for ln in text.splitlines() if ln and not ln.startswith("#")]
        assert lines == sorted(lines)
        assert set(lines) == {
            cp.digest(FAKE_USER),
            cp.digest(FAKE_GROUP),
            cp.digest(FAKE_IP),
        }

        first = text
        cp.sync(root)
        assert target.read_text(encoding="utf-8") == first  # 幂等


# 变异复核清单（每项都实测过「改坏 → 用例必红」）：
# 1. ``_TOKEN_RE`` 去掉点分 IPv4 分支 → TestRuleAHashes::test_dotted_ipv4_is_covered 红
# 2. ``_TOKEN_RE`` 上限 12 改成 ``\d{5,}`` → TestTokenExtraction 的红外用例不再红
# 3. ``digest`` 不 encode / 用 md5 → TestRuleAHashes 全红（块名单对不上）
# 4. 命中时不取 ``_line_of`` 而固定 :1 → test_hit_reports_location... 红
# 5. 把命中值拼进问题文本 → 三条「不回显」断言红
# 6. 去掉 ``PLACEHOLDER_TOKENS`` 跳行 → test_placeholder_group_in_template_is_allowed 红
# 7. 规则 B 去掉 scope 判断（全仓库生效）→ test_scope_is_narrow 红
# 8. ``scan`` 不跳过二进制 → test_binary_files_are_skipped 红
# 9. ``sync`` 直接写原值（不哈希）→ TestSync 的「只存哈希」断言红
# 10. ``sync`` 不去重 → n == 3 断言红
# 11. ``main`` 忽略 problems 一律 return 0 → test_leaked_value_fails_via_main 红
# 12. ``load_blocklist`` 不跳过 ``#`` 注释 → 空块名单告警用例红（注释被当哈希）
