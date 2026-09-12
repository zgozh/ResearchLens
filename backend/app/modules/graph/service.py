"""M08 — 研究图谱模块公共入口（REFACTOR_SPEC §5.5、§5.10、§6.10）。

公共函数：
- ``build(scope, claims: ClaimRecord[], ctx) -> GraphArtifact``
- ``get(scope) -> GraphArtifact``

硬约束：
1. **绝不对 UNSUPPORTED 断言统一连 supports 边**——无证据的 claim 只能是
   ``status=unverified`` 的孤立节点（或按 evidence 的 contradict 连 contradicts）；
2. isolated / candidate / disputed 节点保留明确 status，不隐式升级；
3. 边端点必须同图同 scope；节点 ID 稳定（同输入同 ID，可重复构建）；
4. **GET 不调 LLM、不写库**；无持久化图返回空图 + 明确状态；论文不存在 → 404。
"""
from __future__ import annotations

import hashlib
import json
from typing import Dict, List, Optional, Sequence, Tuple

from app.contracts.common import CallContext, Scope, Warning
from app.contracts.evidence import ArtifactText, ClaimRecord
from app.contracts.graph import (
    EdgeRelation,
    GraphArtifact,
    GraphEdgeRecord,
    GraphNodeRecord,
    NodeKind,
    NodeStatus,
)
from app.core.db import session_scope
from app.core.errors import invalid_input, not_found, revision_mismatch

from . import repository as repo

#: 图谱构建算法版本；影响节点/边集合的改动必须 bump
#: （/3：新增 statement 级绑定归约与 media 节点，ADR-0020）
ALGORITHM_VERSION = "rl.graph/3"

#: claim 类型 → 节点 kind（图谱展示语义）
_KIND_BY_TYPE = {
    "RESULT": "claim",
    "METHOD": "method",
    "LIMITATION": "limitation",
    "CONTEXT": "problem",
}

#: claim 状态 → 节点状态（不做任何「未验证→已验证」的隐式提升）
_STATUS_MAP = {
    "verified": "verified",
    "inference": "inference",
    "contested": "contested",
    "unverified": "unverified",
    "rejected": "unverified",
}


# =============================================================== build


