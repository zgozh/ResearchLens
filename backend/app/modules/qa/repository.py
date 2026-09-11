"""M10 — qa 私有持久化访问（REFACTOR_SPEC §6.12）。

缓存 key 必须包含 **source/revision/model/prompt/gate** 版本；
只有同 revision 且 gate 版本有效才可复用，否则视为 miss。
"""
from __future__ import annotations

import hashlib
import json
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.evidence import AnswerORM

#: 答案门（gate）语义版本：gate 规则变化必须 bump，使旧缓存自动失效
GATE_VERSION = "rl.gate/2"
#: 答案生成 prompt 版本
PROMPT_VERSION = "rl.qa.prompt/2"


def cache_key(
    *,
    revision_id: str,
    question: str,
    model_snapshot_id: Optional[str],
    top_k: int,
    source_digest: str = "",
    prompt_version: str = PROMPT_VERSION,
    gate_version: str = GATE_VERSION,
) -> str:
    """确定性缓存键：任一版本变化都会得到新键，旧缓存自然不再命中。"""
    raw = json.dumps(
        {
            "revision_id": revision_id,
            "q": _normalize_question(question),
            "model": model_snapshot_id or "",
            "top_k": int(top_k),
            "source": source_digest or "",
            "prompt": prompt_version,
            "gate": gate_version,
        },
        sort_keys=True, ensure_ascii=False,
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:96]


def _normalize_question(question: str) -> str:
    return " ".join((question or "").split()).lower()


def find_cached(db: Session, revision_id: str, key: str) -> Optional[AnswerORM]:
    stmt = (
        select(AnswerORM)
        .where(AnswerORM.revision_id == revision_id, AnswerORM.cache_key == key)
        .order_by(AnswerORM.created_at.desc())
        .limit(1)
    )
    return db.execute(stmt).scalars().first()


def insert_answer(
    db: Session,
    *,
    answer_id: str,
    paper_id: int,
    revision_id: str,
    question: str,
    payload: dict,
    cache_key_value: Optional[str],
) -> None:
    db.add(AnswerORM(
        id=answer_id,
        paper_id=paper_id,
        revision_id=revision_id,
        question=question,
        text=payload.get("text", {}),
        statements=payload.get("statements", []),
        evidence=payload.get("evidence", []),
        grounded=bool(payload.get("grounded", False)),
        confidence=payload.get("confidence", "Low"),
        note=payload.get("note", ""),
        mode=payload.get("mode", "generated"),
        model_snapshot_id=payload.get("model_snapshot_id"),
        usage=payload.get("usage", {}),
        warnings=payload.get("warnings", []),
        cache_key=cache_key_value,
    ))
    db.flush()


def get_answer(db: Session, answer_id: str) -> Optional[AnswerORM]:
    return db.get(AnswerORM, answer_id)


def list_answers(db: Session, revision_id: str) -> List[AnswerORM]:
    stmt = (
        select(AnswerORM)
        .where(AnswerORM.revision_id == revision_id)
        .order_by(AnswerORM.created_at)
    )
    return list(db.execute(stmt).scalars().all())


def revision_source_digest(db: Session, revision_id: str) -> str:
    """取 revision 的产物 digest，作为缓存 key 的 source 分量。"""
    from app.models.source import RevisionORM

    row = db.get(RevisionORM, revision_id)
    if row is None:
        return ""
    return row.artifact_digest or ""


def paper_revision(db: Session, paper_id: int) -> Optional[tuple]:
    """旧 HTTP 入口用：取该论文的可读 revision，返回 ``(revision_id, snapshot_id)``。"""
    from app.models.models import Paper
    from app.models.source import RevisionORM

    paper = db.get(Paper, paper_id)
    if paper is None:
        return None
    revision_id = paper.readable_revision_id
    if revision_id:
        row = db.get(RevisionORM, revision_id)
        if row is not None:
            return revision_id, row.model_snapshot_id
    stmt = (
        select(RevisionORM)
        .where(RevisionORM.paper_id == paper_id)
        .order_by(RevisionORM.created_at.desc())
        .limit(1)
    )
    row = db.execute(stmt).scalars().first()
    if row is None:
        return None
    return row.id, row.model_snapshot_id


__all__ = [
    "GATE_VERSION",
    "PROMPT_VERSION",
    "cache_key",
    "find_cached",
    "insert_answer",
    "get_answer",
    "list_answers",
    "revision_source_digest",
    "paper_revision",
]
