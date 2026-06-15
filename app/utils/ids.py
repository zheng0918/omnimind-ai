"""ID 与 traceId 生成工具。"""

from __future__ import annotations

import uuid


def new_trace_id() -> str:
    """生成新的 traceId（无连字符的 hex，便于日志检索）。"""
    return uuid.uuid4().hex


def new_uuid() -> str:
    """生成标准 UUID 字符串。"""
    return str(uuid.uuid4())
