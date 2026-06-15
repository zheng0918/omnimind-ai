"""业务异常体系。

错误码分段（见 interfaceContract.md §四）：
1xxx 通用 / 2xxx 用户 / 3xxx 文件 / 4xxx RAG / 5xxx 审查 / 6xxx 编写 / 9xxx 系统。
Python 侧主要产生：3005 / 4001 / 4002 / 4003 / 5002 / 6001 / 6003 / 9002 / 9999。
"""

from __future__ import annotations


class BizError(Exception):
    """业务异常基类。

    携带业务错误码与可选的 details，由全局 exception handler 统一转成
    `{code, message, traceId}` 响应。`code < 9000` 视为客户端可纠正错误（HTTP 400），
    否则视为服务端错误（HTTP 500）。
    """

    def __init__(self, code: int, message: str, *, details: dict | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}


class ExternalServiceError(BizError):
    """外部依赖不可用：LLM / Embedding / Rerank / Milvus / MinIO。"""


class ParseError(BizError):
    """文档解析失败（加密、扫描件、损坏等）。"""


class RagError(BizError):
    """RAG 检索 / 生成失败。"""


class ValidationBizError(BizError):
    """schema 之外的业务校验失败（如待审文档内容过少）。"""


# ---- 常用错误码常量（避免散落魔法数字）----
CODE_PARAM_INVALID = 1001
CODE_RESOURCE_NOT_FOUND = 1002
CODE_PARSE_FAILED = 3005
CODE_RAG_RETRIEVE_FAILED = 4001
CODE_LLM_TIMEOUT = 4002
CODE_RAG_SCOPE_EMPTY = 4003
CODE_REVIEW_TASK_NOT_FOUND = 5001
CODE_REVIEW_DOC_TOO_SHORT = 5002
CODE_DISPOSITION_CONFLICT = 5003
CODE_WRITE_TENDER_NOT_PARSED = 6001
CODE_WRITE_DRAFT_INCOMPLETE = 6002
CODE_WRITE_SECTION_FAILED = 6003
CODE_INTERNAL_TOKEN_INVALID = 9002
CODE_UNKNOWN = 9999
