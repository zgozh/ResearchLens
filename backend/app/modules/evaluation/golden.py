"""M12 — 人工真值集（REFACTOR_SPEC §5.9、§6.14）。

golden 提供**可测分母**，使 support_precision / support_recall /
unanswerable_refusal_rate 从 proxy 升级为 measured。

关键纪律：
- 候选与 golden 必须**一对一**匹配（``one_to_one_match``），
  防止一份预测匹配多个 gold 造成指标虚高（旧 benchmark 的真实缺陷）；
- ``is_tuning`` 的集合不用于对外报告（只在调参时使用）。
"""
from __future__ import annotations

import json
from typing import Dict, List, Optional, Sequence, Tuple

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.contracts.evaluation import (
    GoldenClaim,
    GoldenQuestion,
    GoldenSet,
    MetricEntry,
    not_evaluated,
)
from app.models.audit import GoldenSetORM

from . import metrics as M


# --------------------------------------------------------------- 持久化


def load_golden_set(db: Session, golden_id: str, version: Optional[str] = None) -> Optional[GoldenSet]:
    stmt = select(GoldenSetORM).where(GoldenSetORM.golden_id == golden_id)
    if version:
        stmt = stmt.where(GoldenSetORM.version == version)
    stmt = stmt.order_by(GoldenSetORM.created_at.desc()).limit(1)
    row = db.execute(stmt).scalars().first()
    if row is None:
        return None
    payload = row.payload
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except ValueError:
            return None
    try:
        return GoldenSet.model_validate(payload)
    except Exception:  # noqa: BLE001  脏 payload 视为不可用
        return None


def save_golden_set(db: Session, golden: GoldenSet, *, blob_id: str,
                    is_tuning: bool = False) -> None:
    stmt = select(GoldenSetORM).where(
        GoldenSetORM.golden_id == golden.id,
        GoldenSetORM.version == golden.version,
    )
    existing = db.execute(stmt).scalars().first()
    payload = golden.model_dump(mode="json")
    if existing is not None:
        existing.payload = payload
        existing.is_tuning = is_tuning
        return
    db.add(GoldenSetORM(
        id=blob_id,
        golden_id=golden.id,
        version=golden.version,
        payload=payload,
        is_tuning=is_tuning,
    ))


# --------------------------------------------------------------- 比对


def support_precision_recall(
    predicted_texts: Sequence[str],
    golden_claims: Sequence[GoldenClaim],
    *,
    predicted_ok: Optional[Sequence[bool]] = None,
) -> Tuple[MetricEntry, MetricEntry]:
    """支持精确率/召回率。**一对一匹配**，不使用一对多近似。

    ``predicted_ok[i]`` 表示第 i 条预测是否**在实质上被支持**（有验证通过的证据）。
    未提供时视为全部被支持（仅做匹配口径评估）。
    """
    if not golden_claims:
        return (
            not_evaluated("support_precision", method="无 GoldenClaim 真值", unit="ratio"),
            not_evaluated("support_recall", method="无 GoldenClaim 真值", unit="ratio"),
        )
    if not predicted_texts:
        return (
            not_evaluated("support_precision", method="无预测样本", unit="ratio"),
            M.ratio_entry("support_recall", 0, len(golden_claims),
                          method="matched_golden / all_golden"),
        )

    prediction_of_golden: List[Optional[int]] = [None] * len(golden_claims)
    golden_of_prediction: List[Optional[int]] = [None] * len(predicted_texts)
    pairs: List[Tuple[float, int, int]] = []
    for pi, ptext in enumerate(predicted_texts):
        for gi, gc in enumerate(golden_claims):
            score = M.similarity(ptext, gc.text)
            if score >= M.SIM_THRESHOLD:
                pairs.append((score, pi, gi))
    pairs.sort(key=lambda t: (-t[0], t[1], t[2]))
    for _, pi, gi in pairs:
        if golden_of_prediction[pi] is not None or prediction_of_golden[gi] is not None:
            continue
        golden_of_prediction[pi] = gi
        prediction_of_golden[gi] = pi

    if predicted_ok is None:
        predicted_ok = [True] * len(predicted_texts)

    tp = sum(
        1 for pi, gi in enumerate(golden_of_prediction)
        if gi is not None and predicted_ok[pi]
    )
    # 精确率分母 = 全部预测条目（含未被支持者）→ 未被支持的预测会拉低精确率
    precision = M.ratio_entry(
        "support_precision", tp, len(predicted_texts),
        method="one_to_one_matched_and_supported / all_predictions",
    )
    recall = M.ratio_entry(
        "support_recall", tp, len(golden_claims),
        method="one_to_one_matched / all_golden_claims",
    )
    return precision, recall


def question_golden_index(golden: Optional[GoldenSet]) -> Dict[str, GoldenQuestion]:
    if golden is None:
        return {}
    return {q.id: q for q in golden.questions}


def claim_golden_index(golden: Optional[GoldenSet]) -> Dict[str, GoldenClaim]:
    if golden is None:
        return {}
    return {c.id: c for c in golden.claims}


def golden_scope_ok(golden: Optional[GoldenSet], paper_id: int, revision_id: str) -> bool:
    """真值集合必须与 scope 同源，否则不可用于该论文的指标。"""
    if golden is None:
        return False
    for item in list(golden.claims) + list(golden.questions) + list(golden.anchors):
        scope = getattr(item, "scope", None)
        if scope is None:
            continue
        if scope.paper_id != paper_id or scope.revision_id != revision_id:
            return False
    return True


__all__ = [
    "load_golden_set",
    "save_golden_set",
    "support_precision_recall",
    "question_golden_index",
    "claim_golden_index",
    "golden_scope_ok",
]
