"""父子块切片纯逻辑单测（rag.chunker）。"""

from __future__ import annotations

from app.rag.chunker import chunk_document
from app.schemas.parse import ParsedParagraph


def _para(text: str, idx: int, page: int = 1) -> ParsedParagraph:
    return ParsedParagraph(
        text=text, page=page, paragraph_id=f"p{idx}", char_offset=idx * 100
    )


def test_chunk_empty() -> None:
    assert chunk_document([], parent_tokens=100, child_tokens=20, overlap_ratio=0.1) == []


def test_parent_keeps_anchor_metadata() -> None:
    paras = [_para("一段较短的中文测试文本。", 0, page=3)]
    parents = chunk_document(paras, parent_tokens=1000, child_tokens=50, overlap_ratio=0.1)
    assert len(parents) == 1
    assert parents[0].page == 3
    assert parents[0].paragraph_id == "p0"
    assert parents[0].children  # 至少切出一个子块


def test_parent_flush_on_token_threshold() -> None:
    # 每段都超过 parent_tokens 阈值 → 每段一个父块。
    paras = [_para(" ".join(f"word{j}" for j in range(40)), i) for i in range(3)]
    parents = chunk_document(paras, parent_tokens=10, child_tokens=8, overlap_ratio=0.1)
    assert len(parents) == 3


def test_children_inherit_from_parent_text() -> None:
    paras = [_para(" ".join(f"token{j}" for j in range(60)), 0)]
    parents = chunk_document(paras, parent_tokens=1000, child_tokens=16, overlap_ratio=0.25)
    assert len(parents) == 1
    assert len(parents[0].children) >= 2
    assert all(c.tokens > 0 for c in parents[0].children)
