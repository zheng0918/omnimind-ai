"""PDF 解析器（PyMuPDF）。仅支持电子版 PDF；加密/扫描件视为失败。"""

from __future__ import annotations

import asyncio

import fitz  # PyMuPDF

from app.core.errors import CODE_PARSE_FAILED, ParseError
from app.schemas.parse import ParsedDocument, ParsedParagraph
from app.utils.text import normalize_text

_SCANNED_MSG = "暂不支持扫描件/加密文档"


def _clamp01(value: float) -> float:
    return 0.0 if value < 0.0 else 1.0 if value > 1.0 else value


def _norm_bbox(block: tuple, page_w: float, page_h: float) -> list[float] | None:
    """把 PyMuPDF block 的 (x0,y0,x1,y1) 点坐标归一化到页宽高的 [0,1]；异常则返回 None。"""
    if len(block) < 4:
        return None
    try:
        x0, y0, x1, y1 = float(block[0]), float(block[1]), float(block[2]), float(block[3])
    except (TypeError, ValueError):
        return None
    return [
        _clamp01(x0 / page_w),
        _clamp01(y0 / page_h),
        _clamp01(x1 / page_w),
        _clamp01(y1 / page_h),
    ]


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
                page_w = page.rect.width or 1.0
                page_h = page.rect.height or 1.0
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
                            # block[0:4]=(x0,y0,x1,y1) 点坐标(左上原点)，归一化到 [0,1]。
                            bbox=_norm_bbox(block, page_w, page_h),
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
