"""向量库抽象与 Milvus 实现（omnimind_chunks）。

VectorStore 协议：upsert / search / delete。一期 MilvusVectorStore；未来可换
PgVector/Qdrant。pymilvus 为同步阻塞，统一 to_thread 卸载 + wait_for 超时。
集合的建表/建索引由 infra.milvus_schema bootstrap 负责，此处只做运行时读写。
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Protocol

from pymilvus import Collection, connections

from app.core.config import Settings
from app.core.errors import CODE_RAG_RETRIEVE_FAILED, ExternalServiceError

_CONN_ALIAS = "runtime"
_SEARCH_EF = 64


@dataclass(frozen=True)
class VectorRecord:
    """待写入的子块向量记录（pk 由 Milvus auto_id 生成）。"""

    chunk_id: int
    doc_id: int
    kb_id: int
    tenant_id: int
    media_type: str
    embedding_ver: str
    metadata: dict[str, Any]
    embedding: list[float]


@dataclass(frozen=True)
class SearchHit:
    """检索命中：子块 chunk_id + 相似度得分（COSINE，越大越相似）。"""

    chunk_id: int
    score: float


class VectorStore(Protocol):
    """向量库协议。"""

    async def upsert(self, records: list[VectorRecord]) -> list[int]:
        """写入向量，返回各记录的 Milvus 主键（与入参同序）。"""
        ...

    async def search(
        self,
        embedding: list[float],
        top_k: int,
        kb_ids: list[int],
        embedding_ver: str | None = None,
    ) -> list[SearchHit]:
        """按知识库范围检索 top_k 个最相似子块；embedding_ver 非空时仅匹配该向量版本。"""
        ...

    async def delete_by_doc(self, doc_id: int) -> None:
        """删除某文档的全部向量（文档删除联动）。"""
        ...


class MilvusVectorStore:
    """VectorStore 的 Milvus 实现。connect/close 在 lifespan 装配。"""

    def __init__(self, settings: Settings) -> None:
        self._host = settings.milvus_host
        self._port = str(settings.milvus_port)
        self._name = settings.milvus_collection
        self._timeout_s = settings.milvus_timeout_s
        self._collection: Collection | None = None

    async def connect(self) -> None:
        """建立连接并 load collection。"""
        await asyncio.to_thread(self._connect_sync)

    def _connect_sync(self) -> None:
        connections.connect(
            alias=_CONN_ALIAS, host=self._host, port=self._port, timeout=self._timeout_s
        )
        collection = Collection(name=self._name, using=_CONN_ALIAS)
        collection.load()
        self._collection = collection

    async def close(self) -> None:
        """断开连接。"""
        await asyncio.to_thread(connections.disconnect, _CONN_ALIAS)
        self._collection = None

    def _require(self) -> Collection:
        if self._collection is None:
            raise ExternalServiceError(
                CODE_RAG_RETRIEVE_FAILED, "Milvus 未连接：应在 lifespan 调用 connect()"
            )
        return self._collection

    async def upsert(self, records: list[VectorRecord]) -> list[int]:
        if not records:
            return []
        collection = self._require()
        data = [
            [r.chunk_id for r in records],
            [r.doc_id for r in records],
            [r.kb_id for r in records],
            [r.tenant_id for r in records],
            [r.media_type for r in records],
            [r.embedding_ver for r in records],
            [r.metadata for r in records],
            [r.embedding for r in records],
        ]
        result = await asyncio.wait_for(
            asyncio.to_thread(collection.insert, data), timeout=self._timeout_s
        )
        await asyncio.to_thread(collection.flush)
        return list(result.primary_keys)

    async def search(
        self,
        embedding: list[float],
        top_k: int,
        kb_ids: list[int],
        embedding_ver: str | None = None,
    ) -> list[SearchHit]:
        collection = self._require()
        clauses: list[str] = []
        if kb_ids:
            clauses.append(f"kb_id in {list(kb_ids)}")
        if embedding_ver:
            clauses.append(f'embedding_ver == "{embedding_ver}"')
        expr = " and ".join(clauses) if clauses else None
        results = await asyncio.wait_for(
            asyncio.to_thread(
                collection.search,
                data=[embedding],
                anns_field="embedding",
                param={"metric_type": "COSINE", "params": {"ef": _SEARCH_EF}},
                limit=top_k,
                expr=expr,
                output_fields=["chunk_id"],
            ),
            timeout=self._timeout_s,
        )
        hits = results[0]
        return [
            SearchHit(chunk_id=int(hit.entity.get("chunk_id")), score=float(hit.distance))
            for hit in hits
        ]

    async def delete_by_doc(self, doc_id: int) -> None:
        collection = self._require()
        await asyncio.wait_for(
            asyncio.to_thread(collection.delete, f"doc_id == {doc_id}"),
            timeout=self._timeout_s,
        )
