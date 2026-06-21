"""向量化客户端抽象与百炼实现（text-embedding-v4, dim 可配置）。

维度由 settings.embed_dim 决定并显式传给 v4（v4 默认输出 1024，需 dimension 参数才出 2048）。
百炼单批硬上限 25 段；多批并发受 embed_concurrency 限制（监控 TPM）。
dashscope SDK 为同步阻塞调用，统一用 asyncio.to_thread 卸载 + wait_for 强制超时。
"""

from __future__ import annotations

import asyncio
from typing import Any, Protocol

from dashscope import TextEmbedding
from tenacity import retry, stop_after_attempt, wait_exponential

from app.core.config import Settings
from app.core.errors import CODE_RAG_RETRIEVE_FAILED, ExternalServiceError


class EmbeddingClient(Protocol):
    """向量化协议。embed 保证返回顺序与入参一致。"""

    @property
    def dim(self) -> int:
        """向量维度。"""
        ...

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """批量向量化，返回与输入等长、同序的向量列表。"""
        ...


def _batched(items: list[str], size: int) -> list[list[str]]:
    return [items[i : i + size] for i in range(0, len(items), size)]


class BailianEmbedder:
    """EmbeddingClient 的阿里云百炼实现。"""

    def __init__(self, settings: Settings) -> None:
        self._api_key = settings.dashscope_api_key
        self._model = settings.dashscope_embed_model
        self._dim = settings.embed_dim
        self._batch_size = min(settings.embed_batch_size, 25)
        self._timeout_s = settings.dashscope_timeout_s
        self._semaphore = asyncio.Semaphore(settings.embed_concurrency)

    @property
    def dim(self) -> int:
        return self._dim

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        batches = _batched(texts, self._batch_size)
        results = await asyncio.gather(*(self._embed_batch(b) for b in batches))
        flattened: list[list[float]] = []
        for batch_vectors in results:
            flattened.extend(batch_vectors)
        return flattened

    @retry(stop=stop_after_attempt(2), wait=wait_exponential(multiplier=0.5, max=4), reraise=True)
    async def _embed_batch(self, batch: list[str]) -> list[list[float]]:
        async with self._semaphore:
            resp: Any = await asyncio.wait_for(
                asyncio.to_thread(
                    TextEmbedding.call,
                    model=self._model,
                    input=batch,
                    dimension=self._dim,
                    api_key=self._api_key,
                ),
                timeout=self._timeout_s,
            )
        if getattr(resp, "status_code", None) != 200:
            raise ExternalServiceError(
                CODE_RAG_RETRIEVE_FAILED,
                f"百炼 embedding 调用失败：{getattr(resp, 'code', 'unknown')}",
            )
        items = resp.output["embeddings"]
        ordered = sorted(items, key=lambda x: x["text_index"])
        return [item["embedding"] for item in ordered]
