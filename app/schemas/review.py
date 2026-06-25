"""智能审查相关 schema（REQ-REV）。"""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field

from app.schemas.common import CamelModel


class Strictness(StrEnum):
    """审查严格度。阈值：LOOSE=0.85 / BALANCED=0.7 / STRICT=0.5。"""

    LOOSE = "LOOSE"
    BALANCED = "BALANCED"
    STRICT = "STRICT"


class ReviewStatus(StrEnum):
    RUNNING = "RUNNING"
    DONE = "DONE"
    FAILED = "FAILED"


class Severity(StrEnum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    PASS = "PASS"


class Disposition(StrEnum):
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    EDITED = "EDITED"
    IGNORED = "IGNORED"


class ReviewCreateIn(CamelModel):
    """POST /ai/v1/review 入参。"""

    java_task_id: int
    kb_id: int
    tender_doc_id: int | None = None
    target_doc_id: int
    checklist_id: str | None = None
    strictness: Strictness = Strictness.BALANCED
    use_history: bool = True
    from_write_task_id: int | None = None


class ReviewCreateOut(CamelModel):
    review_task_id: int
    status: ReviewStatus


class ReviewTaskOut(CamelModel):
    """GET /ai/v1/review/{id} 任务状态摘要。"""

    review_task_id: int
    status: ReviewStatus
    progress: int = 0
    total_items: int = 0
    done_items: int = 0
    error_msg: str | None = None


class ReviewRiskOut(CamelModel):
    """单条风险条目。"""

    risk_id: int
    severity: Severity
    risk_type: str | None = None
    title: str | None = None
    description: str | None = None
    original_text: str | None = None
    suggested_text: str | None = None
    source_page: int | None = None
    source_para_id: str | None = None
    confidence: float | None = None
    # 归一化版面包围盒 [x0,y0,x1,y1]（0~1，左上原点），供前端在原文 PDF 上画高亮框；无则 None。
    bbox: list[float] | None = None
    disposition: Disposition = Disposition.PENDING
    related_cases: list[str] = Field(default_factory=list)


class ReviewSummary(CamelModel):
    high: int = 0
    medium: int = 0
    # `pass` 是 Python 关键字；to_camel("pass_") 会保留下划线，故显式指定别名为 "pass"。
    pass_: int = Field(0, alias="pass")


class ReviewRisksOut(CamelModel):
    """GET /ai/v1/review/{id}/risks 增量响应。"""

    last_id: int
    total_items: int
    done_items: int
    status: ReviewStatus
    summary: ReviewSummary
    risks: list[ReviewRiskOut]


class RiskDispositionIn(CamelModel):
    """处置入参。"""

    disposition: Disposition
    ignore_reason: str | None = None
    user_edited_text: str | None = None
