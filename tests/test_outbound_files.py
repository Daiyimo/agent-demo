"""``agentcore.outbound_files``：最近发出文件登记（识别协议端自回声）。

来源：2026-11-06/07 线上——``upload_private_file`` 发出的文件被协议端以普通
``message`` 事件回传，适配层当成「用户发了空消息」并回了「没收到文字或图片」。
"""

import pytest

from agentcore import outbound_files as of


@pytest.fixture(autouse=True)
def _clean_registry():
    of.reset()
    yield
    of.reset()


def test_note_and_match_by_file_id():
    of.note_sent_file("u1", file_id="fid-1", name="a.txt", size=3)
    assert of.is_recent_sent_file("u1", file_id="fid-1")
    # 不同收件人/不同 id 都不算
    assert not of.is_recent_sent_file("u2", file_id="fid-1")
    assert not of.is_recent_sent_file("u1", file_id="fid-2")


def test_hit_is_consumed():
    """命中即消费：同一文件被重复回传或用户重发时不再无限吞掉。"""
    of.note_sent_file("u1", file_id="fid-1")
    assert of.is_recent_sent_file("u1", file_id="fid-1")
    assert not of.is_recent_sent_file("u1", file_id="fid-1")


def test_name_size_fallback_and_size_mismatch():
    of.note_sent_file("u1", name="report.md", size=12)
    assert not of.is_recent_sent_file("u1", name="report.md", size=11)
    assert of.is_recent_sent_file("u1", name="report.md", size=12)


def test_missing_size_matches_by_name_only():
    """协议端回传没带 file_size 时按文件名兜底（否则回声漏网）。"""
    of.note_sent_file("u1", name="report.md", size=12)
    assert of.is_recent_sent_file("u1", name="report.md")


def test_genuine_user_file_same_name_size_not_echo():
    """M2：用户自己发同名同大小文件（QQ 转发/重传）不得判回声。

    修前「bot 发 a.txt → 用户把 a.txt 发回来说帮我看看」第一次就被静默吞掉
    （已复现：is_recent_sent_file → True，消息丢弃），第二次才放行。入站与
    登记的 file_id 都确定且不等 = 不是同一次投递的回传。
    """
    of.note_sent_file("u1", file_id="fid-1", name="a.txt", size=3)
    assert not of.is_recent_sent_file("u1", file_id="fid-USER", name="a.txt", size=3)
    # 无 size 的同名形态同样放行（id 对不上就不是回声）
    of.note_sent_file("u1", file_id="fid-2", name="b.txt", size=9)
    assert not of.is_recent_sent_file("u1", file_id="fid-X", name="b.txt")
    # 真回声仍命中：file_id 相同，或双方都不带 id 的同名（登记侧没记 id 时）
    of.note_sent_file("u1", file_id="fid-3", name="c.txt", size=1)
    assert of.is_recent_sent_file("u1", file_id="fid-3", name="c.txt", size=1)
    of.note_sent_file("u1", name="d.txt", size=2)
    assert of.is_recent_sent_file("u1", name="d.txt", size=2)


def test_entry_expires(monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(of, "_clock", lambda: now[0])
    of.note_sent_file("u1", file_id="fid-1")
    now[0] += of._TTL_SECONDS + 1
    assert not of.is_recent_sent_file("u1", file_id="fid-1")


def test_registry_is_bounded(monkeypatch):
    monkeypatch.setattr(of, "_MAX_ENTRIES", 3)
    now = [1.0]
    monkeypatch.setattr(of, "_clock", lambda: now[0])
    for i in range(10):
        now[0] += 1
        of.note_sent_file("u1", file_id=f"fid-{i}")
    # L8（REVIEW-e079b8d..3a3ce4a）：`<= 3` 对 no-op 退化照样绿（恒真），
    # 改精确等于——写满 10 条必须被裁到 _MAX_ENTRIES。
    assert len(of._entries) == 3


def test_empty_target_is_ignored():
    of.note_sent_file("", file_id="fid-1")
    assert not of.is_recent_sent_file("", file_id="fid-1")
