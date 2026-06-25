"""智能编写相关 schema（REQ-WRT / interfaceContract §1.6 §3.4）。"""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field

from app.schemas.common import CamelModel


class WriteStatus(StrEnum):
    """编写任务状态机（pythonRequirements §3.4）。"""

    EXTRACTING = "EXTRACTING"
    MATCHING = "MATCHING"
    GENERATING = "GENERATING"
    DONE = "DONE"
    FAILED = "FAILED"


class SectionStatus(StrEnum):
    """章节级状态。"""

    PENDING = "PENDING"
    GENERATING = "GENERATING"
    DONE = "DONE"
    USER_EDITED = "USER_EDITED"
    FAILED = "FAILED"


class ResponseStatus(StrEnum):
    """评分点响应度。"""

    NONE = "NONE"
    PARTIAL = "PARTIAL"
    RESPONDED = "RESPONDED"


class ProjectParams(CamelModel):
    """编写时注入章节生成的项目参数（替换历史素材中的占位）。"""

    project_name: str | None = None
    client: str | None = None
    scale: str | None = None
    win_date: str | None = None


class WriteCreateIn(CamelModel):
    """POST /ai/v1/write 入参。"""

    java_task_id: int
    kb_id: int
    tender_doc_id: int
    use_history: bool = True
    project_params: ProjectParams = ProjectParams()


class WriteCreateOut(CamelModel):
    write_task_id: int
    status: WriteStatus


class ScorePointOut(CamelModel):
    point_id: int
    point_text: str
    weight: float | None = None
    response_status: ResponseStatus = ResponseStatus.NONE


class WriteStatusOut(CamelModel):
    """GET /ai/v1/write/{id} 任务状态 + 评分点进度。"""

    write_task_id: int
    status: WriteStatus
    total_sections: int = 0
    done_sections: int = 0
    score_points: list[ScorePointOut] = Field(default_factory=list)


class SectionSaveIn(CamelModel):
    """PUT /ai/v1/write/{id}/sections/{sid} 入参。"""

    content_md: str


class WriteSectionOut(CamelModel):
    """GET /ai/v1/write/{id}/sections/{sid} 出参：章节正文 + 状态（供编辑器加载）。"""

    section_id: int
    title: str | None = None
    content_md: str | None = None
    status: SectionStatus


class ScorePointResponse(CamelModel):
    point_id: int
    response_status: ResponseStatus


class CheckResponseOut(CamelModel):
    """POST /ai/v1/write/{id}/check-response 出参。"""

    score_points: list[ScorePointResponse]


class DraftExportOut(CamelModel):
    """初稿导出（拼接 markdown）供 Java 落 draft document（REQ-LINK-02）。"""

    write_task_id: int
    content_md: str
