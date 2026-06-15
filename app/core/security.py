"""内网鉴权中间件（X-Internal-Token）。

Python 服务只信任内网，由 Java 网关携带共享密钥调用；不接触 JWT、不做业务鉴权
（interfaceContract §0.3 / §三）。校验失败返回错误码 9002。
健康检查与 OpenAPI 文档路径豁免，便于探活与本地调试。
"""

from __future__ import annotations

import hmac

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.core.errors import CODE_INTERNAL_TOKEN_INVALID
from app.core.trace import get_trace_id

INTERNAL_TOKEN_HEADER = "X-Internal-Token"

_EXEMPT_PREFIXES = ("/health", "/docs", "/openapi.json", "/redoc")


class InternalTokenMiddleware(BaseHTTPMiddleware):
    """校验请求头共享密钥；用 hmac.compare_digest 做常量时间比较防时序侧信道。"""

    def __init__(self, app: object, expected_token: str) -> None:
        super().__init__(app)  # type: ignore[arg-type]
        self._expected_token = expected_token

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        if request.url.path.startswith(_EXEMPT_PREFIXES):
            return await call_next(request)

        provided = request.headers.get(INTERNAL_TOKEN_HEADER, "")
        if not hmac.compare_digest(provided, self._expected_token):
            return JSONResponse(
                status_code=401,
                content={
                    "code": CODE_INTERNAL_TOKEN_INVALID,
                    "message": "内部 Token 校验失败",
                    "data": None,
                    "traceId": get_trace_id(),
                },
            )
        return await call_next(request)
