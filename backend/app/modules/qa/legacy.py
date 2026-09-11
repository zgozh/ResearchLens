"""M10 — 旧 HTTP 兼容适配（REFACTOR_SPEC §5.11）。

``api/routes.py`` 仍以 ``answer_question(db, paper_id, question, top_k)`` 调用本包，
返回 ``AskResponse``。本模块把旧 ``Session`` 用法翻译成 canonical ``answer()``，
再投影为 ``AskResponse``：

- **非流式与流式共用同一服务与同一 gate**；
- 旧 top_k 越界由服务层 clamp 并记 warning，不返回 422；
- 拒答也是 200，且 ``grounded=False``；**绝不按措辞判 grounded**。
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy.orm import Session

from app.contracts.common import CallContext, Scope
from app.contracts.qa import AnswerRecord, QARequest
from app.schemas.schemas import AskResponse

from . import repository as repo
from . import service as svc


def answer_question(
    db: Session,
    paper_id: int,
    question: str,
    top_k: int = 5,
) -> AskResponse:
    """旧签名：返回 ``AskResponse``；无证据时为带标记的拒答（仍 200）。"""
    resolved = _resolve_scope(db, paper_id)
    if resolved is None:
        # 论文不存在或没有 revision：明确拒答，不编造页码证据
        return AskResponse(
            answer="",
            grounded=False,
            confidence="Low",
            evidence=[],
            note="论文不存在或尚无可用 revision。",
        )

    scope, snapshot_id = resolved
    ctx = _legacy_ctx(scope, snapshot_id)
    record = svc.answer(
        scope,
        QARequest(question=(question or "").strip()[:2000], top_k=top_k),
        ctx,
    )
    return to_legacy_answer(record)


def to_legacy_answer(record: AnswerRecord) -> AskResponse:
    """``AnswerRecord → AskResponse``：字段保持，证据不虚构。"""
    return AskResponse(
        answer=record.text.text if record.text else "",
        grounded=record.grounded,
        confidence=record.confidence,
        evidence=[
            {
                "id": ev.legacy_id,
                "page": ev.source_page,
                "region": (ev.source_region[0].block_id if ev.source_region else ""),
                "region_type": "text",
                "text": ev.source_text,
                "quote": "".join(sp.source_text or "" for sp in (ev.quote_spans or [])),
                "confidence": (ev.confidence if ev.confidence is not None else 0.0),
            }
            for ev in record.evidence
        ],
        note=record.note,
    )


def _resolve_scope(db: Session, paper_id: int):
    found = repo.paper_revision(db, paper_id)
    if found is None:
        return None
    revision_id, snapshot_id = found
    return Scope(paper_id=paper_id, revision_id=revision_id), snapshot_id


def _legacy_ctx(scope: Scope, snapshot_id: Optional[str]) -> Optional[CallContext]:
    """旧入口没有 CallContext：留空即可，服务层会走降级路径。"""
    return None


__all__ = ["answer_question", "to_legacy_answer"]
