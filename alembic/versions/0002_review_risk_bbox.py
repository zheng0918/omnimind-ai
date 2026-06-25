"""add bbox column to review_risks (precise highlight box)

Revision ID: 0002_review_risk_bbox
Revises: 0001_initial
Create Date: 2026-06-23
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002_review_risk_bbox"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "public"


def upgrade() -> None:
    # 归一化包围盒 [x0,y0,x1,y1]（0~1，左上原点）；前端画精确高亮框，历史数据为 NULL。
    op.add_column(
        "review_risks",
        sa.Column("bbox", postgresql.JSONB(), nullable=True),
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_column("review_risks", "bbox", schema=SCHEMA)
