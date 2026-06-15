"""FastAPI 入口：装配中间件、全局异常处理、路由、生命周期。

仅做装配，不写业务逻辑（python-project-structure §7.2）。中间件顺序：
TraceMiddleware 最外层（先于鉴权执行，保证错误响应也带 traceId），
InternalTokenMiddleware 次之。
"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from loguru import logger

from app.api.routes import chat, health, parse, review, write
from app.core.config import get_settings
from app.core.errors import CODE_UNKNOWN, BizError
from app.core.lifespan import lifespan
from app.core.security import InternalTokenMiddleware
from app.core.trace import TraceMiddleware, get_trace_id


def _error_body(code: int, message: str) -> dict[str, object]:
    """统一错误响应体（非流式）：{code, message, data, traceId}。"""
    return {"code": code, "message": message, "data": None, "traceId": get_trace_id()}


def create_app() -> FastAPI:
    """构建并返回 FastAPI 应用实例。"""
    settings = get_settings()
    app = FastAPI(
        title="OmniMind AI Service",
        version="0.1.0",
        lifespan=lifespan,
    )

    # 后添加者为最外层：先 Token 校验中间件，再 Trace（使 Trace 最外层）。
    app.add_middleware(InternalTokenMiddleware, expected_token=settings.internal_token)
    app.add_middleware(TraceMiddleware)

    @app.exception_handler(BizError)
    async def handle_biz_error(_: Request, exc: BizError) -> JSONResponse:
        # 9xxx 系统级 → HTTP 500；业务码 → HTTP 200，由 Java 读 code 透传前端。
        status_code = 500 if exc.code >= 9000 else 200
        if status_code == 500:
            logger.error("biz error code={} msg={}", exc.code, exc.message)
        return JSONResponse(status_code=status_code, content=_error_body(exc.code, exc.message))

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        _: Request, exc: RequestValidationError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content=_error_body(1001, f"参数校验失败：{exc.errors()[0].get('msg', '')}"),
        )

    @app.exception_handler(Exception)
    async def handle_unexpected(_: Request, exc: Exception) -> JSONResponse:
        # 不向调用方暴露堆栈；仅记录到日志（含 traceId）。
        logger.exception("unhandled error: {}", type(exc).__name__)
        return JSONResponse(status_code=500, content=_error_body(CODE_UNKNOWN, "未知系统异常"))

    app.include_router(health.router)
    app.include_router(parse.router)
    app.include_router(chat.router)
    app.include_router(review.router)
    app.include_router(write.router)
    return app


app = create_app()
