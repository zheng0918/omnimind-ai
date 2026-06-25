"""traceId 全链路传递。

Java 网关生成 `X-Trace-Id`，经 Header 传入；中间件写入 contextvar，
loguru 与回调 Java 时都从该 contextvar 取，实现日志全链路串联。

实现为**纯 ASGI 中间件**而非 BaseHTTPMiddleware：后者会把下游响应经内存流收集后
再转发，导致 StreamingResponse（SSE 问答/编写）被整体缓冲、逐字流式失效。纯 ASGI
中间件只在 `http.response.start` 时改写响应头，不触碰响应体，对流式零干扰。
"""

from __future__ import annotations

from contextvars import ContextVar

from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.utils.ids import new_trace_id

# 当前请求的 traceId；后台任务可显式 set/reset。
trace_id_ctx: ContextVar[str] = ContextVar("trace_id", default="-")

TRACE_HEADER = "X-Trace-Id"


def get_trace_id() -> str:
    """返回当前上下文 traceId（无则返回占位符 '-'）。"""
    return trace_id_ctx.get()


class TraceMiddleware:
    """从请求头取 traceId 写入 contextvar，并回写到响应头（纯 ASGI，不缓冲流式响应）。"""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        trace_id = Headers(scope=scope).get(TRACE_HEADER) or new_trace_id()
        token = trace_id_ctx.set(trace_id)

        async def send_with_trace(message: Message) -> None:
            if message["type"] == "http.response.start":
                MutableHeaders(scope=message)[TRACE_HEADER] = trace_id
            await send(message)

        try:
            # contextvar 在整段流式期间保持有效：await 直到全部 chunk 发送完才返回。
            await self.app(scope, receive, send_with_trace)
        finally:
            trace_id_ctx.reset(token)
