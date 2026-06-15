"""回 Java 的内部回调客户端。

解析完成后回调 `POST {javaBase}/internal/documents/{documentId}/parse-done`。
携带共享密钥 X-Internal-Token 与链路 X-Trace-Id；body 一律 camelCase。
失败做有限重试（瞬时网络/5xx）。
"""

from __future__ import annotations

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.core.config import Settings
from app.core.trace import TRACE_HEADER, get_trace_id

_RETRIABLE = (httpx.TransportError, httpx.HTTPStatusError)


class JavaCallbackClient:
    """Python → Java 内部回调。复用进程级 httpx 客户端。"""

    def __init__(self, client: httpx.AsyncClient, settings: Settings) -> None:
        self._client = client
        self._base_url = settings.java_base_url.rstrip("/")
        self._token = settings.java_internal_token

    @retry(
        retry=retry_if_exception_type(_RETRIABLE),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=0.5, max=4),
        reraise=True,
    )
    async def notify_parse_done(
        self,
        document_id: int,
        *,
        status: str,
        page_count: int | None = None,
        chunk_count: int | None = None,
        error_msg: str | None = None,
    ) -> None:
        """回调解析结果。status ∈ {PARSED, FAILED}。"""
        url = f"{self._base_url}/internal/documents/{document_id}/parse-done"
        body = {
            "documentId": document_id,
            "status": status,
            "pageCount": page_count,
            "chunkCount": chunk_count,
            "errorMsg": error_msg,
        }
        headers = {TRACE_HEADER: get_trace_id(), "X-Internal-Token": self._token}
        resp = await self._client.post(url, json=body, headers=headers)
        resp.raise_for_status()
