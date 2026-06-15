"""重排序客户端抽象与百炼实现（gte-rerank, top_n=8）。"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Protocol

from dashscope import TextReRank
from tenacity import retry, stop_after_attempt, wait_exponential

from app.core.config import Settings
from app.core.errors import CODE_RAG_RETRIEVE_FAILED, ExternalServiceError


@dataclass(frozen=True)
class RerankHit:
    """重排结果：原文档下标 + 相关性得分。"""

    index: int
    score: float


class Reranker(Protocol):
    """重排协议。返回按得分降序的命中（含原始 index，便于映射回文档）。"""

    async def rerank(self, query: str, documents: list[str], top_n: int) -> list[RerankHit]:
        ...


class BailianReranker:
    """Reranker 的阿里云百炼实现。"""

    def __init__(self, settings: Settings) -> None:
        self._api_key = settings.dashscope_api_key
        self._model = settings.dashscope_rerank_model
        self._timeout_s = settings.dashscope_timeout_s

    @retry(stop=stop_after_attempt(2), wait=wait_exponential(multiplier=0.5, max=4), reraise=True)
    async def rerank(self, query: str, documents: list[str], top_n: int) -> list[RerankHit]:
        if not documents:
            return []
        resp: Any = await asyncio.wait_for(
            asyncio.to_thread(
                TextReRank.call,
                model=self._model,
                query=query,
                documents=documents,
                top_n=min(top_n, len(documents)),
                return_documents=False,
                api_key=self._api_key,
            ),
            timeout=self._timeout_s,
        )
        if getattr(resp, "status_code", None) != 200:
            raise ExternalServiceError(
                CODE_RAG_RETRIEVE_FAILED,
                f"百炼 rerank 调用失败：{getattr(resp, 'code', 'unknown')}",
            )
        results = resp.output["results"]
        return [
            RerankHit(index=item["index"], score=item["relevance_score"])
            for item in results
        ]
