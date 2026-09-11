"""M06 — claims 私有持久化访问（REFACTOR_SPEC §6.8）。

只做"表 ↔ DTO"的投影与读写，不含业务判断：
- claim/statement 的落库与读取；
- Section/MapItem/MethodStep 生成产物的整版覆盖写；
- 预算内的原文块读取（按章节分配，不只读头尾）。

跨模块不暴露 Session：所有函数都接收调用方传入的 ``db``。
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.contracts.common import Scope
from app.core.errors import revision_mismatch
from app.contracts.evidence import (
    ArtifactText,
    ClaimRecord,
    MapArtifact,
    MapItem,
    MethodStepRecord,
    SectionRecord,
    StatementDraft,
    StructureArtifact,
    VerifiedStatement,
)
from app.models.artifacts import BlockORM, PageORM
from app.models.evidence import (
    ClaimRecordORM,
    MapItemORM,
    MethodStepORM,
    SectionRecordORM,
    StatementORM,
)


# --------------------------------------------------------------- 读取

@dataclass(frozen=True)
class BlockRow:
    """原文块的**冻结快照**：离开 Session 后仍可安全读取。

    ORM 实例在 session 关闭后属性会过期（DetachedInstanceError），
    因此读取层一律投影成不可变快照再返回给 service。
    """

    id: str
    page_id: str
    ordinal: int
    kind: str
    text: str
    anchor_id: Optional[str]
    origin: str


@dataclass(frozen=True)
class StatementRow:
    id: str
    claim_id: str
    text: str
    kind: str
    citations: List[dict]
    qualifiers: List[str]
    evidence_ids: List[str]
    display_class: str
    origin: str
    validation: Optional[dict]


@dataclass(frozen=True)
class ClaimRow:
    id: str
    legacy_id: Optional[int]
    claim_id: str
    statement_id: str
    type: str
    status: str
    rationale: str
    evidence_ids: List[str]
    confidence: Optional[float]
    visibility: str


def get_block_rows(
    db: Session, revision_id: str, ids: Optional[Sequence[str]] = None
) -> List[BlockRow]:
    """按 id 读取原文块；只返回 ``origin=source_extraction`` 的一级依据。

    生成摘要块（origin=generated）绝不能成为 claim 的一级依据。

    **排序即文档顺序**：``blocks.page_id`` 是 UUID，按它排序会得到**随机顺序**
    （原实现即如此），任何"按块顺序分节/取前 N 块"的逻辑都会出错。这里 join
    ``pages`` 并按 ``pdf_page_index, ordinal`` 排序——这才是阅读顺序。
    """
    stmt = (
        select(BlockORM)
        .outerjoin(PageORM, PageORM.id == BlockORM.page_id)
        .where(
            BlockORM.revision_id == revision_id,
            BlockORM.origin == "source_extraction",
        )
    )
    if ids:
        stmt = stmt.where(BlockORM.id.in_(list(ids)))
    stmt = stmt.order_by(PageORM.pdf_page_index.asc(), BlockORM.ordinal.asc())
    return [
        BlockRow(
            id=row.id, page_id=row.page_id, ordinal=row.ordinal, kind=row.kind,
            text=row.text or "", anchor_id=row.anchor_id, origin=row.origin,
        )
        for row in db.execute(stmt).scalars().all()
    ]


def list_block_rows(db: Session, revision_id: str) -> List[BlockRow]:
    return get_block_rows(db, revision_id, None)


def _statement_snapshot(row: StatementORM) -> StatementRow:
    return StatementRow(
        id=row.id, claim_id=row.claim_id, text=row.text or "", kind=row.kind or "fact",
        citations=list(row.citations or []), qualifiers=list(row.qualifiers or []),
        evidence_ids=list(row.evidence_ids or []),
        display_class=row.display_class or "unverified", origin=row.origin or "generated",
        validation=row.validation,
    )


def _claim_snapshot(row: ClaimRecordORM) -> ClaimRow:
    return ClaimRow(
        id=row.id, legacy_id=row.legacy_id, claim_id=row.claim_id,
        statement_id=row.statement_id, type=row.type or "RESULT",
        status=row.status or "unverified", rationale=row.rationale or "",
        evidence_ids=list(row.evidence_ids or []), confidence=row.confidence,
        visibility=row.visibility or "exhibit",
    )


def get_statement_row(
    db: Session, revision_id: str, statement_id: str
) -> Optional[StatementRow]:
    row = db.get(StatementORM, statement_id)
    if row is None or row.revision_id != revision_id:
        return None
    return _statement_snapshot(row)


def list_statement_rows(
    db: Session, revision_id: str, ids: Optional[Sequence[str]] = None
) -> List[StatementRow]:
    stmt = select(StatementORM).where(StatementORM.revision_id == revision_id)
    if ids:
        stmt = stmt.where(StatementORM.id.in_(list(ids)))
    return [
        _statement_snapshot(row)
        for row in db.execute(stmt.order_by(StatementORM.ordinal.asc())).scalars().all()
    ]


def get_claim_row(db: Session, revision_id: str, claim_id: str) -> Optional[ClaimRow]:
    row = db.execute(
        select(ClaimRecordORM).where(
            ClaimRecordORM.revision_id == revision_id,
            ClaimRecordORM.claim_id == claim_id,
        )
    ).scalars().first()
    return _claim_snapshot(row) if row is not None else None


def list_claim_rows(
    db: Session, revision_id: str, visibility: Optional[str] = None
) -> List[ClaimRow]:
    stmt = select(ClaimRecordORM).where(ClaimRecordORM.revision_id == revision_id)
    if visibility is not None:
        stmt = stmt.where(ClaimRecordORM.visibility == visibility)
    return [
        _claim_snapshot(row)
        for row in db.execute(stmt.order_by(ClaimRecordORM.id.asc())).scalars().all()
    ]


def list_claim_ids(db: Session, revision_id: str) -> List[str]:
    return list(
        db.execute(
            select(ClaimRecordORM.claim_id).where(ClaimRecordORM.revision_id == revision_id)
        ).scalars().all()
    )


# --------------------------------------------------------------- 写入


def upsert_statement(
    db: Session, draft: StatementDraft, *, origin: str = "generated",
    display_class: str = "unverified", ordinal: int = 0,
) -> StatementORM:
    """注册陈述身份（**只建立 unverified 身份，不写 evidence**）。

    陈述 id 是**全局主键**：若已存在且属于**另一个 revision**，说明调用方
    复用了同一个 id 去表达不同来源的陈述——这是身份污染，必须拒绝而不是
    悄悄"改嫁"，否则旧版本的证据会被错误挂到新版本上。
    """
    row = db.get(StatementORM, draft.id)
    if row is not None and row.revision_id != draft.scope.revision_id:
        raise revision_mismatch(
            f"陈述 id {draft.id} 已属于 revision {row.revision_id}，不能改嫁到 "
            f"{draft.scope.revision_id}"
        )
    if row is None:
        row = StatementORM(
            id=draft.id,
            paper_id=draft.scope.paper_id,
            revision_id=draft.scope.revision_id,
            claim_id=draft.claim_id,
            text=draft.text,
            kind=draft.kind,
            citations=[c.model_dump() for c in draft.citations],
            qualifiers=list(draft.qualifiers),
            origin=origin,
            display_class=display_class,
            ordinal=ordinal,
        )
        db.add(row)
    else:
        row.claim_id = draft.claim_id
        row.text = draft.text
        row.kind = draft.kind
        row.citations = [c.model_dump() for c in draft.citations]
        row.qualifiers = list(draft.qualifiers)
        row.ordinal = ordinal
    return row


def update_statement_validation(
    db: Session, statement_id: str, *, validation: dict, evidence_ids: Sequence[str],
    display_class: str, origin: str = "generated",
) -> None:
    row = db.get(StatementORM, statement_id)
    if row is None:
        return
    row.validation = dict(validation)
    row.evidence_ids = list(evidence_ids)
    row.display_class = display_class
    row.origin = origin


def upsert_claim(db: Session, record: ClaimRecord) -> ClaimRecordORM:
    row = db.execute(
        select(ClaimRecordORM).where(
            ClaimRecordORM.revision_id == record.scope.revision_id,
            ClaimRecordORM.claim_id == record.claim_id,
        )
    ).scalars().first()
    if row is None:
        row = ClaimRecordORM(
            id=record.id,
            paper_id=record.scope.paper_id,
            revision_id=record.scope.revision_id,
            legacy_id=record.legacy_id,
            claim_id=record.claim_id,
            statement_id=record.statement_id,
            type=record.type,
            status=record.status,
            rationale=record.rationale,
            evidence_ids=list(record.evidence_ids),
            confidence=record.confidence,
            visibility=record.visibility,
        )
        db.add(row)
    else:
        row.id = record.id
        row.legacy_id = record.legacy_id
        row.statement_id = record.statement_id
        row.type = record.type
        row.status = record.status
        row.rationale = record.rationale
        row.evidence_ids = list(record.evidence_ids)
        row.confidence = record.confidence
        row.visibility = record.visibility
    return row


def replace_structure(
    db: Session, structure: StructureArtifact
) -> None:
    """整版覆盖写结构产物（幂等：同 revision 重复生成不累积）。"""
    revision_id = structure.scope.revision_id
    for model in (SectionRecordORM, MapItemORM, MethodStepORM):
        for row in db.execute(
            select(model).where(model.revision_id == revision_id)
        ).scalars().all():
            db.delete(row)

    def _sid(local_id: str) -> str:
        """结构行 id 全局唯一且 ≤36 字符（规格 Id=UUID/String(36)）。

        - 短 id（step/map）拼 revision 前缀，build→get 往返稳定；
        - 超长 id（如 ``sec-{block_id}`` 40 字符）用 sha256 压缩到 36 字符，
          避免 Postgres ``VARCHAR(36)`` 报 ``StringDataRightTruncation``。
        """
        full = (
            local_id
            if local_id.startswith(revision_id[:8] + "-")
            else f"{revision_id[:8]}-{local_id}"
        )
        if len(full) <= 36:
            return full
        return hashlib.sha256(full.encode("utf-8")).hexdigest()[:36]

    for ordinal, section in enumerate(structure.sections):
        db.add(SectionRecordORM(
            id=_sid(section.id), paper_id=structure.scope.paper_id, revision_id=revision_id,
            heading=section.heading, kind=section.kind,
            source_block_ids=list(section.source_block_ids),
            anchor_ids=list(section.anchor_ids),
            summary=section.summary.model_dump(),
            key_points=[kp.model_dump() for kp in section.key_points],
            ordinal=ordinal,
        ))

    if structure.map is not None:
        for ordinal, item in enumerate(structure.map.items):
            db.add(MapItemORM(
                id=_sid(item.id), paper_id=structure.scope.paper_id, revision_id=revision_id,
                kind=item.kind, text=item.text.model_dump(),
                claim_ids=list(item.claim_ids), anchor_ids=list(item.anchor_ids),
                ordinal=ordinal,
            ))

    for ordinal, step in enumerate(structure.method_steps):
        db.add(MethodStepORM(
            id=_sid(step.id), paper_id=structure.scope.paper_id, revision_id=revision_id,
            ordinal=ordinal, label=step.label.model_dump(),
            detail=step.detail.model_dump(), phase=step.phase,
            claim_ids=list(step.claim_ids), media_ids=list(step.media_ids),
            binding_ids=list(step.binding_ids),
        ))


def get_structure(db: Session, scope: Scope) -> StructureArtifact:
    revision_id = scope.revision_id
    prefix = revision_id[:8] + "-"

    def _local(row_id: str) -> str:
        """读回时剥回落库前缀，保证 build→get 往返 id 稳定。"""
        return row_id[len(prefix):] if row_id.startswith(prefix) else row_id

    sections = [
        SectionRecord(
            scope=scope, id=_local(row.id), heading=row.heading, kind=row.kind,
            source_block_ids=list(row.source_block_ids or []),
            anchor_ids=list(row.anchor_ids or []),
            summary=ArtifactText(**row.summary) if row.summary else ArtifactText(),
            key_points=[ArtifactText(**kp) for kp in (row.key_points or [])],
        )
        for row in db.execute(
            select(SectionRecordORM)
            .where(SectionRecordORM.revision_id == revision_id)
            .order_by(SectionRecordORM.ordinal.asc())
        ).scalars().all()
    ]
    items = [
        MapItem(
            id=_local(row.id), kind=row.kind,
            text=ArtifactText(**row.text) if row.text else ArtifactText(),
            claim_ids=list(row.claim_ids or []), anchor_ids=list(row.anchor_ids or []),
        )
        for row in db.execute(
            select(MapItemORM)
            .where(MapItemORM.revision_id == revision_id)
            .order_by(MapItemORM.ordinal.asc())
        ).scalars().all()
    ]
    steps = [
        MethodStepRecord(
            scope=scope, id=_local(row.id), order=row.ordinal,
            label=ArtifactText(**row.label) if row.label else ArtifactText(),
            detail=ArtifactText(**row.detail) if row.detail else ArtifactText(),
            phase=row.phase, claim_ids=list(row.claim_ids or []),
            media_ids=list(row.media_ids or []), binding_ids=list(row.binding_ids or []),
        )
        for row in db.execute(
            select(MethodStepORM)
            .where(MethodStepORM.revision_id == revision_id)
            .order_by(MethodStepORM.ordinal.asc())
        ).scalars().all()
    ]
    map_artifact = None
    if items:
        map_artifact = MapArtifact(
            scope=scope, id=f"map-{scope.revision_id}", items=items,
        )
    return StructureArtifact(
        scope=scope, sections=sections, map=map_artifact, method_steps=steps,
    )


# --------------------------------------------------------------- 投影


def statement_dto(scope: Scope, row: StatementRow) -> VerifiedStatement:
    """把 statements 行投影为 ``VerifiedStatement``。

    **必须带出 ``validation`` 与 ``citations``**——这两列都已落库
    （``statements.validation`` / ``statements.citations``），此前漏传导致：

    - ``stage_verify`` 收集不到任何 ``s.validation`` → 报"没有可决策的校验报告"，
      Supervisor 从不运行；
    - exhibits/scene/graph 拿不到验证结论 → 图谱与讲解为空。

    反序列化失败时**降级为 None/空列表**而不是抛错：一行历史脏数据不应该
    让整个读回接口 500（与 §5.11「新 DTO 校验不得拖垮旧数据读取」一致）。
    """
    from app.contracts.evidence import CitationCandidate, ValidationReport

    validation = None
    if row.validation:
        try:
            validation = ValidationReport.model_validate(row.validation)
        except Exception:  # noqa: BLE001 - 单行脏数据不得拖垮读回
            validation = None

    citations: List[CitationCandidate] = []
    for raw in (row.citations or []):
        if isinstance(raw, CitationCandidate):
            citations.append(raw)
            continue
        if isinstance(raw, dict):
            try:
                citations.append(CitationCandidate(**raw))
            except Exception:  # noqa: BLE001
                continue

    return VerifiedStatement(
        scope=scope, id=row.id, claim_id=row.claim_id, text=row.text,
        kind=row.kind or "fact", qualifiers=list(row.qualifiers or []),
        citations=citations,
        validation=validation,
        evidence_ids=list(row.evidence_ids or []),
        origin=row.origin or "generated",
        display_class=row.display_class or "unverified",
    )


def claim_dto(scope: Scope, row: ClaimRow) -> ClaimRecord:
    return ClaimRecord(
        scope=scope, id=row.id, legacy_id=row.legacy_id, claim_id=row.claim_id,
        statement_id=row.statement_id, type=row.type or "RESULT",
        status=row.status or "unverified", rationale=row.rationale or "",
        evidence_ids=list(row.evidence_ids or []), confidence=row.confidence,
        visibility=row.visibility or "exhibit",
    )


def audit(db: Session, *, kind: str, scope: Scope, actor: str, payload: Dict) -> None:
    """审计留痕：只存 ID/hash/摘要，不存原文与 token。"""
    from app.models.audit import AuditLogORM

    db.add(
        AuditLogORM(
            paper_id=scope.paper_id,
            revision_id=scope.revision_id,
            kind=kind,
            actor=actor,
            payload=payload,
        )
    )


__all__ = [
    "get_block_rows",
    "list_block_rows",
    "get_statement_row",
    "list_statement_rows",
    "get_claim_row",
    "list_claim_rows",
    "list_claim_ids",
    "upsert_statement",
    "update_statement_validation",
    "upsert_claim",
    "replace_structure",
    "get_structure",
    "statement_dto",
    "claim_dto",
    "audit",
]
