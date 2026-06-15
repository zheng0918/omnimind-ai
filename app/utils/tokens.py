"""Token 计数工具（tiktoken cl100k_base）。

切片父子块按 token 数控制大小（spec §13.3）。encoder 进程内缓存复用，
避免每次调用重新加载。
"""

from __future__ import annotations

from functools import lru_cache

import tiktoken

# spec 指定使用 cl100k_base 编码做 token 计数。
_ENCODING_NAME = "cl100k_base"


@lru_cache
def _get_encoder() -> tiktoken.Encoding:
    """返回缓存的 tiktoken 编码器单例。"""
    return tiktoken.get_encoding(_ENCODING_NAME)


def count_tokens(text: str) -> int:
    """统计文本 token 数。"""
    if not text:
        return 0
    return len(_get_encoder().encode(text))


def truncate_to_tokens(text: str, max_tokens: int) -> str:
    """将文本截断到不超过 max_tokens 个 token。

    用于上下文装配时控制总长度（spec §10.2 上下文 token 上限）。
    """
    if max_tokens <= 0:
        return ""
    encoder = _get_encoder()
    token_ids = encoder.encode(text)
    if len(token_ids) <= max_tokens:
        return text
    return encoder.decode(token_ids[:max_tokens])


def split_by_tokens(text: str, chunk_tokens: int, overlap_tokens: int) -> list[str]:
    """按 token 滑动窗口切分文本（子块切片用，spec §13.3）。

    overlap_tokens 为相邻窗口重叠的 token 数；步长 = chunk_tokens - overlap_tokens。
    """
    if chunk_tokens <= 0:
        return []
    overlap = max(0, min(overlap_tokens, chunk_tokens - 1))
    step = chunk_tokens - overlap
    encoder = _get_encoder()
    token_ids = encoder.encode(text)
    if not token_ids:
        return []
    pieces: list[str] = []
    for start in range(0, len(token_ids), step):
        window = token_ids[start : start + chunk_tokens]
        if not window:
            break
        pieces.append(encoder.decode(window))
        if start + chunk_tokens >= len(token_ids):
            break
    return pieces
