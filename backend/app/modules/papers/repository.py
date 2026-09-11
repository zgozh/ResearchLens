"""M01 — 论文 / 源文件 / 修订版 / 资产 私有数据访问（REFACTOR_SPEC §5.2、§5.3、§5.10）。

只在本模块内使用；跨模块调用方只能通过 ``app.modules.papers.service`` 的公共函数。
所有函数接收一个已开启的 Session（由 service 层用 ``session_scope()`` 短事务包裹）。
"""
from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from typing import Iterable, List, Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import DomainError, ErrorCode, conflict, not_found, revision_mismatch
from app.models.models import Paper
from app.models.source import AssetORM, ModelSnapshotORM, RevisionORM, SourceDocumentORM, new_id

#: slug 允许字符：ASCII 字母数字与连字符；长度 ≤64（§5.14 唯一约束）
_SLUG_MAX = 64
_NON_SLUG = re.compile(r"[^a-z0-9]+")


def now() -> datetime:
    return datetime.now(timezone.utc)


def make_slug(title: str, *, fallback: str = "paper") -> str:
    """由标题生成 slug：ASCII 化 + 折叠连字符 + 截断到 64。

    中文标题不含 ASCII 字母数字时，退化为 ``fallback`` 前缀（不猜测拼音），
    最终长度仍严格 ≤64。
    """
    base = _NON_SLUG.sub("-", (title or "").strip().lower()).strip("-")
    if not base:
        base = re.sub(r"[^a-z0-9]+", "-", fallback.lower()).strip("-") or "paper"
    if len(base) > _SLUG_MAX:
        base = base[:_SLUG_MAX].rstrip("-") or "paper"
    return base


def unique_slug(db: Session, desired: str, *, exclude_paper_id: Optional[int] = None) -> str:
    """确保 slug 全局唯一；冲突时加 ``-<n>`` 后缀且仍 ≤64。"""
    candidate = desired
    suffix = 1
    while True:
        stmt = select(Paper.id).where(Paper.slug == candidate)
        if exclude_paper_id is not None:
            stmt = stmt.where(Paper.id != exclude_paper_id)
        if db.execute(stmt).first() is None:
            return candidate
        suffix += 1
        tail = f"-{suffix}"
        candidate = (desired[: _SLUG_MAX - len(tail)]).rstrip("-") + tail


# ------------------------------------------------------------------ Paper


def insert_paper(
    db: Session,
    *,
    title: str,
    slug: str,
    source_mode: str,
    provenance_class: str,
    status: str = "pending",
    pdf_url: str = "",
    abstract: str = "",
    accent: str = "#6366F1",
) -> Paper:
    paper = Paper(
        slug=slug,
        title=(title or "").strip() or "Untitled paper",
        source_mode=source_mode,
        provenance_class=provenance_class,
        status=status,
        pdf_url=pdf_url,
        abstract=abstract,
        accent=accent,
        updated_at=now(),
    )
    db.add(paper)
    db.flush()
    return paper


def get_paper_row(db: Session, paper_id: int) -> Optional[Paper]:
    return db.get(Paper, paper_id)


def require_paper(db: Session, paper_id: int) -> Paper:
    row = get_paper_row(db, paper_id)
    if row is None:
        raise not_found(f"论文 {paper_id} 不存在")
    return row


def list_paper_rows(db: Session, source_modes: Optional[Iterable[str]] = None) -> List[Paper]:
    stmt = select(Paper).order_by(Paper.id.asc())
    if source_modes:
        stmt = stmt.where(Paper.source_mode.in_(list(source_modes)))
    return list(db.execute(stmt).scalars())


def update_paper_fields(db: Session, paper_id: int, **fields) -> Paper:
    row = require_paper(db, paper_id)
    for key, value in fields.items():
        if hasattr(row, key):
            setattr(row, key, value)
    row.updated_at = now()
    db.flush()
    return row


# ------------------------------------------------------------------ SourceDocument


def insert_source_document(
    db: Session,
    *,
    paper_id: int,
    sha256: str,
    asset_id: str,
    byte_size: int,
    mime: str,
    page_count: int,
    source_url: str,
    original_filename: str,
    acquisition: str,
) -> SourceDocumentORM:
    row = SourceDocumentORM(
        paper_id=paper_id,
        sha256=sha256,
        asset_id=asset_id,
        byte_size=byte_size,
        mime=mime,
        page_count=page_count,
        source_url=source_url or "",
        original_filename=original_filename or "",
        acquisition=acquisition,
    )
    db.add(row)
    db.flush()
    return row


