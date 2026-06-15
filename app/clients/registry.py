"""客户端容器：进程级装配全部外部客户端，供路由/服务依赖注入。

在 lifespan 构建一次并挂到 app.state.clients；Milvus 连接为有外部依赖的资源，
启动时尽力连接（失败仅告警，调用时再抛 ExternalServiceError），便于本地无依赖启动。
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx
from loguru import logger

from app.clients.java_callback import JavaCallbackClient
from app.clients.milvus_store import MilvusVectorStore
from app.clients.minio_client import MinioClient
from app.core.config import Settings
from app.llm.deepseek import DeepSeekClient
from app.rag.embedder import BailianEmbedder
from app.rag.reranker import BailianReranker


@dataclass
class Clients:
    """聚合所有外部客户端实例。"""

    llm: DeepSeekClient
    embedder: BailianEmbedder
    reranker: BailianReranker
    minio: MinioClient
    vector_store: MilvusVectorStore
    java_callback: JavaCallbackClient


def build_clients(settings: Settings, http: httpx.AsyncClient) -> Clients:
    """构建客户端容器（不含外部连接的副作用）。"""
    return Clients(
        llm=DeepSeekClient(settings),
        embedder=BailianEmbedder(settings),
        reranker=BailianReranker(settings),
        minio=MinioClient(settings),
        vector_store=MilvusVectorStore(settings),
        java_callback=JavaCallbackClient(http, settings),
    )


async def connect_clients(clients: Clients) -> None:
    """建立需要长连接的客户端（Milvus）。失败仅告警，不阻断启动。"""
    try:
        await clients.vector_store.connect()
        logger.info("milvus connected")
    except Exception as exc:
        # 启动期容错：记录后继续，调用时再抛 ExternalServiceError。
        logger.warning("milvus connect failed (deferred): {}", type(exc).__name__)


async def close_clients(clients: Clients) -> None:
    """释放长连接。"""
    try:
        await clients.vector_store.close()
    except Exception as exc:
        logger.warning("milvus close failed: {}", type(exc).__name__)
