"""DeepSeek 客户端（OpenAI 兼容）。

通过 openai.AsyncOpenAI 访问 DeepSeek；统一注入超时；非流式调用带有限重试
（针对超时/连接类瞬时错误）。流式不自动重试，由上层决定。
日志只记 trace 级别信息，绝不记录 prompt/正文（合规）。
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any, cast

from openai import APIConnectionError, APITimeoutError, AsyncOpenAI
from openai.types.chat import ChatCompletionMessageParam
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.core.config import Settings
from app.llm.base import ChatMessage

_TRANSIENT = (APITimeoutError, APIConnectionError)


class DeepSeekClient:
    """LLMClient 的 DeepSeek 实现。"""

    def __init__(self, settings: Settings) -> None:
        self._client = AsyncOpenAI(
            api_key=settings.deepseek_api_key,
            base_url=settings.deepseek_base_url,
            timeout=settings.deepseek_request_timeout_s,
        )
        self._model = settings.deepseek_model
        self._default_temperature = settings.deepseek_temperature
        self._default_max_tokens = settings.deepseek_max_tokens

    def _params(
        self, temperature: float | None, max_tokens: int | None
    ) -> tuple[float, int]:
        return (
            self._default_temperature if temperature is None else temperature,
            self._default_max_tokens if max_tokens is None else max_tokens,
        )

    @staticmethod
    def _to_openai(messages: list[ChatMessage]) -> list[ChatCompletionMessageParam]:
        return cast("list[ChatCompletionMessageParam]", messages)

    @retry(
        retry=retry_if_exception_type(_TRANSIENT),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=0.5, max=4),
        reraise=True,
    )
    async def chat(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> str:
        temp, max_tok = self._params(temperature, max_tokens)
        resp = await self._client.chat.completions.create(
            model=self._model,
            messages=self._to_openai(messages),
            temperature=temp,
            max_tokens=max_tok,
            stream=False,
        )
        return resp.choices[0].message.content or ""

    async def stream(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> AsyncIterator[str]:
        temp, max_tok = self._params(temperature, max_tokens)
        chunks = await self._client.chat.completions.create(
            model=self._model,
            messages=self._to_openai(messages),
            temperature=temp,
            max_tokens=max_tok,
            stream=True,
        )
        async for chunk in chunks:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta.content
            if delta:
                yield delta

    @retry(
        retry=retry_if_exception_type(_TRANSIENT),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=0.5, max=4),
        reraise=True,
    )
    async def json_mode(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> dict[str, Any]:
        _, max_tok = self._params(None, max_tokens)
        resp = await self._client.chat.completions.create(
            model=self._model,
            messages=self._to_openai(messages),
            temperature=temperature,
            max_tokens=max_tok,
            stream=False,
            response_format={"type": "json_object"},
        )
        content = resp.choices[0].message.content or "{}"
        parsed: dict[str, Any] = json.loads(content)
        return parsed
