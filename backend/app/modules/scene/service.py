"""M09 — 场景化讲解模块公共入口（REFACTOR_SPEC §5.5、§5.10、§6.11）。

公共函数：
- ``build(scope, structure: StructureArtifact, claims: ClaimRecord[], ctx) -> PresentationArtifact``
- ``get(scope) -> PresentationArtifact``

硬约束：
1. 只从**已验证** statements/claims 生成；unverified/inference 不进正文事实；
2. 媒体路径唯一：``scene → 已验证 statement → Claim/Evidence → verified Binding → Media``
   （通过 ``evidence.get_verified_media_for_claims``，只接受 ``state=verified``）；
3. 图号/印刷页字符串只作 ``legacy_candidate``，**不进入 verified linked**；
4. **无关联就显示无已验证媒体**，不生成看似合理的链接；
5. 无音频：``audio_url=null`` 且 ``SubtitleCue`` 两端为 null，不猜时间轴；
6. **GET 不调 LLM、不写库**；批量查询，不每 scene 开 Session。
"""
from __future__ import annotations

import hashlib
import json
import re
from typing import Dict, List, Optional, Sequence, Set, Tuple

from app.contracts.common import CallContext, Scope, Warning
from app.contracts.evidence import (
    ArtifactText,
    ClaimRecord,
    StatementSpan,
    StructureArtifact,
)
from app.contracts.scene import (
    NarrationRecord,
    PresentationArtifact,
    SceneRecord,
    SubtitleCue,
)
from app.core.db import session_scope
from app.core.errors import invalid_input, not_found, revision_mismatch

from . import narration as narr, repository as repo

#: 讲解构建算法版本
ALGORITHM_VERSION = "rl.scene/2"

#: 进入讲解正文的 display_class
_VERIFIED_CLASSES = {"verified_fact", "attributed_quote", "transition"}

#: 图号/表号/印刷页候选（仅作 legacy_candidate，不进 verified linked）
#: 支持 ``图 2`` / ``图 2(a)`` / ``Fig. 2`` / ``Figure 2`` / ``表 S1`` / ``Table S1``。
_FIG_RE = re.compile(
    r"(?:图|Fig\.?|Figure)\s*([0-9]+[A-Za-z]?(?:\([a-z0-9]+\))?)", re.I
)
_TABLE_RE = re.compile(
    r"(?:表|Table)\s*([A-Za-z]?[0-9]+[A-Za-z]?(?:\([a-z0-9]+\))?)", re.I
)
_PRINT_PAGE_RE = re.compile(r"\bp\.?\s*(\d{2,5})\b", re.I)

MAX_SCENES = 12
MAX_LINKED_MEDIA = 6


# =============================================================== build


def build(
    scope: Scope,
    structure: Optional[StructureArtifact] = None,
    claims: Optional[Sequence[ClaimRecord]] = None,
    ctx: Optional[CallContext] = None,
) -> PresentationArtifact:
    """由结构 + 已验证据构建讲解产物，并持久化一版快照。"""
    _require_scope(scope)
    warnings: List[Warning] = []

    # ---- 单次批读：claims / statements / bindings / media
    with session_scope() as db:
        claim_rows = repo.list_claims(db, scope.revision_id)
        statement_ids = [r.statement_id for r in claim_rows if r.statement_id]
        statement_rows = repo.list_statements(db, scope.revision_id, statement_ids)
        media_bindings = repo.list_media_bindings(db, scope.revision_id)

    statements_by_id = {row.id: row for row in statement_rows}
    claims_by_id = {row.claim_id: row for row in claim_rows}
    provided = list(claims or [])

    # ---- 已验证媒体通道（受控：只走 verified Binding）
    verified_media = _verified_media(scope, sorted(claims_by_id))
    verified_media_ids = {mid for mids in verified_media.values() for mid in mids}

    with session_scope() as db:
        media_rows = repo.list_media(db, scope.revision_id, sorted(verified_media_ids))
    media_by_id = {row.id: row for row in media_rows}

    if not media_bindings:
        warnings.append(Warning(
            code="no_verified_media_binding",
            message="该 revision 暂无媒体绑定；场景将显示无已验证媒体",
            stage="scene",
        ))

    scenes = _plan_scenes(
        scope, structure, claim_rows, statements_by_id, claims_by_id,
        verified_media, media_by_id, warnings,
    )

    artifact = PresentationArtifact(
        scope=scope, id=_presentation_id(scope.revision_id),
        scenes=scenes, warnings=warnings,
    )

    with session_scope() as db:
        repo.put_presentation_blob(
            db,
            blob_id=_blob_id(scope.revision_id),
            paper_id=scope.paper_id,
            revision_id=scope.revision_id,
            payload=artifact.model_dump(mode="json"),
            digest=_digest(artifact),
        )

    return artifact


