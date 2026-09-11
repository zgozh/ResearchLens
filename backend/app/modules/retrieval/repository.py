"""M07 — retrieval 私有持久化访问（REFACTOR_SPEC §6.9）。

只做"表 ↔ 数据"投影与读写，不含业务判断。跨模块不暴露 Session。
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models.artifacts import BlockORM, PageORM
from app.models.retrieval import ChunkORM, ChunkVectorORM

#: 只有原文提取产物可作一级证据
SOURCE_ORIGIN = "source_extraction"


@dataclass(frozen=True)
class ChunkRow:
    """分块的冻结快照（离开 Session 后仍可读）。"""

    id: str
    ordinal: int
    text: str
    block_ids: List[str]
    anchor_ids: List[str]
    media_ids: List[str]
    section_path: List[str]
    content_hash: str
    token_estimate: int
    embedding_space: Optional[str]


@dataclass(frozen=True)
class VectorRow:
    chunk_id: str
    space: str
    dimension: int
    vector: List[float]


def list_source_blocks(db: Session, revision_id: str) -> List[tuple]:
    """按阅读顺序读原文块，**排除 ``origin != source_extraction``**。

    返回 ``(block, page_index)`` 元组序列；同时带上页面 pdf_page_index 供排序。
    """
    stmt = (
        select(BlockORM, PageORM.pdf_page_index)
        .join(PageORM, PageORM.id == BlockORM.page_id)
        .where(
            BlockORM.revision_id == revision_id,
            BlockORM.origin == SOURCE_ORIGIN,
        )
        .order_by(PageORM.pdf_page_index, BlockORM.ordinal)
    )
    return [(row[0], row[1]) for row in db.execute(stmt).all()]


def existing_hashes(db: Session, revision_id: str) -> set[str]:
    stmt = select(ChunkORM.content_hash).where(ChunkORM.revision_id == revision_id)
    return {h for (h,) in db.execute(stmt).all() if h}


def list_chunks(db: Session, revision_id: str) -> List[ChunkRow]:
    stmt = (
        select(ChunkORM)
        .where(ChunkORM.revision_id == revision_id)
        .order_by(ChunkORM.ordinal)
    )
    return [_chunk_row(row) for row in db.execute(stmt).scalars().all()]


def get_chunk(db: Session, chunk_id: str) -> Optional[ChunkRow]:
    row = db.get(ChunkORM, chunk_id)
    return _chunk_row(row) if row is not None else None


def upsert_chunk(
    db: Session,
    *,
    chunk_id: str,
    paper_id: int,
    revision_id: str,
    ordinal: int,
    text: str,
    block_ids: Sequence[str],
    anchor_ids: Sequence[str],
    media_ids: Sequence[str],
    section_path: Sequence[str],
    content_hash: str,
    token_estimate: int,
    embedding_space: Optional[str] = None,
) -> str:
    """按 (revision_id, content_hash) 幂等写入；已存在则返回原有 id。"""
    stmt = select(ChunkORM).where(
        ChunkORM.revision_id == revision_id,
        ChunkORM.content_hash == content_hash,
    )
    existing = db.execute(stmt).scalars().first()
    if existing is not None:
        return existing.id
    row = ChunkORM(
        id=chunk_id,
        paper_id=paper_id,
        revision_id=revision_id,
        ordinal=ordinal,
        text=text,
        block_ids=list(block_ids),
        anchor_ids=list(anchor_ids),
        media_ids=list(media_ids),
        section_path=list(section_path),
        content_hash=content_hash,
        token_estimate=token_estimate,
        embedding_space=embedding_space,
    )
    db.add(row)
    db.flush()
    return row.id


def delete_chunks(db: Session, revision_id: str) -> int:
    """整版重建时先清旧块与旧向量。"""
    ids = [cid for (cid,) in db.execute(
        select(ChunkORM.id).where(ChunkORM.revision_id == revision_id)
    ).all()]
    if not ids:
        return 0
    db.execute(delete(ChunkVectorORM).where(ChunkVectorORM.chunk_id.in_(ids)))
    db.execute(delete(ChunkORM).where(ChunkORM.id.in_(ids)))
    return len(ids)


# ------------------------------------------------------------------ 向量

def upsert_vector(
    db: Session,
    *,
    vector_id: str,
    chunk_id: str,
    paper_id: int,
    revision_id: str,
    space: str,
    vector: Sequence[float],
) -> None:
    """按 (chunk_id, space) 幂等写入；**旧空间的行不动**，保证旧索引只读可用。"""
    stmt = select(ChunkVectorORM).where(
        ChunkVectorORM.chunk_id == chunk_id,
        ChunkVectorORM.space == space,
    )
    existing = db.execute(stmt).scalars().first()
    payload = [float(x) for x in vector]
    if existing is not None:
        existing.vector = payload
        existing.dimension = len(payload)
        return
    db.add(ChunkVectorORM(
        id=vector_id,
        chunk_id=chunk_id,
        paper_id=paper_id,
        revision_id=revision_id,
        space=space,
        dimension=len(payload),
        vector=payload,
    ))
    db.flush()


def list_vectors(db: Session, revision_id: str, space: str) -> List[VectorRow]:
    stmt = select(ChunkVectorORM).where(
        ChunkVectorORM.revision_id == revision_id,
        ChunkVectorORM.space == space,
    )
    out: List[VectorRow] = []
    for row in db.execute(stmt).scalars().all():
        out.append(VectorRow(
            chunk_id=row.chunk_id,
            space=row.space,
            dimension=int(row.dimension or 0),
            vector=[float(x) for x in (row.vector or [])],
        ))
    return out


def list_vectors_any_space(db: Session, revision_id: str) -> List[VectorRow]:
    """读取该 revision 的**全部**向量行（含历史空间）。

    检索侧再按当前 embedding 空间过滤：旧空间行保持只读可用，
    维度变化时不会被误用，也不会被删除。
    """
    stmt = select(ChunkVectorORM).where(ChunkVectorORM.revision_id == revision_id)
    return [
        VectorRow(
            chunk_id=row.chunk_id,
            space=row.space,
            dimension=int(row.dimension or 0),
            vector=[float(x) for x in (row.vector or [])],
        )
        for row in db.execute(stmt).scalars().all()
    ]


def count_vectors(db: Session, revision_id: str, space: Optional[str] = None) -> int:
    stmt = select(ChunkVectorORM.id).where(ChunkVectorORM.revision_id == revision_id)
    if space:
        stmt = stmt.where(ChunkVectorORM.space == space)
    return len(db.execute(stmt).all())


def spaces_in_use(db: Session, revision_id: str) -> List[str]:
    stmt = select(ChunkVectorORM.space).where(ChunkVectorORM.revision_id == revision_id)
    return sorted({s for (s,) in db.execute(stmt).all() if s})


def new_id(seed: str) -> str:
    """确定性 UUID（同 seed 同 id），便于索引重建保持稳定。"""
    import uuid

    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"researchlens:chunk:{seed}"))


def _chunk_row(row: ChunkORM) -> ChunkRow:
    return ChunkRow(
        id=row.id,
        ordinal=int(row.ordinal or 0),
        text=row.text or "",
        block_ids=list(row.block_ids or []),
        anchor_ids=list(row.anchor_ids or []),
        media_ids=list(row.media_ids or []),
        section_path=list(row.section_path or []),
        content_hash=row.content_hash or "",
        token_estimate=int(row.token_estimate or 0),
        embedding_space=row.embedding_space,
    )


__all__ = [
    "SOURCE_ORIGIN",
    "ChunkRow",
    "VectorRow",
    "list_source_blocks",
    "existing_hashes",
    "list_chunks",
    "get_chunk",
    "upsert_chunk",
    "delete_chunks",
    "upsert_vector",
    "list_vectors",
    "list_vectors_any_space",
    "count_vectors",
    "spaces_in_use",
    "new_id",
]
