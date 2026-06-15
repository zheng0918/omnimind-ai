"""ORM 模型聚合。

导入所有模型以保证 `Base.metadata` 在 alembic autogenerate 时包含全部表。
"""

from __future__ import annotations

from app.models.base import Base
from app.models.chat import ChatMessage, ChatSession
from app.models.chunk import Chunk
from app.models.parse_task import ParseTask
from app.models.review import ReviewRisk, ReviewTask
from app.models.write import (
    WriteOutlineNode,
    WriteScorePoint,
    WriteSection,
    WriteTask,
)

__all__ = [
    "Base",
    "ChatMessage",
    "ChatSession",
    "Chunk",
    "ParseTask",
    "ReviewRisk",
    "ReviewTask",
    "WriteOutlineNode",
    "WriteScorePoint",
    "WriteSection",
    "WriteTask",
]