def _plan_scenes(
    scope: Scope,
    structure: Optional[StructureArtifact],
    claim_rows: Sequence,
    statements_by_id: Dict[str, object],
    claims_by_id: Dict[str, object],
    verified_media: Dict[str, List[str]],
    media_by_id: Dict[str, object],
    warnings: List[Warning],
) -> List[SceneRecord]:
    """按结构章节分场景；**每条已验证 claim 至多归属一个场景**。

    归属优先级（全部确定性，不调 LLM）：
    1. 块级/span 链接——陈述引用的块落在本节 ``source_block_ids``/``anchor_ids``，
       或本节 ``summary.spans`` 直接引用该陈述；
    2. ``claim type ↔ 章节 kind``（kind 由中英文标题关键词推断）；
    3. 仍未归属的 claim 统一并入**一个**兜底场景。

    修复背景（真实缺陷 / ADR-0007）：第 3 步原本是 ``picked = all claim_rows``，
    于是把全部断言灌进**每一个** section——3 篇真实论文实测每个场景内容完全相同
    （paper 3 的 6 个场景各自塞进全部 15 条断言、summary 也相同），即"讲解乱"。
    现在的硬不变式是：断言不得在场景之间复制。
    """
    sections = list(getattr(structure, "sections", []) or []) if structure else []

    if not sections:
        warnings.append(Warning(
            code="no_structure",
            message="未提供结构产物，按断言类型生成骨架场景",
            stage="scene",
        ))
        return _skeleton_scenes(
            scope, claim_rows, statements_by_id, claims_by_id,
            verified_media, media_by_id, warnings,
        )

    window = sections[:MAX_SCENES]
    picks: List[List[object]] = [[] for _ in window]
    assigned: Set[str] = set()

    # ---- 阶段 1：块级/span 链接（唯一可信的一级归属）
    for idx, section in enumerate(window):
        block_ids = _section_block_ids(section)
        span_ids = _summary_statement_ids(getattr(section, "summary", None))
        if not (block_ids or span_ids):
            continue
        for row in claim_rows:
            if row.claim_id in assigned:
                continue
            statement = statements_by_id.get(row.statement_id)
            if statement is None:
                continue
            if _statement_belongs(statement, block_ids, span_ids):
                picks[idx].append(row)
                assigned.add(row.claim_id)

    # ---- 阶段 2：claim type ↔ 章节 kind（无链接线索时的确定性分流）
    for row in claim_rows:
        if row.claim_id in assigned:
            continue
        for idx, section in enumerate(window):
            if _claim_type_matches_section(row, _section_kind(section), section):
                picks[idx].append(row)
                assigned.add(row.claim_id)
                break

    # ---- 阶段 3：兜底——剩余 claim 并入一个场景，绝不复制到每个场景
    leftovers = [row for row in claim_rows if row.claim_id not in assigned]
    if leftovers:
        target = len(window) - 1
        for idx in range(len(window) - 1, -1, -1):
            if picks[idx]:
                target = idx
                break
        picks[target].extend(leftovers)
        warnings.append(Warning(
            code="unassigned_claims_fallback",
            message=(
                f"{len(leftovers)} 条已验证断言无章节归属线索，"
                f"已并入场景 {getattr(window[target], 'id', target)}"
            ),
            stage="scene",
        ))

    scenes = [
        _scene_from_section(
            scope, idx, section, picks[idx], statements_by_id, claims_by_id,
            verified_media, media_by_id, warnings,
        )
        for idx, section in enumerate(window)
    ]

    # 丢弃**没有任何已验证陈述**的场景：它们对观众只是噪音（"宁缺勿造"）。
    # 真实数据里断言多来自摘要/结果章，方法/背景章常常无断言，若不过滤会让
    # 讲解器出现大量空场景（实测 paper 1 有 7 个场景、其中 5 个为空）。
    # 全部为空时保留第一个，保证 presentation 不是空列表、前端有可渲染项。
    populated = [s for s in scenes if s.statement_ids]
    if not populated:
        return scenes[:1]
    return [
        (s if s.order == idx else s.model_copy(update={"order": idx}))
        for idx, s in enumerate(populated)
    ]


