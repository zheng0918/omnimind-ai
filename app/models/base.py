"""ORM 基类与公共列。

所有表建在独立 omnimind_ai 库的 public schema，通过 MetaData.schema 统一约束。
命名约定固定，便于 alembic 自动生成稳定的约束/索引名。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, MetaData, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# schema 常量（非密钥），与 Settings.database_schema 默认值一致；
# 已改为独立 omnimind_ai 库 + 默认 public schema。
SCHEMA = "public"

_NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """声明式基类，绑定 public schema 与命名约定。"""

    metadata = MetaData(schema=SCHEMA, naming_convention=_NAMING_CONVENTION)


class IdMixin:
    """自增 BigInteger 主键（与 Java 端 bigint 习惯一致）。"""

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)


class TimestampMixin:
    """创建/更新时间，库端默认值，更新自动刷新。"""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
