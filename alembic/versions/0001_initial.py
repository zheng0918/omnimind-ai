"""initial omnimind_ai schema

Revision ID: 0001_initial
Revises:
Create Date: 2026-06-15
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "omnimind_ai"


def _ts_cols() -> list[sa.Column]:
    return [
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    ]


def upgrade() -> None:
    op.execute(f'CREATE SCHEMA IF NOT EXISTS "{SCHEMA}"')

    op.create_table(
        "chunks",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("document_id", sa.BigInteger(), nullable=False),
        sa.Column("kb_id", sa.BigInteger(), nullable=False),
        sa.Column("parent_id", sa.BigInteger(), nullable=True),
        sa.Column("level", sa.String(length=8), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("page", sa.Integer(), nullable=True),
        sa.Column("paragraph_id", sa.String(length=64), nullable=True),
        sa.Column("char_offset", sa.Integer(), nullable=True),
        sa.Column("tokens", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("milvus_pk", sa.BigInteger(), nullable=True),
        sa.Column(
            "media_type", sa.String(length=16), server_default=sa.text("'text'"), nullable=False
        ),
        sa.Column(
            "embedding_ver", sa.String(length=32), server_default=sa.text("'v1'"), nullable=False
        ),
        sa.Column("tenant_id", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "extra", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False
        ),
        sa.Column(
            "metadata", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False
        ),
        *_ts_cols(),
        sa.ForeignKeyConstraint(
            ["parent_id"], [f"{SCHEMA}.chunks.id"], name="fk_chunks_parent_id_chunks",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_chunks"),
        schema=SCHEMA,
    )
    op.create_index("ix_chunks_document_id", "chunks", ["document_id"], schema=SCHEMA)
    op.create_index("ix_chunks_parent_id", "chunks", ["parent_id"], schema=SCHEMA)
    op.create_index("ix_chunks_kb_id", "chunks", ["kb_id"], schema=SCHEMA)
    # 词法检索（BM25/lexical）用的 GIN 全文索引。
    op.execute(
        f"CREATE INDEX ix_chunks_text_tsv ON {SCHEMA}.chunks "
        "USING gin(to_tsvector('simple', text))"
    )

    op.create_table(
        "parse_tasks",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("document_id", sa.BigInteger(), nullable=False),
        sa.Column("kb_id", sa.BigInteger(), nullable=False),
        sa.Column("minio_key", sa.String(length=512), nullable=False),
        sa.Column("mime_type", sa.String(length=128), nullable=True),
        sa.Column(
            "status", sa.String(length=16), server_default=sa.text("'PENDING'"), nullable=False
        ),
        sa.Column("progress", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("page_count", sa.Integer(), nullable=True),
        sa.Column("chunk_count", sa.Integer(), nullable=True),
        sa.Column("error_msg", sa.Text(), nullable=True),
        *_ts_cols(),
        sa.PrimaryKeyConstraint("id", name="pk_parse_tasks"),
        schema=SCHEMA,
    )
    op.create_index("ix_parse_tasks_document_id", "parse_tasks", ["document_id"], schema=SCHEMA)

    op.create_table(
        "chat_sessions",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("java_task_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "kb_id", postgresql.JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False
        ),
        sa.Column("owner_id", sa.BigInteger(), nullable=False),
        sa.Column("tenant_id", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "mode", sa.String(length=16), server_default=sa.text("'precise'"), nullable=False
        ),
        *_ts_cols(),
        sa.PrimaryKeyConstraint("id", name="pk_chat_sessions"),
        schema=SCHEMA,
    )

    op.create_table(
        "chat_messages",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("session_id", sa.BigInteger(), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("citations_json", postgresql.JSONB(), nullable=True),
        sa.Column("reasoning", sa.Text(), nullable=True),
        sa.Column("attachments", postgresql.JSONB(), nullable=True),
        sa.Column("ai_model", sa.String(length=64), nullable=True),
        sa.Column("prompt_ver", sa.String(length=32), nullable=True),
        sa.Column("feedback", sa.String(length=16), nullable=True),
        *_ts_cols(),
        sa.ForeignKeyConstraint(
            ["session_id"], [f"{SCHEMA}.chat_sessions.id"],
            name="fk_chat_messages_session_id_chat_sessions", ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_chat_messages"),
        schema=SCHEMA,
    )
    op.create_index("ix_chat_messages_session_id", "chat_messages", ["session_id"], schema=SCHEMA)

    op.create_table(
        "review_tasks",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("java_task_id", sa.BigInteger(), nullable=False),
        sa.Column("kb_id", sa.BigInteger(), nullable=False),
        sa.Column("tender_doc_id", sa.BigInteger(), nullable=True),
        sa.Column("target_doc_id", sa.BigInteger(), nullable=False),
        sa.Column("checklist_id", sa.String(length=64), nullable=True),
        sa.Column(
            "strictness", sa.String(length=16), server_default=sa.text("'BALANCED'"),
            nullable=False,
        ),
        sa.Column(
            "status", sa.String(length=16), server_default=sa.text("'RUNNING'"), nullable=False
        ),
        sa.Column("progress", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("total_items", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("done_items", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "use_history", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column("from_write_task_id", sa.BigInteger(), nullable=True),
        sa.Column("error_msg", sa.Text(), nullable=True),
        *_ts_cols(),
        sa.PrimaryKeyConstraint("id", name="pk_review_tasks"),
        schema=SCHEMA,
    )

    op.create_table(
        "review_risks",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("review_task_id", sa.BigInteger(), nullable=False),
        sa.Column("severity", sa.String(length=8), nullable=False),
        sa.Column("risk_type", sa.String(length=16), nullable=True),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("original_text", sa.Text(), nullable=True),
        sa.Column("suggested_text", sa.Text(), nullable=True),
        sa.Column("source_page", sa.Integer(), nullable=True),
        sa.Column("source_para_id", sa.String(length=64), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column(
            "disposition", sa.String(length=16), server_default=sa.text("'PENDING'"),
            nullable=False,
        ),
        sa.Column("user_edited_text", sa.Text(), nullable=True),
        sa.Column("ignore_reason", sa.Text(), nullable=True),
        sa.Column("related_cases", postgresql.JSONB(), nullable=True),
        sa.Column("ai_model", sa.String(length=64), nullable=True),
        sa.Column("prompt_ver", sa.String(length=32), nullable=True),
        *_ts_cols(),
        sa.ForeignKeyConstraint(
            ["review_task_id"], [f"{SCHEMA}.review_tasks.id"],
            name="fk_review_risks_review_task_id_review_tasks", ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_review_risks"),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_review_risks_review_task_id", "review_risks", ["review_task_id"], schema=SCHEMA
    )

    op.create_table(
        "write_tasks",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("java_task_id", sa.BigInteger(), nullable=False),
        sa.Column("kb_id", sa.BigInteger(), nullable=False),
        sa.Column("tender_doc_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "status", sa.String(length=16), server_default=sa.text("'EXTRACTING'"),
            nullable=False,
        ),
        sa.Column("project_params_json", postgresql.JSONB(), nullable=True),
        sa.Column(
            "use_history", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column("total_sections", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("done_sections", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("error_msg", sa.Text(), nullable=True),
        *_ts_cols(),
        sa.PrimaryKeyConstraint("id", name="pk_write_tasks"),
        schema=SCHEMA,
    )

    op.create_table(
        "write_score_points",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("write_task_id", sa.BigInteger(), nullable=False),
        sa.Column("point_text", sa.Text(), nullable=False),
        sa.Column("weight", sa.Float(), nullable=True),
        sa.Column(
            "response_status", sa.String(length=16), server_default=sa.text("'NONE'"),
            nullable=False,
        ),
        *_ts_cols(),
        sa.ForeignKeyConstraint(
            ["write_task_id"], [f"{SCHEMA}.write_tasks.id"],
            name="fk_write_score_points_write_task_id_write_tasks", ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_write_score_points"),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_write_score_points_write_task_id", "write_score_points", ["write_task_id"],
        schema=SCHEMA,
    )

    op.create_table(
        "write_outline_nodes",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("write_task_id", sa.BigInteger(), nullable=False),
        sa.Column("parent_id", sa.BigInteger(), nullable=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("order_idx", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("section_id", sa.BigInteger(), nullable=True),
        *_ts_cols(),
        sa.ForeignKeyConstraint(
            ["write_task_id"], [f"{SCHEMA}.write_tasks.id"],
            name="fk_write_outline_nodes_write_task_id_write_tasks", ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["parent_id"], [f"{SCHEMA}.write_outline_nodes.id"],
            name="fk_write_outline_nodes_parent_id_write_outline_nodes", ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_write_outline_nodes"),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_write_outline_nodes_write_task_id", "write_outline_nodes", ["write_task_id"],
        schema=SCHEMA,
    )

    op.create_table(
        "write_sections",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("write_task_id", sa.BigInteger(), nullable=False),
        sa.Column("outline_node_id", sa.BigInteger(), nullable=True),
        sa.Column("content_md", sa.Text(), nullable=True),
        sa.Column(
            "status", sa.String(length=16), server_default=sa.text("'PENDING'"), nullable=False
        ),
        sa.Column("editing_user_id", sa.BigInteger(), nullable=True),
        sa.Column("lock_expire_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ai_model", sa.String(length=64), nullable=True),
        sa.Column("prompt_ver", sa.String(length=32), nullable=True),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=True),
        *_ts_cols(),
        sa.ForeignKeyConstraint(
            ["write_task_id"], [f"{SCHEMA}.write_tasks.id"],
            name="fk_write_sections_write_task_id_write_tasks", ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["outline_node_id"], [f"{SCHEMA}.write_outline_nodes.id"],
            name="fk_write_sections_outline_node_id_write_outline_nodes", ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_write_sections"),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_write_sections_write_task_id", "write_sections", ["write_task_id"], schema=SCHEMA
    )


def downgrade() -> None:
    op.drop_table("write_sections", schema=SCHEMA)
    op.drop_table("write_outline_nodes", schema=SCHEMA)
    op.drop_table("write_score_points", schema=SCHEMA)
    op.drop_table("write_tasks", schema=SCHEMA)
    op.drop_table("review_risks", schema=SCHEMA)
    op.drop_table("review_tasks", schema=SCHEMA)
    op.drop_table("chat_messages", schema=SCHEMA)
    op.drop_table("chat_sessions", schema=SCHEMA)
    op.drop_table("parse_tasks", schema=SCHEMA)
    op.drop_table("chunks", schema=SCHEMA)
