"""切片表 chunks（父子块）。子块向量化入 Milvus，父块供 RAG 上下文。"""

from __future__ import annotations

from sqlalchemy import BigInteger, ForeignKey, Index, Integer, String, Text
from sqlalchemy import text as sa_text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, IdMixin, TimestampMixin


class Chunk(Base, IdMixin, TimestampMixin):
    """父子块统一存储；level 区分 PARENT/CHILD，子块通过 parent_id 指向父块。"""

    __tablename__ = "chunks"

    document_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    kb_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    parent_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("chunks.id", ondelete="CASCADE"), nullable=True
    )
    level: Mapped[str] = mapped_column(String(8), nullable=False)  # PARENT | CHILD
    text: Mapped[str] = mapped_column(Text, nullable=False)
    page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    paragraph_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    char_offset: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tokens: Mapped[int] = mapped_column(Integer, nullable=False, server_default=sa_text("0"))
    # 子块向量写入 Milvus 后回写其主键，便于删除联动。
    milvus_pk: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    media_type: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=sa_text("'text'")
    )
    embedding_ver: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default=sa_text("'v1'")
    )
    tenant_id: Mapped[int] = mapped_column(
        BigInteger, nullable=False, server_default=sa_text("0")
    )
    extra: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=sa_text("'{}'::jsonb")
    )
    # 预留通用元数据（attr 名避开 DeclarativeBase 保留的 metadata）。
    meta: Mapped[dict] = mapped_column(
        "metadata", JSONB, nullable=False, server_default=sa_text("'{}'::jsonb")
    )

    __table_args__ = (
        Index("ix_chunks_document_id", "document_id"),
        Index("ix_chunks_parent_id", "parent_id"),
        Index("ix_chunks_kb_id", "kb_id"),
    )
