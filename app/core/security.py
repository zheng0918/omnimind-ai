"""内网鉴权中间件（X-Internal-Token）。

Python 服务只信任内网，由 Java 网关携带共享密钥调用；不接触 JWT、不做业务鉴权
（interfaceContract §0.3 / §三）。校验失败返回错误码 9002。
健康检查与 OpenAPI 文档路径豁免，便于探活与本地调试。

实现为**纯 ASGI 中间件**而非 BaseHTTPMiddleware：后者会缓冲 StreamingResponse，
破坏 SSE 逐字流式（见 app/core/trace.py 说明）。鉴权只读请求头、不触碰响应体，
通过校验后原样把 scope/receive/send 交给下游，对流式零干扰。
"""

from __future__ import annotations

import hmac

from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from app.core.errors import CODE_INTERNAL_TOKEN_INVALID
from app.core.trace import get_trace_id

INTERNAL_TOKEN_HEADER = "X-Internal-Token"

_EXEMPT_PREFIXES = ("/health", "/docs", "/openapi.json", "/redoc")


class InternalTokenMiddleware:
    """校验请求头共享密钥；用 hmac.compare_digest 做常量时间比较防时序侧信道。"""

    def __init__(self, app: ASGIApp, expected_token: str) -> None:
        self.app = app
        self._expected_token = expected_token

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        if scope["path"].startswith(_EXEMPT_PREFIXES):
            await self.app(scope, receive, send)
            return

        provided = Headers(scope=scope).get(INTERNAL_TOKEN_HEADER, "")
        if not hmac.compare_digest(provided, self._expected_token):
            response = JSONResponse(
                status_code=401,
                content={
                    "code": CODE_INTERNAL_TOKEN_INVALID,
                    "message": "内部 Token 校验失败",
                    "data": None,
                    "traceId": get_trace_id(),
                },
            )
            await response(scope, receive, send)
            return

        await self.app(scope, receive, send)
