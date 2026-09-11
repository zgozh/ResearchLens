"""M03 — 媒体私有数据访问（REFACTOR_SPEC §5.3、§5.10 M03）。

Asset 的字节/hash/path 归 M01，本模块只拥有 Media 的图表/公式语义与裁剪关系。
"""
from __future__ import annotations

from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import not_found
from app.models.artifacts import MediaORM
from app.modules.papers import repository as papers_repo


def insert_media(
    db: Session,
    *,
    media_id: str,
    paper_id: int,
    revision_id: str,
    kind: str,
    original_label: Optional[str],
    legacy_no: Optional[int],
    caption: str,
    anchor_ids: List[str],
    original_asset_ids: List[str],
    thumbnail_asset_id: Optional[str],
    extracted: Optional[dict],
    provenance: dict,
    excluded: bool = False,
    exclusion_reason: Optional[str] = None,
    caption_alt: str = "",
) -> MediaORM:
    row = MediaORM(
        id=media_id,
        paper_id=paper_id,
        revision_id=revision_id,
        kind=kind,
        original_label=original_label,
        legacy_no=legacy_no,
        caption=caption or "",
        caption_alt=caption_alt or "",
        anchor_ids=list(anchor_ids or []),
        original_asset_ids=list(original_asset_ids or []),
        thumbnail_asset_id=thumbnail_asset_id,
        extracted=extracted,
        provenance=provenance or {},
        excluded=excluded,
        exclusion_reason=exclusion_reason,
    )
    db.add(row)
    db.flush()
    return row


def list_media(
    db: Session, revision_id: str, *, kind: Optional[str] = None, include_excluded: bool = False
) -> List[MediaORM]:
    stmt = select(MediaORM).where(MediaORM.revision_id == revision_id)
    if kind:
        stmt = stmt.where(MediaORM.kind == kind)
    if not include_excluded:
        stmt = stmt.where(MediaORM.excluded.is_(False))
    stmt = stmt.order_by(MediaORM.kind.asc(), MediaORM.legacy_no.asc().nulls_last(), MediaORM.id.asc())
    return list(db.execute(stmt).scalars())


def get_media_rows(db: Session, revision_id: str, ids: List[str]) -> List[MediaORM]:
    if not ids:
        return []
    stmt = select(MediaORM).where(
        MediaORM.revision_id == revision_id, MediaORM.id.in_(list(ids))
    )
    return list(db.execute(stmt).scalars())


def require_media(db: Session, revision_id: str, media_id: str) -> MediaORM:
    stmt = select(MediaORM).where(
        MediaORM.revision_id == revision_id, MediaORM.id == media_id
    )
    row = db.execute(stmt).scalars().first()
    if row is None:
        raise not_found(f"媒体 {media_id} 不存在")
    return row


def require_scope_revision(db: Session, paper_id: int, revision_id: str):
    """校验 revision 属于该 paper（复用 M01 的 scope 校验，避免重复实现）。"""
    return papers_repo.require_scope_revision(db, paper_id, revision_id)


def delete_media_for_revision(db: Session, revision_id: str) -> None:
    from sqlalchemy import delete

    db.execute(delete(MediaORM).where(MediaORM.revision_id == revision_id))
    db.flush()


def assert_writable_revision(db: Session, revision_id: str) -> None:
    """拒绝写入已发布 revision（§5.14：不对已发布版本做原位重解析）。

    ``build_media`` 重建前需要清理旧行；若不拦住 published，就会把已发布
    事实悄悄替换掉。修正必须走新 revision。
    """
    from app.core.errors import ErrorCode, DomainError
    from app.models.source import RevisionORM

    row = db.get(RevisionORM, revision_id)
    if row is None:
        return
    if (row.state or "").lower() == "published":
        raise DomainError(
            ErrorCode.CONFLICT,
            "已发布修订版不得重新写入媒体产物；请创建新 revision",
            retryable=False,
        )


def next_legacy_no(db: Session, revision_id: str, kind: str) -> int:
    """该 revision 内按 kind 分配兼容整数编号；不重编已存在编号。"""
    rows = list_media(db, revision_id, kind=kind, include_excluded=True)
    used = [r.legacy_no for r in rows if r.legacy_no is not None]
    return (max(used) + 1) if used else 1


__all__ = [
    "insert_media",
    "list_media",
    "get_media_rows",
    "require_media",
    "require_scope_revision",
    "delete_media_for_revision",
    "assert_writable_revision",
    "next_legacy_no",
]
