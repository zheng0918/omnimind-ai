"""智能审查任务与风险表（REQ-REV）。"""

from __future__ import annotations

from sqlalchemy import (
    BigInteger,
    Boolean,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, IdMixin, TimestampMixin


class ReviewTask(Base, IdMixin, TimestampMixin):
    """审查任务。status：RUNNING|DONE|FAILED；支持断点续审与编写→审查反向引用。"""

    __tablename__ = "review_tasks"

    java_task_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    kb_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    tender_doc_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    target_doc_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    checklist_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    strictness: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'BALANCED'")
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'RUNNING'")
    )
    progress: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    total_items: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    done_items: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    use_history: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    from_write_task_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    error_msg: Mapped[str | None] = mapped_column(Text, nullable=True)


class ReviewRisk(Base, IdMixin, TimestampMixin):
    """单条风险项。severity：HIGH|MEDIUM|PASS；disposition 记录用户处置。"""

    __tablename__ = "review_risks"

    review_task_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("review_tasks.id", ondelete="CASCADE"), nullable=False
    )
    severity: Mapped[str] = mapped_column(String(8), nullable=False)
    risk_type: Mapped[str | None] = mapped_column(String(16), nullable=True)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    original_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    suggested_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_para_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    # 归一化版面包围盒 [x0,y0,x1,y1]（0~1，左上原点），供前端在原文 PDF 上画精确高亮框。
    bbox: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    disposition: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'PENDING'")
    )
    user_edited_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    ignore_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    related_cases: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    ai_model: Mapped[str | None] = mapped_column(String(64), nullable=True)
    prompt_ver: Mapped[str | None] = mapped_column(String(32), nullable=True)

    __table_args__ = (Index("ix_review_risks_review_task_id", "review_task_id"),)
