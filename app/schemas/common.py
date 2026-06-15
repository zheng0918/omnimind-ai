"""通用 schema：camelCase 基类、统一响应体、分页结构。"""

from __future__ import annotations

from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel

T = TypeVar("T")


class CamelModel(BaseModel):
    """所有对外 schema 的基类。

    - alias_generator=to_camel：字段以 camelCase 别名输出/接收（如 documentId）；
    - populate_by_name=True：内部仍可用 snake_case 名构造；
    - from_attributes=True：便于从 ORM 实例转换。
    """

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        from_attributes=True,
    )


class ApiResponse(CamelModel, Generic[T]):
    """统一响应体（非流式）：{code, message, data, traceId}。"""

    code: int = 0
    message: str = "ok"
    data: T | None = None
    trace_id: str = "-"


class PageResult(CamelModel, Generic[T]):
    """分页结果。列表接口必须分页（page-api §1.4）。"""

    items: list[T]
    total: int
    page: int
    page_size: int