def _scene_from_section(
    scope: Scope,
    idx: int,
    section,
    picked: Sequence,
    statements_by_id: Dict[str, object],
    claims_by_id: Dict[str, object],
    verified_media: Dict[str, List[str]],
    media_by_id: Dict[str, object],
    warnings: List[Warning],
) -> SceneRecord:
    """由**已归属好的** claim 列表装配一个场景（归属逻辑见 ``_plan_scenes``）。"""
    section_id = getattr(section, "id", None) or f"sec:{idx}"
    heading = _text_of(getattr(section, "heading", "") or f"章节 {idx + 1}")
    scene_id = _scene_id(scope.revision_id, idx, section_id)
    return _assemble_scene(
        scope, scene_id, idx, kind=_section_kind(section), title=heading,
        summary=_text_of(getattr(section, "summary", None)),
        picked=picked, statements_by_id=statements_by_id, claims_by_id=claims_by_id,
        verified_media=verified_media, media_by_id=media_by_id, warnings=warnings,
        anchor_ids=list(getattr(section, "anchor_ids", []) or []),
    )


def _skeleton_scenes(
    scope: Scope,
    claim_rows: Sequence,
    statements_by_id: Dict[str, object],
    claims_by_id: Dict[str, object],
    verified_media: Dict[str, List[str]],
    media_by_id: Dict[str, object],
    warnings: List[Warning],
) -> List[SceneRecord]:
    """无结构时的骨架：按 claim type 分桶成 problem/method/result/limitation。"""
    buckets: List[Tuple[str, str, str]] = [
        ("problem", "CONTEXT", "研究问题"),
        ("method", "METHOD", "方法"),
        ("result", "RESULT", "结果"),
        ("limitation", "LIMITATION", "局限"),
    ]
    scenes: List[SceneRecord] = []
    for idx, (kind, claim_type, title) in enumerate(buckets):
        picked = [r for r in claim_rows if (r.type or "") == claim_type]
        if not picked:
            continue
        scene_id = _scene_id(scope.revision_id, idx, kind)
        scenes.append(_assemble_scene(
            scope, scene_id, idx, kind=kind, title=title, summary="",
            picked=picked, statements_by_id=statements_by_id, claims_by_id=claims_by_id,
            verified_media=verified_media, media_by_id=media_by_id,
            warnings=warnings, anchor_ids=[],
        ))
    return scenes


