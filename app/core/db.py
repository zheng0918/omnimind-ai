"""异步数据库引擎与会话工厂（仅 omnimind_ai schema）。

engine / session_factory 属于"连接对象"，按 python-data-ai §4.6 允许进程内全局复用，
在 lifespan 启动时初始化、关闭时释放。后台 worker 无 Request 上下文，通过
`session_scope()` 直接获取会话；路由层用 `get_session` 依赖注入。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import Settings

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def init_engine(settings: Settings) -> AsyncEngine:
    """创建异步引擎与会话工厂（lifespan 启动时调用一次）。

    通过 asyncpg `server_settings.search_path` 把会话默认 schema 固定为
    omnimind_ai，配合 ORM metadata 的 schema，确保不触碰 omnimind_biz。
    """
    global _engine, _session_factory
    if _engine is not None:
        return _engine
    _engine = create_async_engine(
        settings.database_url,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_pre_ping=True,
        connect_args={"server_settings": {"search_path": settings.database_schema}},
    )
    _session_factory = async_sessionmaker(
        _engine, expire_on_commit=False, autoflush=False
    )
    return _engine


async def dispose_engine() -> None:
    """释放连接池（lifespan 关闭时调用）。"""
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _session_factory = None


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """返回会话工厂；未初始化时抛错（避免静默返回 None）。"""
    if _session_factory is None:
        raise RuntimeError("数据库引擎未初始化：init_engine 应在 lifespan 启动时调用")
    return _session_factory


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    """事务性会话上下文：正常提交、异常回滚、始终关闭。供后台任务使用。"""
    factory = get_session_factory()
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI 依赖：注入事务性会话。"""
    async with session_scope() as session:
        yield session
