"""M09 — scene 私有持久化访问（REFACTOR_SPEC §6.11）。

讲解快照用 ``artifact_blobs`` 的 ``kind='presentation'`` 整版覆盖；
读取一次性批量取出，**不每 scene 开 Session**。
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.artifacts import ArtifactBlobORM
from app.models.evidence import BindingORM, ClaimRecordORM, StatementORM

PRESENTATION_KIND = "presentation"


@dataclass(frozen=True)
class ClaimRow:
    """claim 的**冻结快照**（离开 Session 后仍可读）。"""

    id: str
    claim_id: str
    statement_id: str
    type: str
    status: str
    evidence_ids: List[str]


@dataclass(frozen=True)
class StatementRow:
    """陈述的**冻结快照**（离开 Session 后仍可读）。

    ``block_ids`` 是从 ``citations`` 抽出的引用块集合，用于把陈述归入章节
    （章节只有 ``source_block_ids``/``anchor_ids``，没有 claim_ids 字段）。
    """

    id: str
    claim_id: str
    text: str
    kind: str
    display_class: str
    evidence_ids: List[str]
    origin: str
    block_ids: List[str]


@dataclass(frozen=True)
class MediaBindingRow:
    id: str
    from_kind: str
    from_id: str
    to_id: str
    relation: str
    state: str


@dataclass(frozen=True)
class MediaRow:
    id: str
    kind: str
    original_label: Optional[str]
    legacy_no: Optional[int]
    caption: str


def get_presentation_blob(db: Session, revision_id: str) -> Optional[Dict]:
    stmt = select(ArtifactBlobORM).where(
        ArtifactBlobORM.revision_id == revision_id,
        ArtifactBlobORM.kind == PRESENTATION_KIND,
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


def put_presentation_blob(
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
        ArtifactBlobORM.kind == PRESENTATION_KIND,
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
        kind=PRESENTATION_KIND,
        payload=payload,
        digest=digest,
    ))


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
            evidence_ids=list(row.evidence_ids or []),
        )
        for row in db.execute(stmt).scalars().all()
    ]


def list_statements(db: Session, revision_id: str, ids: List[str]) -> List[StatementRow]:
    """一次批量取陈述快照，避免每 scene 单独查询。"""
    if not ids:
        return []
    stmt = select(StatementORM).where(
        StatementORM.revision_id == revision_id,
        StatementORM.id.in_(ids),
    )
    return [
        StatementRow(
            id=row.id,
            claim_id=row.claim_id or "",
            text=row.text or "",
            kind=row.kind or "fact",
            display_class=row.display_class or "unverified",
            evidence_ids=list(row.evidence_ids or []),
            origin=row.origin or "generated",
            block_ids=_citation_block_ids(row.citations),
        )
        for row in db.execute(stmt).scalars().all()
    ]


def _citation_block_ids(citations) -> List[str]:
    """从 ``citations`` 抽取 block_id（容忍 dict / 对象两种历史形态）。"""
    out: List[str] = []
    for cite in (citations or []):
        bid = cite.get("block_id") if isinstance(cite, dict) else getattr(cite, "block_id", None)
        if bid:
            out.append(str(bid))
    return out


def list_media_bindings(db: Session, revision_id: str) -> List[MediaBindingRow]:
    """全部 media 绑定（claim/statement 两种来源），供批量解析。"""
    stmt = select(BindingORM).where(
        BindingORM.revision_id == revision_id,
        BindingORM.to_kind == "media",
    )
    return [
        MediaBindingRow(
            id=row.id,
            from_kind=row.from_kind or "",
            from_id=row.from_id or "",
            to_id=row.to_id or "",
            relation=row.relation or "illustrates",
            state=row.state or "candidate",
        )
        for row in db.execute(stmt).scalars().all()
    ]


def list_media(db: Session, revision_id: str, ids: List[str]) -> List[MediaRow]:
    """读取 Media 快照（用于投影 caption/legacy_no，不写库）。"""
    from app.models.artifacts import MediaORM

    if not ids:
        return []
    stmt = select(MediaORM).where(
        MediaORM.revision_id == revision_id,
        MediaORM.id.in_(ids),
    )
    return [
        MediaRow(
            id=row.id,
            kind=row.kind or "figure",
            original_label=row.original_label,
            legacy_no=row.legacy_no,
            caption=row.caption or "",
        )
        for row in db.execute(stmt).scalars().all()
    ]


def all_media(db: Session, revision_id: str) -> List[MediaRow]:
    """该 revision 的全部媒体快照（旧兼容层投影用）。"""
    from app.models.artifacts import MediaORM

    stmt = select(MediaORM).where(MediaORM.revision_id == revision_id)
    return [_media_row(row) for row in db.execute(stmt).scalars().all()]


def _media_row(row) -> MediaRow:
    return MediaRow(
        id=row.id,
        kind=row.kind or "figure",
        original_label=row.original_label,
        legacy_no=row.legacy_no,
        caption=row.caption or "",
    )


__all__ = [
    "PRESENTATION_KIND",
    "ClaimRow",
    "StatementRow",
    "MediaBindingRow",
    "MediaRow",
    "get_presentation_blob",
    "put_presentation_blob",
    "list_claims",
    "list_statements",
    "list_media_bindings",
    "list_media",
    "all_media",
]

