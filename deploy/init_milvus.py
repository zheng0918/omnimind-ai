"""Milvus collection 初始化（部署期一次性执行）。

为何需要：`app/infra/milvus_schema.ensure_collection` 是幂等 bootstrap，但运行时
（lifespan → MilvusVectorStore.connect）只 `load` 已存在的 collection，不会创建。
新环境必须先跑本脚本创建 collection，否则首次 upsert/search 会因 collection 不存在而失败。

维度取 `settings.embed_dim`（当前 text-embedding-v4, dim=2048），与 embedder 输出单一真相。

用法（在项目根目录执行）：
    python deploy/init_milvus.py             # 幂等创建（已存在则跳过）
    python deploy/init_milvus.py --recreate  # 先 drop 再建（维度变更/重置时用，会清空已有向量！）
"""

from __future__ import annotations

import argparse

from app.core.config import Settings, get_settings
from app.infra.milvus_schema import ensure_collection
from loguru import logger
from pymilvus import connections, utility

_DROP_ALIAS = "init_drop"


def _drop_if_exists(settings: Settings) -> None:
    """删除同名 collection（仅 --recreate 时调用）。"""
    connections.connect(
        alias=_DROP_ALIAS,
        host=settings.milvus_host,
        port=str(settings.milvus_port),
        timeout=settings.milvus_timeout_s,
    )
    try:
        if utility.has_collection(settings.milvus_collection, using=_DROP_ALIAS):
            utility.drop_collection(settings.milvus_collection, using=_DROP_ALIAS)
            logger.warning("dropped existing collection: {}", settings.milvus_collection)
    finally:
        connections.disconnect(_DROP_ALIAS)


def main() -> None:
    parser = argparse.ArgumentParser(description="初始化 Milvus collection")
    parser.add_argument(
        "--recreate",
        action="store_true",
        help="先 drop 再建（会清空已有向量；维度变更或重置时使用）",
    )
    args = parser.parse_args()

    settings = get_settings()
    if args.recreate:
        _drop_if_exists(settings)
    ensure_collection(settings)
    logger.info(
        "milvus collection ready: {} (dim={})",
        settings.milvus_collection,
        settings.embed_dim,
    )


if __name__ == "__main__":
    main()
