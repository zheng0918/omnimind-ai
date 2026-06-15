"""pydantic 入参 / 出参 / SSE 事件定义。

全局约定：接口出入口字段 camelCase（与 interfaceContract.md 一致），
DB 内部 snake_case，由 `CamelModel` 基类的 alias_generator 自动转换。
"""