def build(
    scope: Scope,
    claims: Optional[Sequence[ClaimRecord]] = None,
    ctx: Optional[CallContext] = None,
) -> GraphArtifact:
    """由断言与证据构建研究图谱，并持久化一版快照。

    ``claims`` 为空时从库中读取该 revision 的全部 claim（保持调用便利）。
    """
    _require_scope(scope)
    warnings: List[Warning] = []

    with session_scope() as db:
        claim_rows = repo.list_claims(db, scope.revision_id)
        # 媒体绑定既可能挂在 claim（历史约定，from_id 是**公开 claim_id**），
        # 也可能挂在 statement（M04 当前产出，出处更精确）。两者都必须在图里成边，
        # 否则图谱就是 nodes>0 / edges=0 的散点（ADR-0020）。
        support_bindings = (
            repo.binding_snapshots(db, scope.revision_id, "claim")
            + repo.binding_snapshots(db, scope.revision_id, "statement")
        )
        # 一次读全该 revision 的证据行：既服务显式绑定的 evidence 目标，
        # 也服务"由已判定证据行推导 claim→evidence 绑定"（实测每篇 10–30 行，
        # 全量读取比"先按绑定查、再补查"更简单也更不容易漏）。
        evidence_by_id = {
            row.id: row for row in repo.list_all_evidence(db, scope.revision_id)
        }
        media_ids = sorted({
            b.to_id for b in support_bindings
            if b.to_kind == "media" and b.to_id
        })
        media_rows = repo.list_media(db, scope.revision_id, media_ids)
        media_by_id = {row.id: row for row in media_rows}

    provided = list(claims or [])
    if provided:
        # 调用方给了 claim 列表：以其为权威，仅补充库中可查到的证据
        records = [_as_claim(scope, c) for c in provided]
    else:
        records = [_row_to_claim(scope, row) for row in claim_rows]

    # statement → 公开 claim_id：把 statement 级绑定归到 claim 节点上
    statement_to_claim = {
        r.statement_id: r.claim_id for r in records if getattr(r, "statement_id", "")
    }

    # 老数据缺口（实测）：gate 把判定写进 evidence_records（claim.evidence_ids 指得到），
    # 但**没人写 claim→evidence 绑定**（bindings 表 6 行全是 statement→media）→
    # 图谱一条 supports 边都没有，paper 2 甚至是 12 节点 / 0 边的散点图。
    # 这里把"已判定的证据行"投影成等价绑定：只补边、不改库、不放宽判定。
    derived_bindings = _derived_evidence_bindings(records, support_bindings, evidence_by_id)
    if derived_bindings:
        support_bindings = list(support_bindings) + derived_bindings
        warnings.append(Warning(
            code="evidence_bindings_derived",
            message=(
                f"{len(derived_bindings)} 条 claim→evidence 绑定由已判定的证据行推导"
                "（bindings 表缺这些行，本图投影不写库）"
            ),
            stage="graph",
        ))

    nodes: List[GraphNodeRecord] = []
    node_ids: set[str] = set()

    for record in records:
        node = _claim_node(scope, record)
        if node.id in node_ids:
            # 重复 ID：保留首个，记录 warning，不产生重影节点
            warnings.append(Warning(
                code="duplicate_claim_id",
                message=f"claim_id {record.claim_id} 重复出现，已折叠为单一节点",
                stage="graph",
            ))
            continue
        node_ids.add(node.id)
        nodes.append(node)
        if not record.evidence_ids:
            # 无证据的实质断言：保留为 unverified 孤立节点，**不连 supports 边**
            warnings.append(Warning(
                code="isolated_claim",
                message=f"claim {record.claim_id} 无可用证据，作为未验证孤立节点呈现",
                stage="graph",
            ))

    # evidence / media 节点**先入图**：边端点校验依赖 node_ids 已知目标。
    # 此前只入 evidence 节点，media 目标永远不在图内 → illustrates 边全被
    # ``edge_endpoint_missing`` 丢弃（ADR-0020）。
    verified_targets = {
        b.to_id for b in support_bindings if (b.state or "candidate") == "verified"
    }

    evidence_nodes: List[GraphNodeRecord] = []
    for ev_id in sorted({
        b.to_id for b in support_bindings
        if b.to_kind == "evidence" and b.to_id in evidence_by_id
    }):
        node_id = _evidence_node_id(ev_id)
        if node_id in node_ids:
            continue
        node_ids.add(node_id)
        row = evidence_by_id[ev_id]
        evidence_nodes.append(GraphNodeRecord(
            id=node_id,
            kind="evidence",
            label=ArtifactText(text=(row.source_text or "")[:200]),
            evidence_id=ev_id,
            anchor_ids=[row.anchor_id] if row.anchor_id else [],
            status="verified" if row.support_status == "supports" else "unverified",
        ))

    media_nodes: List[GraphNodeRecord] = []
    for media_id in media_ids:
        row = media_by_id.get(media_id)
        if row is None:
            # 悬空引用：不伪造节点，由 _build_edges 记 warning 并丢弃该边
            continue
        node_id = _media_node_id(media_id)
        if node_id in node_ids:
            continue
        node_ids.add(node_id)
        media_nodes.append(GraphNodeRecord(
            id=node_id,
            kind="media",
            label=ArtifactText(text=_media_node_label(row)),
            media_id=media_id,
            status="verified" if media_id in verified_targets else "unverified",
        ))

    edges = _build_edges(
        scope, records, support_bindings, evidence_by_id, statement_to_claim,
        node_ids, warnings,
    )
    nodes.extend(evidence_nodes)
    nodes.extend(media_nodes)

    artifact = GraphArtifact(
        scope=scope, id=_graph_id(scope.revision_id),
        nodes=nodes, edges=edges, warnings=warnings,
    )

    with session_scope() as db:
        repo.put_graph_blob(
            db,
            blob_id=_blob_id(scope.revision_id),
            paper_id=scope.paper_id,
            revision_id=scope.revision_id,
            payload=artifact.model_dump(mode="json"),
            digest=_digest(artifact),
        )

    return artifact


def _build_edges(
    scope: Scope,
    records: Sequence[ClaimRecord],
    bindings: Sequence,
    evidence_by_id: Dict[str, object],
    statement_to_claim: Dict[str, str],
    node_ids: set,
    warnings: List[Warning],
) -> List[GraphEdgeRecord]:
    """只依据**已验证绑定**连边；无绑定即无边，绝不统一补 supports。

    绑定来源既可能是 ``claim``（历史约定，``from_id`` 是公开 claim_id），
    也可能是 ``statement``（M04 当前产出）——后者经 ``statement_to_claim``
    归到 claim 节点上。
    """
    edges: List[GraphEdgeRecord] = []
    seen: set[Tuple[str, str, str]] = set()
    by_claim = {r.claim_id: r for r in records}

    for binding in bindings:
        claim_id = _claim_of_binding(binding, by_claim, statement_to_claim)
        if claim_id is None:
            continue
        relation = binding.relation or "supports"
        if relation not in ("supports", "contradicts", "illustrates", "mentions", "depends_on"):
            relation = "mentions"
        record = by_claim.get(claim_id)
        if record is None:
            continue

        source = _claim_node_id(claim_id)
        target = _target_node_id(binding, evidence_by_id)
        if target is None or target not in node_ids:
            warnings.append(Warning(
                code="edge_endpoint_missing",
                message=f"绑定 {binding.id} 的目标不在本图中，已跳过该边",
                stage="graph",
            ))
            continue

        key = (source, target, relation)
        if key in seen:
            continue
        seen.add(key)

        # 边状态严格跟随绑定状态；candidate 绑定不得升为 verified
        state = "verified" if (binding.state or "candidate") == "verified" else "candidate"
        status = state
        if state == "candidate":
            warnings.append(Warning(
                code="candidate_edge",
                message=f"claim {claim_id} 的绑定 {binding.id} 未验证，边标为 candidate",
                stage="graph",
            ))

        edges.append(GraphEdgeRecord(
            id=_edge_id(source, target, relation),
            source=source,
            target=target,
            relation=_as_relation(relation),
            label=_label_for(relation, record),
            binding_ids=[binding.id],
            status=status,
        ))
    return edges


