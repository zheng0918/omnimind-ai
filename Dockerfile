# OmniMind AI 服务镜像（spec 强制 Python 3.11）。
FROM python:3.11-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# 先装依赖（利用层缓存）：仅 copy 构建所需元数据与包目录。
COPY pyproject.toml ./
COPY app ./app
RUN pip install --upgrade pip && pip install .

# 迁移脚本随镜像分发，便于容器内执行 alembic upgrade。
COPY alembic.ini ./
COPY alembic ./alembic

# 以非 root 运行，降低容器逃逸影响面。
RUN useradd --create-home --uid 10001 appuser \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
