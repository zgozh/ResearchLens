"""M08 — graph 私有持久化访问（REFACTOR_SPEC §6.10）。

图的持久化用 ``artifact_blobs`` 的 ``kind='graph'`` 整版覆盖：节点/边一次写入，
读取时整版取出。不新增表，避免迁移，也保证「GET 不写库」的语义单纯。
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.artifacts import ArtifactBlobORM
from app.models.evidence import BindingORM, ClaimRecordORM, EvidenceRowORM

GRAPH_KIND = "graph"


def get_graph_blob(db: Session, revision_id: str) -> Optional[Dict]:
    stmt = select(ArtifactBlobORM).where(
        ArtifactBlobORM.revision_id == revision_id,
        ArtifactBlobORM.kind == GRAPH_KIND,
    )
    row = db.execute(stmt).scalars().first()
    if row is None:
        return None
    payload = row.payload
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except ValueError:
            return None
    return dict(payload or {})


def put_graph_blob(
    db: Session,
    *,
    blob_id: str,
    paper_id: int,
    revision_id: str,
    payload: Dict,
    digest: str,
) -> None:
    stmt = select(ArtifactBlobORM).where(
        ArtifactBlobORM.revision_id == revision_id,
        ArtifactBlobORM.kind == GRAPH_KIND,
    )
    row = db.execute(stmt).scalars().first()
    if row is not None:
        row.payload = payload
        row.digest = digest
        row.paper_id = paper_id
        return
    db.add(ArtifactBlobORM(
        id=blob_id,
        paper_id=paper_id,
        revision_id=revision_id,
        kind=GRAPH_KIND,
        payload=payload,
        digest=digest,
    ))


@dataclass(frozen=True)
class BindingSnapshot:
    """绑定的**冻结快照**：离开 Session 后仍可安全读取。

    ORM 实例在 session 关闭后属性会过期（DetachedInstanceError），
    因此读取层一律投影成不可变快照再返回给 service。
    """

    id: str
    from_kind: str
    from_id: str
    to_kind: str
    to_id: str
    relation: str
    state: str
    method: str


@dataclass(frozen=True)
class EvidenceSnapshot:
    id: str
    anchor_id: str
    source_text: str
    support_status: str
    source_page: int


def binding_snapshots(db: Session, revision_id: str, from_kind: str) -> List[BindingSnapshot]:
    return [
        BindingSnapshot(
            id=row.id,
            from_kind=row.from_kind or "",
            from_id=row.from_id or "",
            to_kind=row.to_kind or "",
            to_id=row.to_id or "",
            relation=row.relation or "supports",
            state=row.state or "candidate",
            method=row.method or "",
        )
        for row in list_bindings_for(db, revision_id, from_kind)
    ]


@dataclass(frozen=True)
class ClaimRow:
    id: str
    claim_id: str
    statement_id: str
    type: str
    status: str
    rationale: str
    evidence_ids: List[str]
    confidence: Optional[float]
    visibility: str


def list_claims(db: Session, revision_id: str) -> List[ClaimRow]:
    stmt = (
        select(ClaimRecordORM)
        .where(ClaimRecordORM.revision_id == revision_id)
        .order_by(ClaimRecordORM.claim_id)
    )
    return [
        ClaimRow(
            id=row.id,
            claim_id=row.claim_id or "",
            statement_id=row.statement_id or "",
            type=row.type or "RESULT",
            status=row.status or "unverified",
            rationale=row.rationale or "",
            evidence_ids=list(row.evidence_ids or []),
            confidence=row.confidence,
            visibility=row.visibility or "exhibit",
        )
        for row in db.execute(stmt).scalars().all()
    ]


@dataclass(frozen=True)
class MediaSnapshot:
    """媒体的**冻结快照**（图节点标签用），离开 Session 后仍可读。"""

    id: str
    kind: str
    label: str
    legacy_no: Optional[int]


def list_media(db: Session, revision_id: str, ids: Sequence[str]) -> List[MediaSnapshot]:
    """按 id 读取媒体快照；**只读**，不存在的不伪造。"""
    from app.models.artifacts import MediaORM

    wanted = [str(i) for i in (ids or []) if i]
    if not wanted:
        return []
    stmt = select(MediaORM).where(
        MediaORM.revision_id == revision_id,
        MediaORM.id.in_(wanted),
    )
    return [
        MediaSnapshot(
            id=row.id,
            kind=row.kind or "figure",
            label=(row.caption or row.original_label or "").strip(),
            legacy_no=row.legacy_no,
        )
        for row in db.execute(stmt).scalars().all()
    ]


def list_bindings_for(db: Session, revision_id: str, from_kind: str) -> List[BindingORM]:
    stmt = select(BindingORM).where(
        BindingORM.revision_id == revision_id,
        BindingORM.from_kind == from_kind,
    )
    return list(db.execute(stmt).scalars().all())


def list_evidence(db: Session, revision_id: str, ids: List[str]) -> List[EvidenceSnapshot]:
    """证据**冻结快照**（离开 Session 后仍可读）。"""
    if not ids:
        return []
    stmt = select(EvidenceRowORM).where(
        EvidenceRowORM.revision_id == revision_id,
        EvidenceRowORM.id.in_(ids),
    )
    return [
        EvidenceSnapshot(
            id=row.id,
            anchor_id=row.anchor_id or "",
            source_text=row.source_text or "",
            support_status=row.support_status or "unreviewed",
            source_page=int(row.source_page or 1),
        )
        for row in db.execute(stmt).scalars().all()
    ]


def paper_exists(db: Session, paper_id: int) -> bool:
    from app.models.source import RevisionORM

    stmt = select(RevisionORM.id).where(RevisionORM.paper_id == paper_id).limit(1)
    return db.execute(stmt).first() is not None


__all__ = [
    "GRAPH_KIND",
    "BindingSnapshot",
    "EvidenceSnapshot",
    "ClaimRow",
    "get_graph_blob",
    "put_graph_blob",
    "list_claims",
    "list_bindings_for",
    "binding_snapshots",
    "list_evidence",
    "paper_exists",
]
