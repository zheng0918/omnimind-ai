#!/usr/bin/env bash
# OmniMind AI 初始化（PG + Milvus）。Linux/服务器用。
# 在项目根目录执行：  bash deploy/init.sh   [--recreate]
# 前置：.env 已配置 DATABASE_URL / MILVUS_* / DASHSCOPE_*；依赖已安装（pip install -e .）。
set -euo pipefail

echo "==> [1/2] 应用 PG 迁移 (alembic upgrade head)"
alembic upgrade head

echo "==> [2/2] 初始化 Milvus collection"
python deploy/init_milvus.py "$@"

echo "==> 初始化完成"
