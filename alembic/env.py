"""Alembic 环境（异步）。

连接串与 schema 从 Settings 读取，不在配置文件写明文 DSN。所有迁移作用于
omnimind_ai schema，版本表也置于该 schema，确保与 omnimind_biz 完全隔离。
"""

from __future__ import annotations

import asyncio
from logging.config import fileConfig

from alembic import context
from app.core.config import get_settings
from app.models import Base
from app.models.base import SCHEMA
from sqlalchemy import pool, text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata
_settings = get_settings()

# 用 Settings 中的 DSN 覆盖配置（避免在 alembic.ini 写明文）。
config.set_main_option("sqlalchemy.url", _settings.database_url)


def _configure(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        version_table_schema=SCHEMA,
        include_schemas=True,
        compare_type=True,
        compare_server_default=True,
    )


def run_migrations_offline() -> None:
    """离线模式：仅生成 SQL，不连接数据库。"""
    context.configure(
        url=_settings.database_url,
        target_metadata=target_metadata,
        version_table_schema=SCHEMA,
        include_schemas=True,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def _do_run_migrations(connection: Connection) -> None:
    connection.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{SCHEMA}"'))
    connection.execute(text(f'SET search_path TO "{SCHEMA}"'))
    _configure(connection)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    """在线模式：建立异步连接执行迁移。"""
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(_do_run_migrations)
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
