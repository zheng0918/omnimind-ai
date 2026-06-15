"""内置审查清单（spec §11.2：内置清单 + 招标文件抽取合并）。

一期提供少量通用条目；实际条目以招标文件抽取为主、内置为兜底补充。
每条：id（稳定标识）/ title（要点）/ requirement（判定依据）/ risk_type（缺省类型）。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ChecklistItem:
    """单条审查要点。"""

    id: str
    title: str
    requirement: str
    risk_type: str


_GENERIC: list[ChecklistItem] = [
    ChecklistItem(
        id="builtin-deadline",
        title="投标有效期与递交截止",
        requirement="投标文件是否明确投标有效期，且不短于招标文件要求。",
        risk_type="missing",
    ),
    ChecklistItem(
        id="builtin-bond",
        title="投标保证金",
        requirement="是否按要求提交投标保证金承诺或缴纳凭证。",
        risk_type="missing",
    ),
    ChecklistItem(
        id="builtin-qualification",
        title="资质与业绩",
        requirement="投标人资质等级、类似项目业绩是否满足招标资格要求。",
        risk_type="risk",
    ),
    ChecklistItem(
        id="builtin-signature",
        title="签字盖章与格式",
        requirement="关键页是否签字盖章、文件格式是否符合招标编制要求。",
        risk_type="format",
    ),
]

_CONSTRUCTION: list[ChecklistItem] = [
    ChecklistItem(
        id="builtin-construction-plan",
        title="施工组织设计",
        requirement="是否包含与项目规模匹配的施工组织设计与进度计划。",
        risk_type="missing",
    ),
    ChecklistItem(
        id="builtin-safety",
        title="安全文明施工措施",
        requirement="是否提供安全、文明施工与环境保护措施方案。",
        risk_type="risk",
    ),
]

_REGISTRY: dict[str, list[ChecklistItem]] = {
    "cl-construction": _GENERIC + _CONSTRUCTION,
}


def builtin_checklist(checklist_id: str | None) -> list[ChecklistItem]:
    """按清单 id 取内置条目；未知 id 回退通用清单。"""
    if checklist_id is None:
        return list(_GENERIC)
    return list(_REGISTRY.get(checklist_id, _GENERIC))
