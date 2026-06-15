"""OmniMind AI 服务（FastAPI）。

职责边界：文档解析 / 切片 / 向量化 / RAG 检索 / 审查·编写 Agent。
仅访问 omnimind_ai schema + Milvus + MinIO（只读源文件），不接触 omnimind_biz、不解析 JWT。
"""

__version__ = "0.1.0"
