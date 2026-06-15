"""文档解析器抽象（Protocol）。

一期：PyMuPDF / Docx / Xlsx；注册即生效（未来可挂 MinerU/PaddleOCR）。
解析器统一输出结构化段落 [{text,page,paragraphId,charOffset}]，CPU 密集的解析
逻辑由实现放入线程池，避免阻塞事件循环。
"""

from __future__ import annotations

from typing import Protocol

from app.schemas.parse import ParsedDocument


class DocumentParser(Protocol):
    """文档解析协议。"""

    @property
    def supported_mime_types(self) -> tuple[str, ...]:
        """支持的 MIME 类型集合，用于注册表匹配。"""
        ...

    async def parse(self, data: bytes) -> ParsedDocument:
        """把原文字节解析为结构化文档。失败抛 ParseError。"""
        ...
