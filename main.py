"""本地开发启动器：以 uvicorn 运行 app.main:app。

生产环境由容器/进程管理器直接运行 `uvicorn app.main:app`，本文件仅为本地便捷入口。
"""

from __future__ import annotations

import uvicorn
from app.core.config import get_settings


def main() -> None:
    """启动开发服务器（reload 仅用于本地）。"""
    settings = get_settings()
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",  # noqa: S104  本地开发监听全部网卡，生产由编排层约束
        port=settings.app_port,
        reload=settings.app_reload,
    )


if __name__ == "__main__":
    main()
