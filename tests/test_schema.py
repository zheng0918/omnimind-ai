"""schema 序列化纯逻辑单测：camelCase 别名与审查阈值。"""

from __future__ import annotations

from app.agents.review_agent import threshold_for
from app.schemas.review import ReviewStatus, ReviewSummary, ReviewTaskOut


def test_review_summary_pass_alias() -> None:
    summary = ReviewSummary(high=1, medium=2, **{"pass": 3})
    dumped = summary.model_dump(by_alias=True)
    assert dumped["pass"] == 3
    assert dumped["high"] == 1
    assert dumped["medium"] == 2


def test_review_task_out_camel_case() -> None:
    out = ReviewTaskOut(
        review_task_id=7, status=ReviewStatus.RUNNING, progress=50,
        total_items=10, done_items=5,
    )
    dumped = out.model_dump(by_alias=True)
    assert dumped["reviewTaskId"] == 7
    assert dumped["totalItems"] == 10
    assert dumped["doneItems"] == 5
    assert dumped["status"] == "RUNNING"


def test_threshold_for_known_and_default() -> None:
    assert threshold_for("LOOSE") == 0.85
    assert threshold_for("BALANCED") == 0.7
    assert threshold_for("STRICT") == 0.5
    # 未知严格度回退 BALANCED。
    assert threshold_for("UNKNOWN") == 0.7
