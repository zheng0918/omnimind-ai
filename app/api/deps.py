"""路由层公共依赖与响应封装。

统一成功响应体 {code, message, data, traceId}（与 interfaceContract §0.2 一致）；
data 若为 pydantic 模型，按 camelCase 别名序列化。
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients.registry import Clients
from app.core.db import get_session
from app.core.trace import get_trace_id
from app.schemas.common import CamelModel


def get_clients(request: Request) -> Clients:
    """从 app.state 取进程级客户端容器。"""
    clients: Clients = request.app.state.clients
    return clients


SessionDep = Annotated[AsyncSession, Depends(get_session)]
ClientsDep = Annotated[Clients, Depends(get_clients)]


def ok(data: CamelModel | dict[str, Any] | None = None) -> dict[str, Any]:
    """构建成功响应体。"""
    if isinstance(data, CamelModel):
        payload: Any = data.model_dump(by_alias=True)
    else:
        payload = data
    return {"code": 0, "message": "ok", "data": payload, "traceId": get_trace_id()}
