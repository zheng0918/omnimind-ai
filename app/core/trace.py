"""traceId 全链路传递。

Java 网关生成 `X-Trace-Id`，经 Header 传入；中间件写入 contextvar，
loguru 与回调 Java 时都从该 contextvar 取，实现日志全链路串联。
"""

from __future__ import annotations

from contextvars import ContextVar

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from app.utils.ids import new_trace_id

# 当前请求的 traceId；后台任务可显式 set/reset。
trace_id_ctx: ContextVar[str] = ContextVar("trace_id", default="-")

TRACE_HEADER = "X-Trace-Id"


def get_trace_id() -> str:
    """返回当前上下文 traceId（无则返回占位符 '-'）。"""
    return trace_id_ctx.get()


class TraceMiddleware(BaseHTTPMiddleware):
    """从请求头取 traceId 写入 contextvar，并回写到响应头。"""

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        trace_id = request.headers.get(TRACE_HEADER) or new_trace_id()
        token = trace_id_ctx.set(trace_id)
        try:
            response: Response = await call_next(request)
        finally:
            trace_id_ctx.reset(token)
        response.headers[TRACE_HEADER] = trace_id
        return response
