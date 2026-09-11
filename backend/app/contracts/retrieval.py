"""M00 — 检索契约（REFACTOR_SPEC §5.6）。"""
from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import Field

from .common import (
    AnchorId,
    BlockId,
    ContractModel,
    Hash,
    Id,
    MediaId,
    Scope,
    Warning,
)


class Chunk(ContractModel):
    scope: Scope
    id: Id
    block_ids: List[BlockId] = Field(default_factory=list)
    anchor_ids: List[AnchorId] = Field(default_factory=list)
    text: str = ""
    section_path: List[str] = Field(default_factory=list)
    media_ids: List[MediaId] = Field(default_factory=list)
    content_hash: Optional[Hash] = None
    token_estimate: int = Field(default=0, ge=0)
    embedding_space: Optional[str] = None


class RetrievalRequest(ContractModel):
    scope: Scope
    query: str
    top_k: int = Field(default=5, ge=1, le=20)
    mode: Literal["lexical", "hybrid"] = "hybrid"
    max_context_tokens: int = Field(default=6000, gt=0)
    rerank: bool = True


class RetrievalHit(ContractModel):
    chunk_id: Id
    block_ids: List[BlockId] = Field(default_factory=list)
    anchor_ids: List[AnchorId] = Field(default_factory=list)
    media_ids: List[MediaId] = Field(default_factory=list)
    text: str = ""
    lexical_score: Optional[float] = None
    vector_score: Optional[float] = None
    rrf_score: float = 0.0
    rerank_score: Optional[float] = None
    rank: int = Field(default=0, ge=0)


class RetrievalResult(ContractModel):
    """空检索是 hits=[] 非异常。"""

    scope: Scope
    hits: List[RetrievalHit] = Field(default_factory=list)
    mode_used: Literal["lexical", "hybrid"] = "lexical"
    warnings: List[Warning] = Field(default_factory=list)
    elapsed_ms: int = 0


class IndexResult(ContractModel):
    scope: Scope
    chunk_count: int = Field(default=0, ge=0)
    vector_count: int = Field(default=0, ge=0)
    embedding_space: Optional[str] = None
    status: Literal["ready", "lexical_only", "failed"] = "lexical_only"
    warnings: List[Warning] = Field(default_factory=list)


__all__ = ["Chunk", "RetrievalRequest", "RetrievalHit", "RetrievalResult", "IndexResult"]
