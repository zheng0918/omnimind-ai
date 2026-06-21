"""SSE 事件 schema（spec §10.3 + interfaceContract §0.8）。

事件经 Java 原样透传给前端，字段 camelCase，事件名不重命名。
一期事件集：token / citation / progress / done / error。
"""

from __future__ import annotations

from typing import Literal

from app.schemas.common import CamelModel


class Citation(CamelModel):
    """单条引用元数据（答案溯源）。"""

    doc_id: int
    doc_name: str | None = None
    chunk_id: int | None = None
    page: int | None = None
    paragraph_id: str | None = None
    snippet: str
    confidence: float | None = None


class TokenEvent(CamelModel):
    """增量文本事件。"""

    type: Literal["token"] = "token"
    text: str


class CitationEvent(CamelModel):
    """引用列表事件（问答完成时一次性下发）。"""

    type: Literal["citation"] = "citation"
    citations: list[Citation]


class ProgressEvent(CamelModel):
    """阶段进度事件（编写大纲流等）。"""

    type: Literal["progress"] = "progress"
    stage: str
    percent: int


class OutlineNode(CamelModel):
    """编写大纲节点（契约 §1.6 outline 流 token 事件载荷）。"""

    node_id: int
    parent_id: int | None = None
    title: str
    order_idx: int
    section_id: int | None = None


class OutlineNodeEvent(CamelModel):
    """大纲节点增量事件（event:token, data:{node:{...}}）。"""

    type: Literal["token"] = "token"
    node: OutlineNode


class OutlineDoneEvent(CamelModel):
    """大纲流完成事件（契约 §1.6：totalNodes / matchedMaterials）。"""

    type: Literal["done"] = "done"
    total_nodes: int
    matched_materials: int = 0


class SectionDoneEvent(CamelModel):
    """章节流完成事件（契约 §1.6：sectionId / status）。"""

    type: Literal["done"] = "done"
    section_id: int
    status: str = "DONE"


class DoneEvent(CamelModel):
    """完成事件，携带可观测指标。"""

    type: Literal["done"] = "done"
    message_id: int | None = None
    filtered_count: int = 0
    first_token_ms: int | None = None
    total_ms: int | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None


class ErrorEvent(CamelModel):
    """错误事件，发出后关闭流（不抛 HTTPException）。"""

    type: Literal["error"] = "error"
    code: int
    message: str
