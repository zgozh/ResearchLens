"""M07 — 可选向量通道（REFACTOR_SPEC §5.6）。

硬约束：**SQLite 必须纯词法可用**。云 embedding 不可用、超时或维度变化时，
一律返回空的向量通道 + warning，由 service 降级为 ``mode_used=lexical``，
**绝不中断检索，也绝不污染旧向量空间**。

向量空间 = ``model + dimension + normalization_version``；旧空间保持只读，
直到新空间完成写入，避免维度变化导致历史向量被错配。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

from app.contracts.ai import ModelSnapshot
from app.contracts.common import CallContext, Warning

from .lexical import cosine

#: 归一化版本参与空间名；改动归一化必须改这里
NORMALIZATION_VERSION = "l2v1"


def space_name(model: str, dimension: int, normalization: str = NORMALIZATION_VERSION) -> str:
    return f"{model}:{int(dimension)}:{normalization}"


@dataclass
class VectorChannel:
    """一路向量检索结果；``available=False`` 表示应降级到纯词法。"""

    available: bool
    space: Optional[str] = None
    hits: List[Tuple[str, float]] = None      # type: ignore[assignment]
    warnings: List[Warning] = None            # type: ignore[assignment]
    model: Optional[str] = None
    dimension: Optional[int] = None

    def __post_init__(self) -> None:
        if self.hits is None:
            self.hits = []
        if self.warnings is None:
            self.warnings = []


def embedding_space_for(snapshot: Optional[ModelSnapshot]) -> Optional[str]:
    if snapshot is None or not snapshot.embedding_model:
        return None
    dim = snapshot.embedding_dimension
    if not dim:
        return None
    return space_name(snapshot.embedding_model, int(dim))


def embed_query(
    query: str,
    snapshot: Optional[ModelSnapshot],
    ctx: Optional[CallContext],
) -> Tuple[Optional[List[float]], Optional[str], List[Warning]]:
    """尝试为查询取向量。**任何失败都返回 (None, None, warnings)**，不抛异常。"""
    from app.core.config import settings

    if snapshot is None or not snapshot.embedding_model:
        return None, None, [Warning(
            code="embedding_unavailable",
            message="未配置 embedding 模型，检索降级为纯词法",
            stage="retrieval",
        )]
    if not settings.has_llm:
        return None, None, [Warning(
            code="embedding_unavailable",
            message="模型服务未配置密钥，检索降级为纯词法",
            stage="retrieval",
        )]
    try:
        from app.modules import ai as ai_svc

        batch = ai_svc.embed([query], snapshot=snapshot, ctx=ctx)
    except Exception as exc:  # noqa: BLE001  依赖失败必须降级而非中断
        return None, None, [Warning(
            code="embedding_failed",
            message=f"embedding 调用失败，检索降级为纯词法：{type(exc).__name__}",
            stage="retrieval",
        )]
    vectors = list(getattr(batch, "vectors", []) or [])
    if not vectors:
        return None, None, [Warning(
            code="embedding_empty",
            message="embedding 返回空向量，检索降级为纯词法",
            stage="retrieval",
        )]
    vec = [float(x) for x in vectors[0]]
    space = space_name(
        getattr(batch, "model", None) or snapshot.embedding_model,
        getattr(batch, "dimension", None) or len(vec),
    )
    return vec, space, []


def search(
    query_vector: Optional[List[float]],
    space: Optional[str],
    vectors: Sequence[tuple],
    *,
    limit: int = 30,
) -> VectorChannel:
    """CPU 精确余弦（小规模可行；Postgres pgvector 可后续替换为 SQL）。"""
    if query_vector is None or not space:
        return VectorChannel(available=False)

    same_space = [v for v in vectors if getattr(v, "space", None) == space]
    if not same_space:
        return VectorChannel(
            available=False, space=space,
            warnings=[Warning(
                code="vector_space_missing",
                message="当前向量空间尚无索引（旧空间保持只读），本次降级为纯词法",
                stage="retrieval",
            )],
        )

    scored: List[Tuple[str, float]] = []
    for row in same_space:
        vector = list(getattr(row, "vector", []) or [])
        if len(vector) != len(query_vector):
            # 维度不一致的行直接跳过，不因个别脏行影响整路
            continue
        score = cosine(query_vector, vector)
        if score > 0.0:
            scored.append((row.chunk_id, score))
    scored.sort(key=lambda kv: (-kv[1], kv[0]))
    return VectorChannel(
        available=bool(scored), space=space, hits=scored[:limit],
        model=space.split(":")[0] if ":" in space else space,
        dimension=len(query_vector),
    )


def vectors_for_index(
    texts: Sequence[str],
    snapshot: Optional[ModelSnapshot],
    ctx: Optional[CallContext],
) -> Tuple[Dict[int, List[float]], Optional[str], List[Warning]]:
    """为待索引块批量取向量；失败时返回空 dict + warnings（索引仍算成功）。"""
    if not texts:
        return {}, None, []
    if snapshot is None or not snapshot.embedding_model:
        return {}, None, [Warning(
            code="embedding_unavailable",
            message="未配置 embedding 模型，仅建立词法索引",
            stage="retrieval",
        )]
    try:
        from app.modules import ai as ai_svc

        batch = ai_svc.embed(list(texts), snapshot=snapshot, ctx=ctx)
    except Exception as exc:  # noqa: BLE001
        return {}, None, [Warning(
            code="embedding_failed",
            message=f"embedding 调用失败，仅建立词法索引：{type(exc).__name__}",
            stage="retrieval",
        )]

    vectors = list(getattr(batch, "vectors", []) or [])
    if len(vectors) != len(texts):
        return {}, None, [Warning(
            code="embedding_count_mismatch",
            message="embedding 返回数量与输入不一致，仅建立词法索引",
            stage="retrieval",
        )]
    space = space_name(
        getattr(batch, "model", None) or snapshot.embedding_model,
        getattr(batch, "dimension", None) or (len(vectors[0]) if vectors else 0),
    )
    out: Dict[int, List[float]] = {}
    for idx, vec in enumerate(vectors):
        out[idx] = [float(x) for x in vec]
    return out, space, []


__all__ = [
    "NORMALIZATION_VERSION",
    "space_name",
    "VectorChannel",
    "embedding_space_for",
    "embed_query",
    "search",
    "vectors_for_index",
]
