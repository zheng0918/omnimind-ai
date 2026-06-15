"""解析器注册表。按 MIME 类型选择解析器；注册即生效。"""

from __future__ import annotations

from app.core.errors import CODE_PARSE_FAILED, ParseError
from app.parsers.base import DocumentParser
from app.parsers.docx import DocxParser
from app.parsers.pdf import PyMuPDFParser
from app.parsers.xlsx import XlsxParser

_PARSERS: tuple[DocumentParser, ...] = (PyMuPDFParser(), DocxParser(), XlsxParser())

_REGISTRY: dict[str, DocumentParser] = {
    mime: parser for parser in _PARSERS for mime in parser.supported_mime_types
}


def get_parser(mime_type: str) -> DocumentParser:
    """按 MIME 类型取解析器；不支持则抛 ParseError。"""
    parser = _REGISTRY.get(mime_type)
    if parser is None:
        raise ParseError(CODE_PARSE_FAILED, f"暂不支持的文档类型：{mime_type}")
    return parser
