"""文本工具纯逻辑单测（utils.text）：脱敏 / 规范化 / object_key 安全。"""

from __future__ import annotations

from app.utils.text import (
    StreamingDesensitizer,
    desensitize,
    is_safe_object_key,
    normalize_text,
)


def test_desensitize_mobile_id_email() -> None:
    out = desensitize("联系13912345678，邮箱 a.b@example.com")
    assert "13912345678" not in out
    assert "a.b@example.com" not in out
    assert "[已脱敏]" in out


def test_desensitize_id_card_not_misread_as_mobile() -> None:
    out = desensitize("身份证 11010519491231002X 请核对")
    assert "11010519491231002X" not in out
    assert "[已脱敏]" in out


def test_desensitize_empty() -> None:
    assert desensitize("") == ""


def test_streaming_desensitizer_reassembles_full_text() -> None:
    san = StreamingDesensitizer()
    chunks = ["手机号是1", "3912", "345678", "，结束了请回复确认收到信息"]
    emitted = "".join(san.feed(c) for c in chunks)
    emitted += san.flush()
    assert "13912345678" not in emitted
    assert "13912345678" not in san.full_text
    assert "[已脱敏]" in san.full_text


def test_normalize_text_collapses_spaces_keeps_newline() -> None:
    assert normalize_text("a   b\tc") == "a b c"
    assert "\n" in normalize_text("line1\n\nline2")


def test_normalize_text_empty() -> None:
    assert normalize_text("") == ""


def test_object_key_rejects_traversal_and_bad_chars() -> None:
    assert is_safe_object_key("kb/2024/file_01.pdf")
    assert not is_safe_object_key("../etc/passwd")
    assert not is_safe_object_key("a/../b")
    assert not is_safe_object_key("bad key.pdf")
    assert not is_safe_object_key("")
