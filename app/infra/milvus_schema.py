"""Milvus collection 定义与初始化（omnimind_chunks）。

属 DDL 范畴（与 alembic 迁移并列），单独提供 bootstrap 函数：连接 → 建 collection
→ 建 HNSW/COSINE 索引 → load。运行时检索客户端在 clients 层另行封装。
向量维度 1024（百炼 text-embedding-v3）；只向量化子块。
"""

from __future__ import annotations

from pymilvus import (
    Collection,
    CollectionSchema,
    DataType,
    FieldSchema,
    connections,
    utility,
)

from app.core.config import Settings

_CONN_ALIAS = "bootstrap"


def build_schema() -> CollectionSchema:
    """构建 omnimind_chunks 的字段 schema（spec §Milvus Collection）。"""
    fields = [
        FieldSchema(name="pk", dtype=DataType.INT64, is_primary=True, auto_id=True),
        FieldSchema(name="chunk_id", dtype=DataType.INT64),
        FieldSchema(name="doc_id", dtype=DataType.INT64),
        FieldSchema(name="kb_id", dtype=DataType.INT64),
        FieldSchema(name="tenant_id", dtype=DataType.INT64),
        FieldSchema(name="media_type", dtype=DataType.VARCHAR, max_length=16),
        FieldSchema(name="embedding_ver", dtype=DataType.VARCHAR, max_length=32),
        FieldSchema(name="metadata", dtype=DataType.JSON),
        FieldSchema(name="embedding", dtype=DataType.FLOAT_VECTOR, dim=1024),
    ]
    return CollectionSchema(fields=fields, description="OmniMind child-chunk vectors")


def ensure_collection(settings: Settings) -> None:
    """幂等创建 collection 与索引并 load；已存在则跳过创建。

    连接信息来自 Settings；超时由 milvus_timeout_s 控制。
    """
    connections.connect(
        alias=_CONN_ALIAS,
        host=settings.milvus_host,
        port=str(settings.milvus_port),
        timeout=settings.milvus_timeout_s,
    )
    try:
        name = settings.milvus_collection
        if not utility.has_collection(name, using=_CONN_ALIAS):
            collection = Collection(
                name=name, schema=build_schema(), using=_CONN_ALIAS
            )
            collection.create_index(
                field_name="embedding",
                index_params={
                    "index_type": "HNSW",
                    "metric_type": "COSINE",
                    "params": {"M": 16, "efConstruction": 200},
                },
            )
        else:
            collection = Collection(name=name, using=_CONN_ALIAS)
        collection.load()
    finally:
        connections.disconnect(alias=_CONN_ALIAS)
