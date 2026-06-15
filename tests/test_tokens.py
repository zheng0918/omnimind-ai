"""Token 工具纯逻辑单测（utils.tokens）。"""

from __future__ import annotations

from app.utils.tokens import count_tokens, split_by_tokens, truncate_to_tokens


def test_count_tokens_empty() -> None:
    assert count_tokens("") == 0


def test_count_tokens_positive() -> None:
    assert count_tokens("hello world") > 0


def test_truncate_noop_when_short() -> None:
    text = "short text"
    assert truncate_to_tokens(text, 100) == text


def test_truncate_zero_or_negative() -> None:
    assert truncate_to_tokens("anything", 0) == ""
    assert truncate_to_tokens("anything", -5) == ""


def test_truncate_reduces_token_count() -> None:
    text = "one two three four five six seven eight nine ten"
    out = truncate_to_tokens(text, 3)
    assert count_tokens(out) <= 3
    assert text.startswith(out[: max(len(out) - 2, 0)]) or out in text


def test_split_by_tokens_empty() -> None:
    assert split_by_tokens("", 10, 2) == []
    assert split_by_tokens("text", 0, 0) == []


def test_split_by_tokens_covers_text() -> None:
    text = " ".join(f"w{i}" for i in range(50))
    pieces = split_by_tokens(text, chunk_tokens=10, overlap_tokens=2)
    assert len(pieces) >= 2
    # 每片 token 数不超过窗口大小。
    assert all(count_tokens(p) <= 10 for p in pieces)


def test_split_overlap_clamped() -> None:
    # overlap >= chunk 会被钳制，不应死循环或返回空。
    pieces = split_by_tokens("a b c d e f", chunk_tokens=3, overlap_tokens=99)
    assert pieces
