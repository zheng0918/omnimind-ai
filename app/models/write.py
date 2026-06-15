"""智能编写任务相关表（REQ-WRT / REQ-LINK）。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
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


class WriteTask(Base, IdMixin, TimestampMixin):
    """编写任务。status：EXTRACTING|MATCHING|GENERATING|DONE|FAILED。"""

    __tablename__ = "write_tasks"

    java_task_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    kb_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    tender_doc_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'EXTRACTING'")
    )
    project_params_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    use_history: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    total_sections: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    done_sections: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    error_msg: Mapped[str | None] = mapped_column(Text, nullable=True)


class WriteScorePoint(Base, IdMixin, TimestampMixin):
    """从招标文件抽取的评分点。response_status：NONE|PARTIAL|RESPONDED。"""

    __tablename__ = "write_score_points"

    write_task_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("write_tasks.id", ondelete="CASCADE"), nullable=False
    )
    point_text: Mapped[str] = mapped_column(Text, nullable=False)
    weight: Mapped[float | None] = mapped_column(Float, nullable=True)
    response_status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'NONE'")
    )

    __table_args__ = (Index("ix_write_score_points_write_task_id", "write_task_id"),)


class WriteOutlineNode(Base, IdMixin, TimestampMixin):
    """编写大纲节点（树形）。section_id 指向对应正文段落。"""

    __tablename__ = "write_outline_nodes"

    write_task_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("write_tasks.id", ondelete="CASCADE"), nullable=False
    )
    parent_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("write_outline_nodes.id", ondelete="CASCADE"), nullable=True
    )
    title: Mapped[str] = mapped_column(Text, nullable=False)
    order_idx: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    section_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    __table_args__ = (Index("ix_write_outline_nodes_write_task_id", "write_task_id"),)


class WriteSection(Base, IdMixin, TimestampMixin):
    """正文段落。status：PENDING|GENERATING|DONE|USER_EDITED。"""

    __tablename__ = "write_sections"

    write_task_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("write_tasks.id", ondelete="CASCADE"), nullable=False
    )
    outline_node_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("write_outline_nodes.id", ondelete="SET NULL"),
        nullable=True,
    )
    content_md: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'PENDING'")
    )
    # 协作锁预留（一期不用）。
    editing_user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    lock_expire_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    ai_model: Mapped[str | None] = mapped_column(String(64), nullable=True)
    prompt_ver: Mapped[str | None] = mapped_column(String(32), nullable=True)
    generated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (Index("ix_write_sections_write_task_id", "write_task_id"),)
