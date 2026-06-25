"""父子块切片（REQ-KB-04，spec §13.3）。

父块 1024 token，子块 256 token，overlap 0.10。父块按段落顺序累积，保留首段
的页码/段落定位信息；子块在父块文本上按 token 窗口切分并继承父块元数据。
仅子块会被向量化，父块用于回填 LLM 上下文。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.schemas.parse import ParsedParagraph
from app.utils.tokens import count_tokens, split_by_tokens


@dataclass
class ChildChunk:
    """子块：向量化与检索的最小单位。"""

    text: str
    tokens: int


@dataclass
class ParentChunk:
    """父块：检索命中后回填给 LLM 的上下文单位。"""

    text: str
    tokens: int
    page: int | None
    paragraph_id: str
    char_offset: int
    # 取自首段（锚段）的归一化包围盒，用于风险溯源时在原文 PDF 上画高亮框。
    bbox: list[float] | None = None
    children: list[ChildChunk] = field(default_factory=list)


def chunk_document(
    paragraphs: list[ParsedParagraph],
    *,
    parent_tokens: int,
    child_tokens: int,
    overlap_ratio: float,
) -> list[ParentChunk]:
    """把结构化段落切为父子块列表。"""
    parents = _build_parents(paragraphs, parent_tokens)
    overlap = int(child_tokens * overlap_ratio)
    for parent in parents:
        for piece in split_by_tokens(parent.text, child_tokens, overlap):
            parent.children.append(ChildChunk(text=piece, tokens=count_tokens(piece)))
    return parents


def _build_parents(
    paragraphs: list[ParsedParagraph], parent_tokens: int
) -> list[ParentChunk]:
    parents: list[ParentChunk] = []
    buf: list[str] = []
    buf_tokens = 0
    anchor: ParsedParagraph | None = None

    def flush() -> None:
        nonlocal buf, buf_tokens, anchor
        if not buf or anchor is None:
            return
        text = "\n".join(buf)
        parents.append(
            ParentChunk(
                text=text,
                tokens=buf_tokens,
                page=anchor.page,
                paragraph_id=anchor.paragraph_id,
                char_offset=anchor.char_offset,
                bbox=anchor.bbox,
            )
        )
        buf = []
        buf_tokens = 0
        anchor = None

    for para in paragraphs:
        para_tokens = count_tokens(para.text)
        if anchor is None:
            anchor = para
        buf.append(para.text)
        buf_tokens += para_tokens
        if buf_tokens >= parent_tokens:
            flush()
    flush()
    return parents
