"""健康检查（探活）。豁免内网 Token，供容器/网关探测。"""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/health", summary="存活探针")
async def health() -> dict[str, str]:
    """返回服务存活状态。"""
    return {"status": "ok"}
