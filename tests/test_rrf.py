"""RRF 融合纯逻辑单测（retriever.rrf_fuse）。"""

from __future__ import annotations

from app.rag.retriever import rrf_fuse


def test_rrf_empty_lists() -> None:
    assert rrf_fuse([], k=60) == []
    assert rrf_fuse([[], []], k=60) == []


def test_rrf_dedup_and_order() -> None:
    # 同一 id 出现在两个列表的高位，应排到最前。
    fused = rrf_fuse([[1, 2, 3], [2, 1, 4]], k=60)
    assert set(fused) == {1, 2, 3, 4}
    assert fused[0] in {1, 2}
    assert len(fused) == len(set(fused))


def test_rrf_rank_weighting() -> None:
    # 仅靠前排名贡献更高分数：单列表时顺序保持。
    assert rrf_fuse([[10, 20, 30]], k=60) == [10, 20, 30]


def test_rrf_consensus_beats_single_top() -> None:
    # id=5 在两个列表都靠前（rank2+rank2），id=9 仅在一个列表 rank1。
    fused = rrf_fuse([[9, 5, 1], [2, 5, 3]], k=1)
    assert fused[0] == 5
