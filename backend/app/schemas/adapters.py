"""M13 — 旧 DTO 投影适配器（REFACTOR_SPEC §5.10 末段、§5.11）。

严格签名（§5.10）：

    to_legacy_paper(paper, metadata, revision) -> PaperOut
    to_legacy_claim(claim, statement, evidence) -> ClaimOut
    to_legacy_graph(graph, statements) -> GraphOut
    to_legacy_presentation(presentation, media, evidence, statements) -> PresentationOut
    to_legacy_answer(answer) -> AskResponse
    to_legacy_evaluation(report) -> EvaluationOut

硬性兼容规则（§5.11）：
- 旧字段名/类型逐项保留，**绝不删**；可加与原 canonical 一致的新字段；
- 旧 ``evidence.id`` 继续**数字**，新 ID 放 ``evidence_id``；
- 旧 confidence 无法表达 null 时**投影 0 并新增 ``confidence_assessed:false``**；
- SUPPORTED 状态只投影 ``verified→SUPPORTED``，其余→``UNSUPPORTED``，新增
  ``verification_status``；
- **不为「兼容」保留错误的 grounded=true**；
- 旧 ``Figure.image_b64`` 保持可读并新增 ``image_mime``，**默认不悄悄改成 URL**；
- 兼容输出**不允许运行时 Any**：``content`` 收敛为 ``JSONScalar``，``steps`` 等
  仍允许旧宽松值（Any），但必须是可 JSON 序列化的旧有效值。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.contracts.artifacts import Asset, Media, MediaViewPolicy
from app.contracts.common import Scope
from app.contracts.documents import (
    LegacyMethodStep,
    LegacyPaperMetadata,
    PaperRecord,
    Revision,
)
from app.contracts.evaluation import EvaluationReport
from app.contracts.evidence import (
    ClaimRecord,
    EvidenceRecord,
    VerifiedStatement,
)
from app.contracts.graph import GraphArtifact
from app.contracts.qa import AnswerRecord
from app.contracts.scene import PresentationArtifact

from app.schemas.schemas import (
    AskResponse,
    ClaimOut,
    ClaimSummary,
    EvaluationOut,
    EvidenceOut,
    FigureOut,
    GraphOut,
    LegacyMethodStepOut,
    PaperDetail,
    PaperOut,
    PresentationOut,
    SceneOut,
    SectionOut,
    TableOut,
)


def _json_scalar(value: Any) -> Any:
    """把任意值收敛为 JSONScalar（string|number|bool|null）。

    旧单元格可能是 dict/None/数字；新契约要求 JSONScalar，前端做显式字符串转换。
    非标量一律 ``str()``，**绝不执行内容**。
    """
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    return str(value)


# ================================================================== 论文


def to_legacy_paper(
    paper: PaperRecord,
    metadata: LegacyPaperMetadata,
    revision: Optional[Revision] = None,
) -> PaperOut:
    """``PaperRecord + LegacyPaperMetadata (+ Revision) → PaperOut``。

    旧字段（id/slug/title/subtitle/authors/year/domain/abstract/tags/source_mode/
    status/map_summary/pdf_url/method_steps）**逐项保留**；新增 canonical 扩展字段。
    """
    return PaperOut(
        id=paper.id,
        slug=paper.slug,
        title=paper.title,
        subtitle=metadata.subtitle or "",
        authors=list(metadata.authors or []),
        year=int(metadata.year or 2026),
        domain=metadata.domain or "general",
        abstract=metadata.abstract or "",
        tags=list(metadata.tags or []),
        source_mode=paper.source_mode,
        status=paper.status,
        map_summary=dict(metadata.map_summary or {}),
        pdf_url=metadata.pdf_url or "",
        method_steps=[_legacy_step(s, i) for i, s in enumerate(metadata.method_steps or [])],
        # --- canonical 扩展（可选，不破坏旧消费者）---
        provenance_class=paper.provenance_class,
        revision_id=getattr(revision, "id", None),
        readable_revision_id=paper.readable_revision_id,
        published_revision_id=paper.published_revision_id,
        generation_status=_generation_status(paper),
    )


def _generation_status(paper: PaperRecord) -> str:
    """产物生成状态（不改变旧 status 语义，仅作新增提示）。"""
    if paper.published_revision_id:
        return "published"
    if paper.readable_revision_id:
        return "readable"
    return "pending"


def _legacy_step(step: Any, index: int = 0) -> LegacyMethodStepOut:
    """旧 method_steps 允许宽松 dict；保留旧有效值，非法条目降级为最小结构。

    §5.11 要求"保留旧有效值或输出逐项迁移警告，不能以新 DTO 验证导致整个旧详情 500"：
    - 旧数据普遍缺 ``id`` → 按序号补稳定占位 ``legacy-step-{i}``（不覆盖已有 id）；
    - ``figure_ref`` 只在已是 int 时保留，字符串/其他类型置 None（不猜数字）；
    - 非 dict 条目降级为最小结构，而非丢弃，避免改变旧响应的条目数。
    """
    if isinstance(step, LegacyMethodStep):
        data = step.model_dump()
    elif isinstance(step, dict):
        data = dict(step)
    else:
        data = {"id": str(step), "label": str(step)}
    return LegacyMethodStepOut(
        id=str(data.get("id") or f"legacy-step-{index}"),
        label=str(data.get("label") or ""),
        phase=data.get("phase"),
        detail=data.get("detail"),
        text=data.get("text"),
        figure_ref=data.get("figure_ref") if isinstance(data.get("figure_ref"), int) else None,
        # 与 figure_ref 同一纪律：只保留 int，字符串/其它类型一律丢弃（不猜编号）
        figure_refs=[n for n in (data.get("figure_refs") or []) if isinstance(n, int)],
        table_refs=[n for n in (data.get("table_refs") or []) if isinstance(n, int)],
        # 图表引用的**来源方法**（ADR-0059）：前端据此把"位置推断"与"题注匹配"分开标注。
        # 固定字段表**必须显式列出**，否则又会被静默丢弃（D-48 的教训）。
        figure_ref_methods={
            int(no): str(method)
            for no, method in (data.get("figure_ref_methods") or {}).items()
            if str(no).lstrip("-").isdigit()
        },
        color=data.get("color"),
    )


def to_legacy_detail(
    paper: PaperRecord,
    metadata: LegacyPaperMetadata,
    revision: Optional[Revision],
    *,
    sections: Optional[List[dict]] = None,
    figures: Optional[List[dict]] = None,
    tables: Optional[List[dict]] = None,
    pages: Optional[List[dict]] = None,
    accent: str = "#6366F1",
) -> PaperDetail:
    """``PaperDetail`` 投影：旧字段 + 空数组默认，逐项迁移警告。

    旧库中 ``content/steps/evidence_refs/linked`` 原本允许 Any：本函数**保留旧
    有效值**，遇到不可解析项输出 ``migration_warnings``，绝不让整个旧详情 500。
    """
    base = to_legacy_paper(paper, metadata, revision)
    warnings: List[str] = []
    # ``PaperOut`` 自身已含 ``method_steps``；若原样展开再显式传一次会
    # ``TypeError: got multiple values for keyword argument``。
    # 该函数此前**零调用**，所以这个冲突一直没暴露（详见 modules/papers/legacy.py）。
    base_dump = base.model_dump()
    base_dump.pop("method_steps", None)
    return PaperDetail(
        **base_dump,
        sections=[_section_out(s, warnings) for s in (sections or [])],
        figures=[_figure_out(f, warnings) for f in (figures or [])],
        tables=[_table_out(t, warnings) for t in (tables or [])],
        method_steps=[_legacy_step(s, i) for i, s in enumerate(metadata.method_steps or [])],
        pages=[
            {"page_no": int(p.get("page_no") or 0), "text": str(p.get("text") or "")}
            for p in (pages or [])
        ],
        accent=accent or "#6366F1",
        migration_warnings=warnings,
    )


def _section_out(raw: Any, warnings: List[str]) -> SectionOut:
    d = _as_dict(raw)
    return SectionOut(
        heading=str(d.get("heading") or ""),
        kind=str(d.get("kind") or "body"),
        page=int(d.get("page") or 1),
        summary=str(d.get("summary") or ""),
        body=str(d.get("body") or ""),
        key_points=[str(x) for x in (d.get("key_points") or [])],
        page_start=int(d.get("page_start") or 0),
        page_end=int(d.get("page_end") or 0),
    )


def _figure_out(raw: Any, warnings: List[str]) -> FigureOut:
    d = _as_dict(raw)
    glyph = d.get("glyph_svg")
    if glyph is not None and not isinstance(glyph, str):
        warnings.append("figure.glyph_svg 非字符串，已丢弃")
        glyph = ""
    return FigureOut(
        fig_no=int(d.get("fig_no") or 0),
        caption=str(d.get("caption") or ""),
        page=int(d.get("page") or 1),
        glyph_svg=glyph or "",
        image_b64=str(d.get("image_b64") or ""),
        image_mime=str(d.get("image_mime") or "image/png"),
        importance=str(d.get("importance") or "medium"),
        description=str(d.get("description") or ""),
        media_id=d.get("media_id"),
        image_url=str(d.get("image_url") or ""),
    )


def _table_out(raw: Any, warnings: List[str]) -> TableOut:
    d = _as_dict(raw)
    content_raw = d.get("content") or []
    content: List[List[Any]] = []
    if isinstance(content_raw, list):
        for row in content_raw:
            if isinstance(row, list):
                content.append([_json_scalar(c) for c in row])
            else:
                warnings.append("table.content 含非数组行，已转为单行字符串")
                content.append([_json_scalar(row)])
    else:
        warnings.append("table.content 非矩阵，已置空")
    html = d.get("table_html")
    if html is not None and not isinstance(html, str):
        warnings.append("table.table_html 非字符串，已置空")
        html = ""
    return TableOut(
        table_no=int(d.get("table_no") or 0),
        caption=str(d.get("caption") or ""),
        page=int(d.get("page") or 1),
        content=content,
        table_html=html or "",
        key_finding=str(d.get("key_finding") or ""),
        media_id=d.get("media_id"),
    )


def _as_dict(raw: Any) -> Dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if hasattr(raw, "model_dump"):
        try:
            return raw.model_dump()
        except Exception:  # noqa: BLE001
            return {}
    return {}


# ================================================================== 断言 / 证据


def _legacy_region_label(segment: Any) -> str:
    """``AnchorSegment`` → 旧 ``EvidenceOut.region`` 字符串。

    真实缺陷（2026-09-12 实测 ``GET /papers/1/claims/{id}`` **500**）：
    这里原本读 ``segment.block_id``，而 ``AnchorSegment`` 的字段是
    ``block_ids``（**列表**）—— ``AttributeError: 'AnchorSegment' object has no
    attribute 'block_id'``。该代码路径此前从未被执行（claims 详情对 canonical
    断言恒 404），所以一直没暴露。这里对两种历史形态都容忍，取不到就返回空串。
    """
    if segment is None:
        return ""
    single = getattr(segment, "block_id", None)
    if single:
        return str(single)
    block_ids = getattr(segment, "block_ids", None) or []
    if block_ids:
        return str(block_ids[0])
    page_label = getattr(segment, "page_label", None)
    return str(page_label) if page_label else ""


def to_legacy_evidence(record: EvidenceRecord) -> EvidenceOut:
    """旧 ``EvidenceOut``：``id`` 继续数字，新 ID 放 ``evidence_id``。"""
    legacy_id = record.legacy_id
    # 旧字段不接受任意字符串：不是 int 时置 None（新 ID 在 evidence_id）
    numeric_id = int(legacy_id) if isinstance(legacy_id, int) else None
    assessed = record.confidence is not None
    return EvidenceOut(
        id=numeric_id,
        page=int(record.source_page or 1),
        region=_legacy_region_label(record.source_region[0] if record.source_region else None),
        region_type="text",
        text=record.source_text or "",
        quote="".join(sp.source_text or "" for sp in (record.quote_spans or [])),
        # 旧契约无法表达 null：投影 0 并显式标注未评估
        confidence=float(record.confidence) if assessed else 0.0,
        # --- canonical 扩展 ---
        evidence_id=record.id,
        anchor_id=record.anchor_id,
        locator_status=record.locator_status,
        verification_status=record.support_status,
        media_ids=list(record.media_ids or []),
        confidence_assessed=assessed,
        confidence_method=record.confidence_method,
    )


def _status_to_legacy(claim: ClaimRecord) -> str:
    """SUPPORTED 状态只投影 ``verified→SUPPORTED``，其余→``UNSUPPORTED``。"""
    return "SUPPORTED" if claim.status == "verified" else "UNSUPPORTED"


def to_legacy_claim(
    claim: ClaimRecord,
    statement: Optional[VerifiedStatement],
    evidence: List[EvidenceRecord],
) -> ClaimOut:
    """``ClaimRecord + VerifiedStatement + EvidenceRecord[] → ClaimOut``。

    ``claim_id`` = 公开身份（非 DB 主键）；旧 ``id`` 用 ``legacy_id``。
    新增 ``verification_status`` 区分 contested/inference/unverified。
    """
    assessed = claim.confidence is not None
    return ClaimOut(
        id=int(claim.legacy_id) if isinstance(claim.legacy_id, int) else None,
        claim_id=claim.claim_id,
        statement=(statement.text if statement is not None else claim.rationale) or "",
        type=claim.type,
        confidence=float(claim.confidence) if assessed else 0.0,
        status=_status_to_legacy(claim),
        rationale=claim.rationale or "",
        evidence=[to_legacy_evidence(e) for e in (evidence or [])],
        # --- canonical 扩展 ---
        statement_id=claim.statement_id,
        verification_status=claim.status,
        visibility=claim.visibility,
        revision_id=claim.scope.revision_id,
        confidence_assessed=assessed,
        evidence_ids=list(claim.evidence_ids or []),
    )


def to_legacy_claim_summary(claim: ClaimRecord) -> ClaimSummary:
    assessed = claim.confidence is not None
    return ClaimSummary(
        claim_id=claim.claim_id,
        statement="",
        type=claim.type,
        confidence=float(claim.confidence) if assessed else 0.0,
        status=_status_to_legacy(claim),
        evidence_count=len(claim.evidence_ids or []),
        verification_status=claim.status,
        confidence_assessed=assessed,
    )


# ================================================================== 图谱


def to_legacy_graph(
    graph: GraphArtifact,
    statements: Optional[List[VerifiedStatement]] = None,
) -> GraphOut:
    """``GraphArtifact → GraphOut``：nodes/edges 字段名与旧前端一致。

    **不把 unsupported 变 supports**：边关系原样投影。
    """
    nodes = [
        {
            "id": n.id,
            "label": (n.label.text if n.label else ""),
            "kind": n.kind,
            "props": {
                "status": n.status,
                "claim_id": n.claim_id,
                "evidence_id": n.evidence_id,
                "media_id": n.media_id,
                "anchor_ids": list(n.anchor_ids or []),
            },
        }
        for n in graph.nodes
    ]
    edges = [
        {
            "id": e.id,
            "source": e.source,
            "target": e.target,
            "label": (e.label.text if e.label else e.relation),
            "relation": e.relation,
            "status": e.status,
        }
        for e in graph.edges
    ]
    return GraphOut(nodes=nodes, edges=edges, revision_id=graph.scope.revision_id)


# ================================================================== 讲解


def to_legacy_presentation(
    presentation: PresentationArtifact,
    media: Optional[List[Media]] = None,
    evidence: Optional[List[EvidenceRecord]] = None,
    statements: Optional[List[VerifiedStatement]] = None,
) -> PresentationOut:
    """``PresentationArtifact + Media/Evidence/Statements → PresentationOut``。

    ``figure_refs``/``table_refs`` 仍是**兼容整数**（来自 media.legacy_no），
    ``linked`` 只由 verified 媒体的 evidence 投影；无关联为空数组。
    """
    media_by_id = {m.id: m for m in (media or [])}
    evidence_by_id = {e.id: e for e in (evidence or [])}
    linked_evidence: List[EvidenceOut] = []
    for rid in list(evidence_by_id.keys()):
        linked_evidence.append(to_legacy_evidence(evidence_by_id[rid]))

    scenes: List[SceneOut] = []
    for scene in presentation.scenes:
        figure_refs: List[int] = []
        table_refs: List[int] = []
        linked: List[Dict[str, Any]] = []
        for mid in scene.media_ids or []:
            item = media_by_id.get(mid)
            if item is None:
                continue
            if isinstance(item.legacy_no, int):
                if item.kind == "table":
                    table_refs.append(item.legacy_no)
                elif item.kind == "figure":
                    figure_refs.append(item.legacy_no)
            linked.append({
                "type": "media" if item.kind == "figure" else item.kind,
                "media_id": item.id,
                "label": item.original_label or "",
                "caption": item.caption or "",
            })

        narration = scene.narration
        scenes.append(SceneOut(
            order=scene.order,
            title=scene.title.text if scene.title else "",
            kind=scene.kind,
            summary=scene.summary.text if scene.summary else "",
            steps=list(scene.step_ids or []),
            evidence_refs=list(scene.statement_ids or []),
            figure_refs=_dedup_ints(figure_refs),
            table_refs=_dedup_ints(table_refs),
            narration={
                "script": narration.script.text if narration else "",
                "tts_text": narration.tts_text.text if narration else "",
                "audio_url": (narration.audio_url if narration else None),
                "subtitle": [
                    {"id": c.id, "start_ms": c.start_ms, "end_ms": c.end_ms, "text": c.text.text}
                    for c in (narration.subtitle_cues if narration else [])
                ],
            },
            linked=linked,
            media_ids=list(scene.media_ids or []),
            statement_ids=list(scene.statement_ids or []),
        ))
    return PresentationOut(scenes=scenes, revision_id=presentation.scope.revision_id)


def _dedup_ints(values: List[int]) -> List[int]:
    out: List[int] = []
    for v in values:
        if v not in out:
            out.append(v)
    return out


# ================================================================== QA


def to_legacy_answer(answer: AnswerRecord) -> AskResponse:
    """``AnswerRecord → AskResponse``。**绝不把拒答标 grounded=true**。"""
    if not answer.text or not (answer.text.text or "").strip():
        grounded = False
    else:
        grounded = bool(answer.grounded)
    return AskResponse(
        answer=answer.text.text if answer.text else "",
        grounded=grounded,
        confidence=answer.confidence,
        evidence=[to_legacy_evidence(e) for e in (answer.evidence or [])],
        note=answer.note or "",
        mode=str(getattr(answer, "mode", "") or ""),   # general/abstained 前端要区分（ADR-0057）
    )


# ================================================================== 评测


def to_legacy_evaluation(report: EvaluationReport) -> EvaluationOut:
    """``EvaluationReport → EvaluationOut``：未评估**不冒充 0**（保留 null 标记）。

    ``proxy`` 指标**有值就如实给**（规格允许报告 proxy，只要求标明），
    与 ``modules/evaluation/legacy.py`` 保持同一口径——两处投影都填 0/null 才是真缺陷。
    """
    metrics: Dict[str, Any] = {}
    not_evaluated_names: List[str] = []
    not_evaluated_reasons: Dict[str, str] = {}
    proxy_names: List[str] = []
    for entry in report.metrics:
        value = entry.value
        if value.value is None or value.status == "not_evaluated":
            metrics[entry.name] = None
            not_evaluated_names.append(entry.name)
            # M10：把"为什么没测出来"一并给前端（此前只有名单，界面只能说"未评测"）
            not_evaluated_reasons[entry.name] = value.reason or "unspecified"
        elif value.status == "proxy":
            metrics[entry.name] = value.value
            proxy_names.append(entry.name)
        else:
            metrics[entry.name] = value.value
    canonical = report.overall_score
    metrics["overall_score_available"] = canonical is not None
    metrics["ai_overall_score"] = report.ai_overall_score
    metrics["ai_overall_score_available"] = report.ai_overall_score is not None
    metrics["overall_score_basis"] = (
        "human_annotated" if canonical is not None
        else ("ai_judge" if report.ai_overall_score is not None else None)
    )
    metrics["not_evaluated"] = not_evaluated_names
    metrics["not_evaluated_reasons"] = not_evaluated_reasons
    metrics["proxy"] = proxy_names
    metrics["golden_id"] = report.golden_id
    metrics["version"] = report.version
    metrics["warnings"] = [{"code": w.code, "message": w.message} for w in report.warnings]
    metrics["overall_score_canonical"] = canonical
    return EvaluationOut(
        # 未评估时给 **None**，不给 0.0（列已放宽可空，迁移 0008 / ADR-0055）
        overall_score=float(canonical) if canonical is not None else None,
        metrics=metrics,
    )


__all__ = [
    "to_legacy_paper",
    "to_legacy_detail",
    "to_legacy_claim",
    "to_legacy_claim_summary",
    "to_legacy_evidence",
    "to_legacy_graph",
    "to_legacy_presentation",
    "to_legacy_answer",
    "to_legacy_evaluation",
]
