"""共享 httpx 客户端工厂。

连接对象进程内复用（python-data-ai §4.6），统一设置超时；在 lifespan 装配，
业务层通过 app.state.http 取用，禁止散落新建。
"""

from __future__ import annotations

import httpx


def new_async_client(timeout_s: float) -> httpx.AsyncClient:
    """创建带超时的异步 HTTP 客户端。"""
    return httpx.AsyncClient(timeout=timeout_s)
