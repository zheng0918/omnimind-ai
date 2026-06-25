"""解析器注册表。按 MIME 类型选择解析器；注册即生效。"""

from __future__ import annotations

import os

from app.core.errors import CODE_PARSE_FAILED, ParseError
from app.parsers.base import DocumentParser
from app.parsers.docx import DocxParser
from app.parsers.pdf import PyMuPDFParser
from app.parsers.xlsx import XlsxParser

_PARSERS: tuple[DocumentParser, ...] = (PyMuPDFParser(), DocxParser(), XlsxParser())

_REGISTRY: dict[str, DocumentParser] = {
    mime: parser for parser in _PARSERS for mime in parser.supported_mime_types
}

# 扩展名兜底：上传方有时只给通用 MIME（如 application/octet-stream），
# 此时按文件后缀回退到对应 MIME 再查注册表。
_EXTENSION_MIME: dict[str, str] = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}


def get_parser(mime_type: str, key: str | None = None) -> DocumentParser:
    """按 MIME 类型取解析器；MIME 未命中时按 key 的扩展名兜底；仍不支持则抛 ParseError。"""
    parser = _REGISTRY.get(mime_type)
    if parser is None and key:
        ext = os.path.splitext(key)[1].lower()
        fallback_mime = _EXTENSION_MIME.get(ext)
        if fallback_mime is not None:
            parser = _REGISTRY.get(fallback_mime)
    if parser is None:
        raise ParseError(CODE_PARSE_FAILED, f"暂不支持的文档类型：{mime_type}")
    return parser
