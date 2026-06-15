"""应用配置。

统一使用 pydantic-settings 从 `.env` / 环境变量加载，业务代码禁止散落
`os.environ.get(...)`，一律通过 `get_settings()` 获取单例。
密钥只允许通过环境变量注入，代码内不写明文。
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """全局配置项。字段名对应大写下划线环境变量（pydantic 不区分大小写匹配）。"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ---- 应用本体 ----
    app_port: int = 8000
    app_reload: bool = False

    # ---- 数据库（仅 omnimind_ai schema）----
    database_url: str = "postgresql+asyncpg://ai_rw:placeholder@localhost:5432/omnimind"
    database_schema: str = "omnimind_ai"
    db_pool_size: int = 20
    db_max_overflow: int = 10

    # ---- Milvus ----
    milvus_host: str = "localhost"
    milvus_port: int = 19530
    milvus_collection: str = "omnimind_chunks"
    milvus_timeout_s: int = 15

    # ---- MinIO（只读源文件）----
    minio_endpoint: str = "localhost:9000"
    minio_access_key: str = "placeholder"
    minio_secret_key: str = "placeholder"
    minio_bucket: str = "omnimind-files"
    minio_secure: bool = False

    # ---- DeepSeek（OpenAI 兼容）----
    deepseek_api_key: str = "placeholder"
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-chat"
    deepseek_temperature: float = 0.2
    deepseek_max_tokens: int = 4096
    deepseek_request_timeout_s: int = 60

    # ---- 阿里云百炼 ----
    dashscope_api_key: str = "placeholder"
    dashscope_embed_model: str = "text-embedding-v3"
    dashscope_rerank_model: str = "gte-rerank"
    dashscope_timeout_s: int = 30
    embed_dim: int = 1024
    embed_batch_size: int = 25  # 百炼单批硬上限 25 段
    embed_concurrency: int = 5

    # ---- Agent 并发与超时 ----
    review_parallel: int = 10
    write_parallel: int = 5
    agent_max_retry: int = 2
    agent_step_timeout_s: int = 60

    # ---- Java 回调 ----
    java_base_url: str = "http://localhost:8080"
    java_internal_token: str = "placeholder"
    java_callback_timeout_s: int = 10

    # ---- 内部鉴权（与 Java 网关共享密钥）----
    internal_token: str = "placeholder"

    # ---- Prompt 版本 ----
    prompt_ver: str = "v1"

    # ---- 日志 ----
    log_level: str = "INFO"

    # ---- RAG 检索参数（默认值来自 spec §10.2）----
    rag_dense_top_k: int = 50
    rag_lexical_top_k: int = 50
    rag_rrf_k: int = 60  # RRF 标准常数
    rag_parent_limit: int = 30
    rag_rerank_top_n: int = 8
    rag_context_token_limit: int = 6000
    rag_history_rounds: int = 5

    # ---- 切片参数（spec §13.3）----
    chunk_parent_tokens: int = 1024
    chunk_child_tokens: int = 256
    chunk_overlap_ratio: float = 0.10


@lru_cache
def get_settings() -> Settings:
    """返回进程内单例配置。

    使用 lru_cache 保证只解析一次 `.env`，且便于测试时通过
    `get_settings.cache_clear()` 重置。
    """
    return Settings()
