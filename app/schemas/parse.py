"""文档解析相关 schema（REQ-KB-04）。"""

from __future__ import annotations

from enum import StrEnum

from app.schemas.common import CamelModel


class ParseStatus(StrEnum):
    """解析任务状态机。"""

    PENDING = "PENDING"
    PARSING = "PARSING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"


class ParseSubmitIn(CamelModel):
    """POST /ai/v1/parse 入参（Java → Python）。"""

    document_id: int
    minio_key: str
    mime_type: str
    kb_id: int


class ParseSubmitOut(CamelModel):
    """解析提交响应：立即返回任务 id。"""

    parse_task_id: int
    status: ParseStatus


class ParseStatusOut(CamelModel):
    """GET /ai/v1/parse/{id}/status 响应。"""

    document_id: int
    status: ParseStatus
    progress: int = 0
    page_count: int | None = None
    error_msg: str | None = None


class ParsedParagraph(CamelModel):
    """解析得到的结构化段落（解析器统一输出，内部使用）。"""

    text: str
    page: int | None = None
    paragraph_id: str
    char_offset: int


class ParsedDocument(CamelModel):
    """解析器返回的完整结构化文档。"""

    paragraphs: list[ParsedParagraph]
    page_count: int
    parser_version: str = "v1"
