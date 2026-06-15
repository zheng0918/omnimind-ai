"""PDF 解析器（PyMuPDF）。仅支持电子版 PDF；加密/扫描件视为失败。"""

from __future__ import annotations

import asyncio

import fitz  # PyMuPDF

from app.core.errors import CODE_PARSE_FAILED, ParseError
from app.schemas.parse import ParsedDocument, ParsedParagraph
from app.utils.text import normalize_text

_SCANNED_MSG = "暂不支持扫描件/加密文档"


class PyMuPDFParser:
    """电子版 PDF 解析。按页提取文本块为段落。"""

    @property
    def supported_mime_types(self) -> tuple[str, ...]:
        return ("application/pdf",)

    async def parse(self, data: bytes) -> ParsedDocument:
        return await asyncio.to_thread(self._parse_sync, data)

    def _parse_sync(self, data: bytes) -> ParsedDocument:
        try:
            doc = fitz.open(stream=data, filetype="pdf")
        except Exception as exc:  # 损坏/非法 PDF
            raise ParseError(CODE_PARSE_FAILED, _SCANNED_MSG) from exc
        try:
            if doc.needs_pass:  # 加密文档
                raise ParseError(CODE_PARSE_FAILED, _SCANNED_MSG)
            paragraphs: list[ParsedParagraph] = []
            offset = 0
            seq = 0
            for page_index in range(doc.page_count):
                page = doc.load_page(page_index)
                for block in page.get_text("blocks"):
                    raw = block[4] if len(block) > 4 else ""
                    text = normalize_text(raw).strip()
                    if not text:
                        continue
                    paragraphs.append(
                        ParsedParagraph(
                            text=text,
                            page=page_index + 1,
                            paragraph_id=f"p{seq}",
                            char_offset=offset,
                        )
                    )
                    offset += len(text)
                    seq += 1
            page_count = doc.page_count
        finally:
            doc.close()
        # 无任何可提取文本 → 判定扫描件。
        if not paragraphs:
            raise ParseError(CODE_PARSE_FAILED, _SCANNED_MSG)
        return ParsedDocument(paragraphs=paragraphs, page_count=page_count)
