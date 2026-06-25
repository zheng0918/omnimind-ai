# OmniMind AI 初始化（PG + Milvus）。Windows 本地用。
# 在项目根目录执行：  .\deploy\init.ps1   [-Recreate]
# 前置：.env 已配置 DATABASE_URL / MILVUS_* / DASHSCOPE_*；依赖已安装（pip install -e .）。
param([switch]$Recreate)

$ErrorActionPreference = "Stop"

Write-Host "==> [1/2] 应用 PG 迁移 (alembic upgrade head)"
alembic upgrade head
if ($LASTEXITCODE -ne 0) { Write-Error "alembic 迁移失败"; exit 1 }

Write-Host "==> [2/2] 初始化 Milvus collection"
if ($Recreate) {
    python deploy/init_milvus.py --recreate
} else {
    python deploy/init_milvus.py
}
if ($LASTEXITCODE -ne 0) { Write-Error "Milvus 初始化失败"; exit 1 }

Write-Host "==> 初始化完成"
