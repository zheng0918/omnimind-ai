"""文本规范化与安全校验工具。"""

from __future__ import annotations

import re
import unicodedata

# MinIO object_key 白名单字符（spec §17 安全基线：禁止路径遍历）。
_OBJECT_KEY_PATTERN = re.compile(r"^[A-Za-z0-9/_\-.]+$")

# 敏感信息脱敏（finalRequirements §CHAT：手机/身份证/邮箱 → 标注"已脱敏"）。
_MOBILE_PATTERN = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")
_ID_CARD_PATTERN = re.compile(r"(?<!\d)\d{17}[\dXx](?!\d)")
_EMAIL_PATTERN = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
_DESENSITIZED_TAG = "[已脱敏]"
# 流式脱敏保留的尾部字符数：足以容纳一个完整身份证（18 位）跨 token 边界的情况。
_SANITIZER_HOLDBACK = 24


def desensitize(text: str) -> str:
    """对手机号 / 身份证 / 邮箱做脱敏，替换为统一标注。

    身份证先于手机号匹配，避免 18 位号码被误判为手机号片段。
    """
    if not text:
        return text
    text = _EMAIL_PATTERN.sub(_DESENSITIZED_TAG, text)
    text = _ID_CARD_PATTERN.sub(_DESENSITIZED_TAG, text)
    return _MOBILE_PATTERN.sub(_DESENSITIZED_TAG, text)


class StreamingDesensitizer:
    """流式脱敏缓冲：对增量 token 累积去敏，保留尾部以防敏感串跨 token 截断。

    `feed` 返回可安全下发的已脱敏前缀，`flush` 返回结尾残留。
    `full_text` 为累计的完整已脱敏文本（用于落库与引用抽取）。
    """

    def __init__(self) -> None:
        self._buffer = ""
        self._emitted = ""

    @property
    def full_text(self) -> str:
        """已下发 + 待下发的完整脱敏文本。"""
        return self._emitted + desensitize(self._buffer)

    def feed(self, delta: str) -> str:
        """喂入增量，返回本次可安全下发的已脱敏文本。"""
        self._buffer += delta
        if len(self._buffer) <= _SANITIZER_HOLDBACK:
            return ""
        cut = len(self._buffer) - _SANITIZER_HOLDBACK
        safe = desensitize(self._buffer[:cut])
        self._buffer = self._buffer[cut:]
        self._emitted += safe
        return safe

    def flush(self) -> str:
        """流结束时返回剩余的已脱敏文本。"""
        tail = desensitize(self._buffer)
        self._buffer = ""
        self._emitted += tail
        return tail


def normalize_text(text: str) -> str:
    """统一 Unicode 形式并压缩多余空白，保证切片/向量化输入一致。"""
    if not text:
        return ""
    normalized = unicodedata.normalize("NFKC", text)
    # 合并连续空白为单个空格，但保留换行（章节结构信息）。
    normalized = re.sub(r"[ \t\f\v]+", " ", normalized)
    return normalized.strip()


def is_safe_object_key(object_key: str) -> bool:
    """校验 MinIO object_key 是否合法（白名单字符 + 禁止 `..`）。

    防止路径遍历：拒绝包含 `..` 或非白名单字符的 key。
    """
    if not object_key or ".." in object_key:
        return False
    return bool(_OBJECT_KEY_PATTERN.match(object_key))