def _assemble_scene(
    scope: Scope,
    scene_id: str,
    order: int,
    *,
    kind: str,
    title: str,
    summary: str,
    picked: Sequence,
    statements_by_id: Dict[str, object],
    claims_by_id: Dict[str, object],
    verified_media: Dict[str, List[str]],
    media_by_id: Dict[str, object],
    warnings: List[Warning],
    anchor_ids: Sequence[str],
) -> SceneRecord:
    """从已验证陈述装配单个场景；无证据的 claim 不进正文事实。"""
    parts: List[Tuple[str, str]] = []
    statement_ids: List[str] = []
    claim_ids: List[str] = []
    media_ids: List[str] = []
    binding_ids: List[str] = []
    step_ids: List[str] = []

    for row in picked:
        statement = statements_by_id.get(row.statement_id)
        if statement is None:
            continue
        display_class = getattr(statement, "display_class", "unverified")
        if display_class not in _VERIFIED_CLASSES:
            # 未验证陈述不进讲解正文；有证据时降级为提示，无证据时静默跳过
            warnings.append(Warning(
                code="unverified_statement_skipped",
                message=f"陈述 {statement.id} 未通过验证（{display_class}），不进入讲解正文",
                stage="scene",
            ))
            continue
        text = (getattr(statement, "text", "") or "").strip()
        if not text:
            continue
        parts.append((statement.id, text))
        statement_ids.append(statement.id)
        claim_ids.append(row.claim_id)
        step_ids.append(f"{scene_id}:step:{len(step_ids)}")

        for mid in verified_media.get(row.claim_id, []):
            if mid in media_ids:
                continue
            media_ids.append(mid)
            binding_ids.append(f"b:{row.claim_id}:{mid}")

    # 只保留真实存在的 media（防止 dangling id）
    media_ids = [m for m in media_ids if m in media_by_id][:MAX_LINKED_MEDIA]

    if not parts:
        # 无已验证关联：显示无已验证媒体，不造假链接
        warnings.append(Warning(
            code="scene_without_verified_statement",
            message=f"场景「{title}」无已验证陈述，仅呈现空场景",
            stage="scene",
        ))
        rec = narr.empty_narration("", cue_id_prefix=scene_id)
        return SceneRecord(
            scope=scope, id=scene_id, order=order,
            title=ArtifactText(text=title),
            kind=kind,
            summary=ArtifactText(text=summary),
            step_ids=[], statement_ids=[], claim_ids=[], binding_ids=[],
            media_ids=[], narration=rec,
        )

    rec = narr.build_narration(parts, cue_id_prefix=scene_id)
    return SceneRecord(
        scope=scope, id=scene_id, order=order,
        title=ArtifactText(text=title),
        kind=kind,
        summary=ArtifactText(text=summary or _summary_from(parts)),
        step_ids=step_ids,
        statement_ids=statement_ids,
        claim_ids=_dedup(claim_ids),
        binding_ids=_dedup(binding_ids),
        media_ids=media_ids,
        narration=rec,
    )


# =============================================================== get


def get(scope: Scope) -> PresentationArtifact:
    """读取持久化讲解快照。**不调 LLM、不写库**。"""
    _require_scope(scope)

    with session_scope() as db:
        payload = repo.get_presentation_blob(db, scope.revision_id)

    if not payload:
        return PresentationArtifact(
            scope=scope, id=_presentation_id(scope.revision_id), scenes=[],
            warnings=[Warning(
                code="presentation_absent",
                message="该 revision 尚无讲解产物（未生成或已失效）",
                stage="scene",
            )],
        )

    try:
        artifact = PresentationArtifact.model_validate(payload)
    except Exception:  # noqa: BLE001  脏 payload 不阻断读取
        return PresentationArtifact(scope=scope, id=_presentation_id(scope.revision_id))

    if artifact.scope.revision_id != scope.revision_id:
        artifact = artifact.model_copy(update={"scope": scope})
    return artifact


# =============================================================== 媒体通道


def verified_media_for(scene: SceneRecord) -> List[str]:
    """场景已验证媒体 ID 列表（供前端/兼容层复用，不做任何推断）。"""
    return list(scene.media_ids or [])


def legacy_candidates(scene: SceneRecord) -> Dict[str, List[str]]:
    """图号/表号/印刷页**候选**（仅展示用，绝不进 verified linked）。"""
    blob = " ".join(
        [scene.title.text, scene.summary.text,
         scene.narration.script.text if scene.narration else ""]
    )
    return {
        "figure_labels": _dedup([m.group(0) for m in _FIG_RE.finditer(blob)]),
        "table_labels": _dedup([m.group(0) for m in _TABLE_RE.finditer(blob)]),
        "print_pages": _dedup([m.group(0) for m in _PRINT_PAGE_RE.finditer(blob)]),
    }