def find_source_by_hash(db: Session, paper_id: int, sha256: str) -> Optional[SourceDocumentORM]:
    stmt = select(SourceDocumentORM).where(
        SourceDocumentORM.paper_id == paper_id, SourceDocumentORM.sha256 == sha256
    )
    return db.execute(stmt).scalars().first()


def get_source_row(db: Session, source_id: str) -> Optional[SourceDocumentORM]:
    return db.get(SourceDocumentORM, source_id)


def require_source(db: Session, source_id: str) -> SourceDocumentORM:
    row = get_source_row(db, source_id)
    if row is None:
        raise not_found(f"源文件 {source_id} 不存在")
    return row


def get_source_for_paper(db: Session, paper_id: int) -> Optional[SourceDocumentORM]:
    stmt = (
        select(SourceDocumentORM)
        .where(SourceDocumentORM.paper_id == paper_id)
        .order_by(SourceDocumentORM.created_at.desc())
    )
    return db.execute(stmt).scalars().first()


# ------------------------------------------------------------------ Revision


def insert_revision(
    db: Session,
    *,
    paper_id: int,
    source_document_id: Optional[str],
    kind: str,
    state: str = "staging",
    parser_name: str = "",
    parser_version: str = "",
    normalizer_version: str = "",
    prompt_version: str = "",
    model_snapshot_id: Optional[str] = None,
    quality: str = "source_only",
) -> RevisionORM:
    row = RevisionORM(
        paper_id=paper_id,
        source_document_id=source_document_id,
        kind=kind,
        state=state,
        parser_name=parser_name,
        parser_version=parser_version,
        normalizer_version=normalizer_version,
        prompt_version=prompt_version,
        model_snapshot_id=model_snapshot_id,
        quality=quality,
        warnings=[],
    )
    db.add(row)
    db.flush()
    return row


def get_revision_row(db: Session, revision_id: str) -> Optional[RevisionORM]:
    return db.get(RevisionORM, revision_id)


def require_revision(db: Session, revision_id: str) -> RevisionORM:
    row = get_revision_row(db, revision_id)
    if row is None:
        raise not_found(f"修订版 {revision_id} 不存在")
    return row


def require_scope_revision(db: Session, paper_id: int, revision_id: str) -> RevisionORM:
    """校验 revision 属于该 paper；跨 paper 引用一律 REVISION_MISMATCH。"""
    row = require_revision(db, revision_id)
    if int(row.paper_id) != int(paper_id):
        raise revision_mismatch("修订版与论文不一致")
    return row


def list_revision_rows(db: Session, paper_id: int) -> List[RevisionORM]:
    stmt = (
        select(RevisionORM)
        .where(RevisionORM.paper_id == paper_id)
        .order_by(RevisionORM.created_at.asc())
    )
    return list(db.execute(stmt).scalars())


# ------------------------------------------------------------------ Asset


def insert_asset(
    db: Session,
    *,
    paper_id: int,
    revision_id: Optional[str],
    sha256: str,
    mime: str,
    byte_size: int,
    rel_path: str,
    kind: str,
    width_px: Optional[int] = None,
    height_px: Optional[int] = None,
) -> AssetORM:
    row = AssetORM(
        paper_id=paper_id,
        revision_id=revision_id,
        sha256=sha256,
        mime=mime,
        byte_size=byte_size,
        rel_path=rel_path,
        kind=kind,
        width_px=width_px,
        height_px=height_px,
    )
    db.add(row)
    db.flush()
    return row


def find_asset_by_content(
    db: Session, paper_id: int, sha256: str, kind: str
) -> Optional[AssetORM]:
    """内容寻址幂等：同 paper + 同 hash + 同 kind 视为同一份资产。"""
    stmt = select(AssetORM).where(
        AssetORM.paper_id == paper_id,
        AssetORM.sha256 == sha256,
        AssetORM.kind == kind,
    )
    return db.execute(stmt).scalars().first()


def get_asset_row(db: Session, asset_id: str) -> Optional[AssetORM]:
    return db.get(AssetORM, asset_id)


