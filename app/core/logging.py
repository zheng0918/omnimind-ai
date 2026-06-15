"""日志初始化（loguru）。

单一日志库 loguru，禁止混用标准 logging。启动时配置为 JSON 序列化输出到 stdout，
并通过 patcher 自动注入当前 traceId。
日志安全：禁止打印 API key / token / 完整 prompt / 密码等敏感信息。
"""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

from loguru import logger

from app.core.trace import get_trace_id

if TYPE_CHECKING:
    from loguru import Record


def _inject_trace(record: Record) -> None:
    """patcher：把当前 contextvar 中的 traceId 注入每条日志的 extra。"""
    record["extra"].setdefault("trace_id", get_trace_id())


def setup_logging(level: str = "INFO") -> None:
    """配置全局 loguru sink。

    Args:
        level: 日志级别（INFO/DEBUG/WARNING/ERROR）。生产建议 INFO。
    """
    logger.remove()
    logger.configure(patcher=_inject_trace)
    # serialize=True 输出 JSON，便于 docker compose logs 收集与检索。
    logger.add(
        sys.stdout,
        level=level,
        serialize=True,
        backtrace=False,  # 不输出完整堆栈到客户端可见处，避免泄露内部细节
        diagnose=False,
        enqueue=True,  # 异步写，避免阻塞 event loop
    )