def _verified_media(scope: Scope, claim_ids: Sequence[str]) -> Dict[str, List[str]]:
    """受控通道：只接受 ``state=verified`` 的 Binding → Media。

    主通道走 ``evidence.get_verified_media_for_claims``（按 ``ClaimRecordORM.id``
    解析绑定）。历史数据里 ``BindingORM.from_id`` 也常直接存**公开 claim_id**
    （旧 IR 约定），因此这里额外按公开 id 直查一次并合并——
    仍然只接受 ``state=verified`` 且 ``relation=illustrates`` 的绑定，
    图号/印刷页字符串绝不在此路径产生结果。
    """
    if not claim_ids:
        return {}
    out: Dict[str, List[str]] = {cid: [] for cid in claim_ids}
    try:
        from app.modules import evidence as evidence_svc

        for cid, mids in evidence_svc.get_verified_media_for_claims(
            scope, list(claim_ids)
        ).items():
            for mid in mids:
                if mid not in out.setdefault(cid, []):
                    out[cid].append(mid)
    except Exception:  # noqa: BLE001  证据层不可用时不阻断讲解装配
        pass

    out = _merge_direct_claim_bindings(scope, out)
    return out


def _merge_direct_claim_bindings(
    scope: Scope, out: Dict[str, List[str]]
) -> Dict[str, List[str]]:
    """按公开 claim_id 直查 verified 媒体绑定（历史 IR 约定兼容）。"""
    try:
        with session_scope() as db:
            rows = repo.list_media_bindings(db, scope.revision_id)
    except Exception:  # noqa: BLE001
        return out
    for row in rows:
        if row.from_kind != "claim" or row.state != "verified":
            continue
        if row.relation not in ("illustrates", "shows", "depicts"):
            continue
        if row.from_id not in out:
            continue
        if row.to_id not in out[row.from_id]:
            out[row.from_id].append(row.to_id)
    return out


# =============================================================== 辅助


def _section_block_ids(section) -> Set[str]:
    """本节覆盖的原文块/anchor 集合（SectionRecord 的实际归属字段）。"""
    out: Set[str] = set()
    for key in ("source_block_ids", "anchor_ids"):
        for item in (getattr(section, key, []) or []):
            out.add(str(item))
    return out


def _summary_statement_ids(summary) -> Set[str]:
    """``summary.spans`` 引用的陈述 ID（章节→已验证陈述的次级归属线索）。"""
    out: Set[str] = set()
    for span in (getattr(summary, "spans", None) or []):
        sid = span.get("statement_id") if isinstance(span, dict) \
            else getattr(span, "statement_id", None)
        if sid:
            out.add(str(sid))
    return out


def _statement_belongs(statement, block_ids: Set[str], span_stmt_ids: Set[str]) -> bool:
    """陈述是否归属本节的唯一判据：引用块命中，或 summary.spans 直接引用。

    两者都为空时**不归属任何章节**（宁缺勿造，避免把全部断言塞进首节）。
    """
    if statement.id in span_stmt_ids:
        return True
    if not block_ids:
        return False
    return any(bid in block_ids for bid in (getattr(statement, "block_ids", None) or []))


#: 章节 kind → 允许进入该节的 claim type（无块级归属时的唯一线索）
_SECTION_CLAIM_TYPES: Dict[str, Set[str]] = {
    "intro": {"CONTEXT", "PROBLEM"},
    "problem": {"CONTEXT", "PROBLEM"},
    "method": {"METHOD"},
    "experiment": {"METHOD", "RESULT"},
    "result": {"RESULT"},
    "limitation": {"LIMITATION"},
}