def require_asset(db: Session, asset_id: str) -> AssetORM:
    row = get_asset_row(db, asset_id)
    if row is None:
        raise not_found(f"资产 {asset_id} 不存在")
    return row


def get_assets_for_paper(db: Session, paper_id: int, ids: Optional[List[str]] = None) -> List[AssetORM]:
    """批量查询，绝不逐资产开 Session（§5.10 M01 约束）。"""
    stmt = select(AssetORM).where(AssetORM.paper_id == paper_id)
    if ids:
        stmt = stmt.where(AssetORM.id.in_(list(ids)))
    stmt = stmt.order_by(AssetORM.created_at.asc())
    return list(db.execute(stmt).scalars())


def get_assets_by_ids(db: Session, ids: List[str]) -> List[AssetORM]:
    if not ids:
        return []
    stmt = select(AssetORM).where(AssetORM.id.in_(list(ids)))
    return list(db.execute(stmt).scalars())


# ------------------------------------------------------------------ 模型快照


def find_or_create_snapshot(db: Session, snapshot: dict) -> ModelSnapshotORM:
    chat = snapshot.get("chat_model", "")
    embedding = snapshot.get("embedding_model")
    version = snapshot.get("capability_version", "rl.capabilities/1")
    stmt = select(ModelSnapshotORM).where(
        ModelSnapshotORM.chat_model == chat,
        ModelSnapshotORM.embedding_model == embedding,
        ModelSnapshotORM.capability_version == version,
    )
    row = db.execute(stmt).scalars().first()
    if row is not None:
        return row
    row = ModelSnapshotORM(
        id=new_id(),
        provider=snapshot.get("provider", "dashscope"),
        base_url=snapshot.get("base_url", ""),
        chat_model=chat,
        embedding_model=embedding,
        embedding_dimension=snapshot.get("embedding_dimension"),
        capability_version=version,
        temperature=float(snapshot.get("temperature", 0.2)),
    )
    db.add(row)
    db.flush()
    return row


# ------------------------------------------------------------------ 发布 CAS


def cas_publish(
    db: Session,
    paper_id: int,
    *,
    expected_revision: Optional[str],
    new_revision_id: str,
    quality: str,
) -> Paper:
    """原子切换 published_revision_id；期望不符则 CONFLICT（不覆盖他人发布）。

    同时把该 revision 的 state 推进为 ``published``，使「已发布不得原位重解析」
    的约束由数据本身保证（而非仅看 pointer）。
    """
    row = require_paper(db, paper_id)
    current = row.published_revision_id
    if (expected_revision or None) != (current or None):
        raise conflict(
            "发布冲突：expected_revision 与当前 published_revision_id 不一致"
        )
    if expected_revision and expected_revision != new_revision_id:
        prev = db.execute(
            select(RevisionORM).where(RevisionORM.id == expected_revision)
        ).scalars().first()
        if prev is not None and prev.state == "published":
            prev.state = "superseded"
    target = db.execute(
        select(RevisionORM).where(RevisionORM.id == new_revision_id)
    ).scalars().first()
    if target is not None and target.state != "published":
        target.state = "published"
    row.published_revision_id = new_revision_id
    row.status = "ready" if quality in ("complete", "partial") else row.status
    row.updated_at = now()
    db.flush()
    return row


def count_papers(db: Session) -> int:
    return int(db.execute(select(func.count(Paper.id))).scalar() or 0)


def digest_of(*parts: Optional[str]) -> str:
    h = hashlib.sha256()
    for p in parts:
        h.update((p or "").encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()


__all__ = [
    "now",
    "make_slug",
    "unique_slug",
    "insert_paper",
    "get_paper_row",
    "require_paper",
    "list_paper_rows",
    "update_paper_fields",
    "insert_source_document",
    "find_source_by_hash",
    "get_source_row",
    "require_source",
    "get_source_for_paper",
    "insert_revision",
    "get_revision_row",
    "require_revision",
    "require_scope_revision",
    "list_revision_rows",
    "insert_asset",
    "find_asset_by_content",
    "get_asset_row",
    "require_asset",
    "get_assets_for_paper",
    "get_assets_by_ids",
    "find_or_create_snapshot",
    "cas_publish",
    "count_papers",
    "digest_of",
]
