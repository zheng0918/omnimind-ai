"""MinIO 客户端（只读源文件）。

按 object_key 拉取原文字节供解析。minio SDK 为同步阻塞，统一用 to_thread 卸载。
object_key 经白名单校验，拒绝路径穿越（../）。Python 侧只读不写。
"""

from __future__ import annotations

import asyncio

from minio import Minio

from app.core.config import Settings
from app.core.errors import CODE_PARSE_FAILED, ExternalServiceError
from app.utils.text import is_safe_object_key


class MinioClient:
    """只读 MinIO 封装。"""

    def __init__(self, settings: Settings) -> None:
        self._client = Minio(
            settings.minio_endpoint,
            access_key=settings.minio_access_key,
            secret_key=settings.minio_secret_key,
            secure=settings.minio_secure,
        )
        self._bucket = settings.minio_bucket

    async def get_object_bytes(self, object_key: str) -> bytes:
        """读取对象全部字节。非法 key 直接拒绝。"""
        if not is_safe_object_key(object_key):
            raise ExternalServiceError(
                CODE_PARSE_FAILED, f"非法 objectKey：{object_key}"
            )
        return await asyncio.to_thread(self._read, object_key)

    def _read(self, object_key: str) -> bytes:
        response = None
        try:
            response = self._client.get_object(self._bucket, object_key)
            return response.read()
        finally:
            if response is not None:
                response.close()
                response.release_conn()
