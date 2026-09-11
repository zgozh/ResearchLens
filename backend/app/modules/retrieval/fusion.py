"""M07 — 多路融合（REFACTOR_SPEC §5.6）。

RRF：score(d) = Σ_lists 1 / (K + rank_in_list(d))，**K=60**（常数）。
参数化约束：各路默认取 30、总候选上限 60、重排最多 12 候选。

去重要点：同一 chunk 在两路都出现只累加 RRF 分，不产生两条 hit；
跨块引文由 ``block_ids`` 表达多个 spans，**不允许因 overlap 重复计为多份独立证据**。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

RRF_K = 60
PER_LIST_LIMIT = 30
TOTAL_CANDIDATES = 60
MAX_RERANK = 12

#: 各路的相对权重；词法在无向量时是唯一依赖，故权重更高。
DEFAULT_WEIGHTS = {"lexical": 1.0, "vector": 1.0, "rerank": 1.0}


@dataclass
class FusedCandidate:
    chunk_id: str
    rrf_score: float = 0.0
    lexical_score: Optional[float] = None
    vector_score: Optional[float] = None
    rerank_score: Optional[float] = None
    #: 该 chunk 在各路中的最好名次（1-based），用于稳定排序
    best_rank: int = 1 << 30
    sources: List[str] = field(default_factory=list)


def rrf_fuse(
    lists: Sequence[Tuple[str, Sequence[Tuple[str, float]]]],
    *,
    k: int = RRF_K,
    per_list_limit: int = PER_LIST_LIMIT,
    total_limit: int = TOTAL_CANDIDATES,
    weights: Optional[Dict[str, float]] = None,
) -> List[FusedCandidate]:
    """把多路 ``(channel_name, [(chunk_id, score), ...])`` 融合成候选表。

    返回按 RRF 分降序、最多 ``total_limit`` 条；同分时按最佳名次、再按 chunk_id
    升序，保证**结果稳定可复现**（同输入必得同序）。
    """
    weights = weights or DEFAULT_WEIGHTS
    acc: Dict[str, FusedCandidate] = {}

    for name, ranked in lists:
        weight = float(weights.get(name, 1.0))
        if weight <= 0.0:
            continue
        for idx, (chunk_id, score) in enumerate(list(ranked)[:per_list_limit]):
            rank = idx + 1
            cand = acc.get(chunk_id)
            if cand is None:
                cand = FusedCandidate(chunk_id=chunk_id)
                acc[chunk_id] = cand
            cand.rrf_score += weight / (k + rank)
            cand.best_rank = min(cand.best_rank, rank)
            if name not in cand.sources:
                cand.sources.append(name)
            _attach_score(cand, name, score)

    ordered = sorted(acc.values(), key=lambda c: (-c.rrf_score, c.best_rank, c.chunk_id))
    return ordered[:total_limit]


def _attach_score(cand: FusedCandidate, name: str, score: float) -> None:
    if name == "lexical":
        cand.lexical_score = score if cand.lexical_score is None else max(cand.lexical_score, score)
    elif name == "vector":
        cand.vector_score = score if cand.vector_score is None else max(cand.vector_score, score)
    elif name == "rerank":
        cand.rerank_score = score if cand.rerank_score is None else max(cand.rerank_score, score)


def order_with_rerank(
    candidates: Sequence[FusedCandidate],
    max_rerank: int = MAX_RERANK,
) -> List[FusedCandidate]:
    """重排后排序：有 rerank_score 的按它降序排在前，其余保持 RRF 序。"""
    if not candidates:
        return []
    head = [c for c in candidates[:max_rerank] if c.rerank_score is not None]
    if not head:
        return list(candidates)
    head_sorted = sorted(head, key=lambda c: (-(c.rerank_score or 0.0), c.best_rank, c.chunk_id))
    rest = [c for c in candidates if c.rerank_score is None]
    return head_sorted + rest


def truncate_by_tokens(
    candidates: Sequence[FusedCandidate],
    token_of: Dict[str, int],
    budget: int,
) -> List[FusedCandidate]:
    """按上下文 token 预算截断；至少保留 1 条，避免预算过紧时返回空。"""
    if budget <= 0:
        return list(candidates[:1])
    out: List[FusedCandidate] = []
    used = 0
    for cand in candidates:
        cost = int(token_of.get(cand.chunk_id, 0))
        if out and used + cost > budget:
            break
        out.append(cand)
        used += cost
    return out


__all__ = [
    "RRF_K",
    "PER_LIST_LIMIT",
    "TOTAL_CANDIDATES",
    "MAX_RERANK",
    "FusedCandidate",
    "rrf_fuse",
    "order_with_rerank",
    "truncate_by_tokens",
]