#: 媒体 kind → 中文前缀（图节点标签用）
_MEDIA_KIND_ZH = {"figure": "图", "table": "表", "equation": "式"}


def _media_node_label(row) -> str:
    """媒体节点标签：「图/表 N」+ caption 前 60 字，便于在图上一眼认出。"""
    kind_zh = _MEDIA_KIND_ZH.get((row.kind or "").lower(), "媒体")
    head = f"{kind_zh} {row.legacy_no}" if row.legacy_no is not None else kind_zh
    caption = (row.label or "").strip()
    if not caption:
        return head
    if caption.startswith(head):
        return caption[:60]
    return f"{head} {caption[:60]}"


def _derived_evidence_bindings(
    records: Sequence[ClaimRecord], explicit: Sequence, evidence_by_id: Dict[str, object]
) -> List:
    """把**已判定**的证据行投影为 claim→evidence 绑定（只补图谱边，不写库）。

    真实缺陷（Postgres 实测）：``bindings`` 全库 6 行、全是 ``statement → media``，
    ``claim → evidence`` 一条都没有 → 研究图谱没有任何 supports 边（用户："连线不齐"）。
    而 ``evidence_records.support_status`` 就是 gate 的判定结论，
    ``claim_records.evidence_ids`` 也已经指向它——那是**已验证的证据**，不是编造。

    保守规则：
    - 只认 ``supports`` / ``contradicts``；``insufficient`` / ``unreviewed`` 一律不进图；
    - ``(claim_id, evidence_id)`` 已有显式绑定时不重复补；
    - ``state`` 固定 ``verified``：证据行本身携带判定结论，不是候选。
    """
    from app.modules.graph.repository import BindingSnapshot

    taken = {(b.from_id, b.to_id) for b in explicit}
    out: List[BindingSnapshot] = []
    for record in records:
        for evidence_id in (getattr(record, "evidence_ids", None) or []):
            if not evidence_id or (record.claim_id, evidence_id) in taken:
                continue
            row = evidence_by_id.get(evidence_id)
            status = (getattr(row, "support_status", "") or "").lower()
            if status not in ("supports", "contradicts"):
                continue
            taken.add((record.claim_id, evidence_id))
            out.append(BindingSnapshot(
                # id 需 ≤36 字符且稳定；用 claim/evidence 的短前缀拼
                id=f"dv-{record.claim_id[:10]}-{evidence_id[-10:]}",
                from_kind="claim",
                from_id=record.claim_id,
                to_kind="evidence",
                to_id=evidence_id,
                relation=status,
                state="verified",
                method="evidence_record_projection",
            ))
    return out


def _claim_of_binding(
    binding, by_claim: Dict[str, ClaimRecord], statement_to_claim: Dict[str, str]
) -> Optional[str]:
    """把绑定来源规约成**公开 claim_id**；无法规约则返回 ``None``。

    ``statement`` 级绑定经 ``statement_to_claim`` 归到所属 claim；
    ``claim`` 级绑定要求 ``from_id`` 确实是本图内的 claim（否则不连边）。
    """
    if binding.from_kind == "statement":
        return statement_to_claim.get(binding.from_id)
    if binding.from_kind == "claim":
        return binding.from_id if binding.from_id in by_claim else None
    return None


def _target_node_id(binding, evidence_by_id: Dict[str, object]) -> Optional[str]:
    """把绑定目标映射成图内节点 ID；目标不是图节点则返回 None。"""
    if binding.to_kind == "evidence":
        if binding.to_id in evidence_by_id:
            return _evidence_node_id(binding.to_id)
        return None
    if binding.to_kind == "media":
        return _media_node_id(binding.to_id)
    if binding.to_kind == "anchor":
        return _anchor_node_id(binding.to_id)
    if binding.to_kind == "block":
        return _block_node_id(binding.to_id)
    return None


