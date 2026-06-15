"""LLM 客户端抽象（Protocol）。

一期实现 DeepSeekClient；未来可替换 VllmClient 等，通过环境变量注入。
三种用法：chat（整段返回）、stream（流式 token）、json_mode（JSON Mode 结构化输出）。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any, Protocol, TypedDict


class ChatMessage(TypedDict):
    """对话消息。role ∈ {system,user,assistant}。"""

    role: str
    content: str


class LLMClient(Protocol):
    """大模型客户端协议。所有实现必须设置请求超时。"""

    async def chat(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> str:
        """非流式：返回完整文本。"""
        ...

    def stream(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> AsyncIterator[str]:
        """流式：逐 token（增量文本片段）产出。"""
        ...

    async def json_mode(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> dict[str, Any]:
        """JSON Mode：强制模型输出 JSON 对象并解析为 dict。"""
        ...
