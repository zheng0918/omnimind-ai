"""应用生命周期钩子。

启动：初始化日志、数据库引擎、共享 httpx 客户端（回调 Java 用）。
关闭：释放连接池与 httpx 客户端。
外部存储/向量库客户端（MinIO / Milvus）在其 clients 模块按需建立，
连接对象统一在此装配，避免散落各处新建（python-data-ai §4.6）。
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from loguru import logger

from app.clients.http import new_async_client
from app.clients.registry import build_clients, close_clients, connect_clients
from app.core.config import get_settings
from app.core.db import dispose_engine, init_engine
from app.core.logging import setup_logging
from app.workers.parse_worker import recover_unfinished_parses


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """FastAPI lifespan：装配并在退出时释放进程级资源。"""
    settings = get_settings()
    setup_logging(settings.log_level)
    init_engine(settings)
    app.state.http = new_async_client(settings.java_callback_timeout_s)
    app.state.clients = build_clients(settings, app.state.http)
    await connect_clients(app.state.clients)
    # 后台重跑重启前丢失的孤儿解析任务；不阻塞启动。
    recovery_task = asyncio.create_task(recover_unfinished_parses(app.state.clients))
    logger.info("omnimind-ai started")
    try:
        yield
    finally:
        recovery_task.cancel()
        await close_clients(app.state.clients)
        await app.state.http.aclose()
        await dispose_engine()
        logger.info("omnimind-ai stopped")