#: 章节标题关键词 → kind。**顺序即优先级**（取第一个命中）：
#: 真实中文论文标题常同时含多个关键词（如"5 实验结果与分析"含"实验"+"结果"、
#: "6 有效性分析"含"有效性"+"分析"），故把更具体的判据排在前面。
#: 修复背景（ADR-0007）：此前只认英文关键词，6 个中文标题全被归为默认
#: ``intro``，导致 claim type 分流全部失配、进而触发"全量灌入每个场景"的兜底。
_SECTION_KIND_TOKENS: Tuple[Tuple[str, str], ...] = (
    # 引言 / 背景
    ("摘要", "intro"), ("引言", "intro"), ("概述", "intro"), ("绪论", "intro"),
    ("abstract", "intro"), ("introduction", "intro"),
    ("背景", "problem"), ("相关工作", "problem"), ("研究现状", "problem"),
    ("问题", "problem"), ("background", "problem"), ("related work", "problem"),
    ("problem", "problem"),
    # 方法 / 设计
    ("方法", "method"), ("设计", "method"), ("模型", "method"), ("算法", "method"),
    ("框架", "method"), ("实现", "method"), ("度量", "method"),
    ("method", "method"), ("approach", "method"), ("design", "method"),
    ("model", "method"), ("algorithm", "method"),
    # 实验 / 评估
    ("实验", "experiment"), ("评估", "experiment"), ("数据集", "experiment"),
    ("experiment", "experiment"), ("evaluation", "experiment"), ("dataset", "experiment"),
    # 局限 / 结论（须先于"分析/结果"，否则"有效性分析"会被误判为 result）
    ("有效性", "limitation"), ("局限", "limitation"), ("威胁", "limitation"),
    ("结论", "limitation"), ("总结", "limitation"), ("展望", "limitation"),
    ("limitation", "limitation"), ("threat", "limitation"),
    ("conclusion", "limitation"), ("future", "limitation"),
    # 结果 / 讨论
    ("结果", "result"), ("分析", "result"), ("讨论", "result"),
    ("result", "result"), ("discussion", "result"), ("analysis", "result"),
)

_SECTION_KINDS = ("intro", "problem", "method", "experiment", "result", "limitation")


def _section_kind(section) -> str:
    """推断章节 kind：契约 kind 优先，否则按标题中英文关键词（确定性、不调 LLM）。

    契约 kind 若是**未知值**（如 ``body``）则不强行归为 ``intro``——先试标题关键词，
    都不命中才保留契约原值，保证结构产物与场景的 kind 一致（否则同一章节在
    ``section_records`` 里是 ``body``、在场景里变成 ``intro``，评审会认为不一致）。
    """
    kind = (getattr(section, "kind", "") or "").lower()
    if kind in _SECTION_KINDS:
        return kind
    heading = (_text_of(getattr(section, "heading", "")) or "").lower()
    for token, mapped in _SECTION_KIND_TOKENS:
        if token in heading:
            return mapped
    return kind or "intro"


def _claim_type_matches_section(row, kind: str, section) -> bool:
    """章节 kind 是否接纳该 claim type。

    kind 已由 ``_section_kind`` 综合契约字段与标题关键词推断，故此处只查表，
    不再重复做标题关键词匹配（避免与 kind 判断不一致而把断言放进错的章节）。
    匹配到的仍是**已验证 claim**，不引入未验证内容。
    """
    allowed = _SECTION_CLAIM_TYPES.get(kind)
    return bool(allowed) and (getattr(row, "type", "") or "").upper() in allowed


def _text_of(value) -> str:
    if value is None:
        return ""
    return value if isinstance(value, str) else str(getattr(value, "text", "") or "")


def _summary_from(parts: Sequence[Tuple[str, str]]) -> str:
    first = parts[0][1] if parts else ""
    return first[:160]


def _dedup(items: Sequence[str]) -> List[str]:
    out: List[str] = []
    seen: Set[str] = set()
    for item in items:
        if item and item not in seen:
            seen.add(item)
            out.append(item)
    return out


def _scene_id(revision_id: str, idx: int, seed: str) -> str:
    return f"s:{revision_id[:8]}:{idx}:{abs(hash(seed)) % 10000}"


def _presentation_id(revision_id: str) -> str:
    return f"p:{revision_id}"


def _blob_id(revision_id: str) -> str:
    import uuid

    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"researchlens:presentation:{revision_id}"))


def _digest(artifact: PresentationArtifact) -> str:
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


__all__ = ["build", "get", "verified_media_for", "legacy_candidates", "ALGORITHM_VERSION"]