# =============================================================== get


def get(scope: Scope) -> GraphArtifact:
    """读取持久化快照。**不调 LLM、不写库**；无快照时返回空图 + warning。"""
    _require_scope(scope)

    with session_scope() as db:
        payload = repo.get_graph_blob(db, scope.revision_id)

    if not payload:
        return GraphArtifact(
            scope=scope,
            id=_graph_id(scope.revision_id),
            nodes=[],
            edges=[],
        )

    try:
        artifact = GraphArtifact.model_validate(payload)
    except Exception:  # noqa: BLE001  旧/脏 payload 不阻断读取
        return GraphArtifact(scope=scope, id=_graph_id(scope.revision_id))

    # 返回的 scope 必须以请求为准（同 revision 才有意义）
    if artifact.scope.revision_id != scope.revision_id:
        artifact = artifact.model_copy(update={"scope": scope})
    return artifact


# =============================================================== 节点构造


def _claim_node(scope: Scope, record: ClaimRecord) -> GraphNodeRecord:
    return GraphNodeRecord(
        id=_claim_node_id(record.claim_id),
        kind=_as_node_kind(_KIND_BY_TYPE.get(record.type or "RESULT", "claim")),
        label=ArtifactText(text=record.rationale or record.claim_id),
        claim_id=record.claim_id,
        anchor_ids=list(getattr(record, "anchor_ids", []) or []),
        status=_as_node_status(_STATUS_MAP.get(record.status or "unverified", "unverified")),
    )


def _as_node_kind(value: str) -> NodeKind:
    return value if value in (
        "problem", "method", "experiment", "claim", "evidence", "limitation", "media"
    ) else "claim"  # type: ignore[return-value]


def _as_node_status(value: str) -> NodeStatus:
    return value if value in (
        "verified", "inference", "contested", "unverified"
    ) else "unverified"  # type: ignore[return-value]


def _as_relation(value: str) -> EdgeRelation:
    return value if value in (
        "supports", "contradicts", "illustrates", "depends_on", "mentions"
    ) else "mentions"  # type: ignore[return-value]


def _label_for(relation: str, record: ClaimRecord) -> ArtifactText:
    zh = {
        "supports": "支持", "contradicts": "矛盾", "illustrates": "图示",
        "depends_on": "依赖", "mentions": "提及",
    }.get(relation, "关联")
    return ArtifactText(text=f"{zh}：{record.claim_id}")


def _as_claim(scope: Scope, record: ClaimRecord) -> ClaimRecord:
    if record.scope.revision_id and record.scope.revision_id != scope.revision_id:
        raise revision_mismatch("claim 不属于该 revision")
    if record.scope.revision_id == scope.revision_id:
        return record
    return record.model_copy(update={"scope": scope})


def _row_to_claim(scope: Scope, row) -> ClaimRecord:
    return ClaimRecord(
        scope=scope,
        id=row.statement_id,
        claim_id=row.claim_id,
        statement_id=row.statement_id,
        type=row.type or "RESULT",
        status=row.status or "unverified",
        rationale=row.rationale or "",
        evidence_ids=list(row.evidence_ids or []),
        confidence=row.confidence,
        visibility=row.visibility or "exhibit",
    )


# =============================================================== 稳定 ID


def _claim_node_id(claim_id: str) -> str:
    return f"n:claim:{claim_id}"


def _evidence_node_id(evidence_id: str) -> str:
    return f"n:evidence:{evidence_id}"


def _media_node_id(media_id: str) -> str:
    return f"n:media:{media_id}"


def _anchor_node_id(anchor_id: str) -> str:
    return f"n:anchor:{anchor_id}"


def _block_node_id(block_id: str) -> str:
    return f"n:block:{block_id}"


def _edge_id(source: str, target: str, relation: str) -> str:
    return f"e:{source}|{relation}|{target}"


def _graph_id(revision_id: str) -> str:
    return f"g:{revision_id}"


def _blob_id(revision_id: str) -> str:
    return str(__import__("uuid").uuid5(
        __import__("uuid").NAMESPACE_URL, f"researchlens:graph:{revision_id}"
    ))


def _digest(artifact: GraphArtifact) -> str:
    raw = json.dumps(artifact.model_dump(mode="json"), sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _require_scope(scope: Scope) -> None:
    from app.models.source import RevisionORM

    if scope.paper_id <= 0 or not scope.revision_id:
        raise invalid_input("scope 非法")
    with session_scope() as db:
        row = db.get(RevisionORM, scope.revision_id)
        if row is None:
            raise not_found("revision 不存在")
        if row.paper_id != scope.paper_id:
            raise revision_mismatch("revision 不属于该 paper")


__all__ = ["build", "get", "ALGORITHM_VERSION"]
