"""Alembic 环境（异步）。

连接串与 schema 从 Settings 读取，不在配置文件写明文 DSN。迁移作用于独立
omnimind_ai 库的 public schema，版本表也置于该 schema。
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
    # 直接注入原始 DSN，绕开 configparser 插值（密码含 % 编码会被误解析）。
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = _settings.database_url
    connectable = async_engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(_do_run_migrations)
        # SQLAlchemy 2.0 异步连接是 commit-as-you-go；且迁移内先执行了 CREATE SCHEMA
        # 开启隐式事务，使 alembic 的 begin_transaction 不再发 COMMIT，故须显式提交，
        # 否则连接关闭时全部 DDL 被回滚。
        await connection.commit()
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
