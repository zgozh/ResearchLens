"""M06 — 断言、结构概览与方法步骤（REFACTOR_SPEC §6.8）。

硬约束（违反即视为重构失败）：
- **draft 永不直接成为 SUPPORTED**：claim 状态只由 M04 ``ValidationReport.decision`` 决定；
- public ``claim_id`` ≤32 字符且**同 revision 唯一**（碰撞必须重命名，不能覆盖）；
- ``ArtifactText.spans`` 必须**完整覆盖所有非空白文字**（不允许正文之外的"无引用副文案"）；
- unsupported 内容**不得**通过 ``Section.summary`` / key_points 泄漏为展项事实；
- ``MethodStepRecord.id`` 必填；
- 不直接修改 Page/Block；生成规模受预算限制并报告覆盖情况。
"""
from __future__ import annotations

import hashlib
import re
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

from app.contracts.common import CallContext, Scope, Warning
from app.contracts.evidence import (
    ArtifactText,
    ClaimBuildResult,
    ClaimDraftBatch,
    ClaimRecord,
    CitationCandidate,
    MapArtifact,
    MapItem,
    MethodStepRecord,
    SectionRecord,
    StatementDraft,
    StatementSpan,
    StructureArtifact,
    VerifiedStatement,
    display_class_for,
)
from app.core.errors import invalid_input, not_found, revision_mismatch
from app.core.db import session_scope
from app.core.security import settings
from app.models.source import new_id

from . import prompts
from . import repository as repo

#: 公开 claim_id 最大长度（契约硬约束）
MAX_CLAIM_ID = 32

_CLAIM_ID_SAFE_RE = re.compile(r"[^A-Za-z0-9_\-]")
_MULTISPACE_RE = re.compile(r"\s+")


# =============================================================== 工具


def _sanitize_claim_id(raw: str, fallback_seed: str = "") -> str:
    """清洗 claim_id：只保留安全字符并截断到 32 字符。"""
    cleaned = _CLAIM_ID_SAFE_RE.sub("_", (raw or "").strip())
    cleaned = cleaned.strip("_")
    if not cleaned:
        cleaned = "c_" + hashlib.sha256(fallback_seed.encode("utf-8")).hexdigest()[:16]
    return cleaned[:MAX_CLAIM_ID]


def _unique_claim_id(candidate: str, taken: Set[str]) -> str:
    """在同 revision 内保证唯一：碰撞则加稳定后缀，**绝不覆盖已有 claim**。"""
    base = candidate[:MAX_CLAIM_ID]
    if base not in taken:
        return base
    for i in range(1, 1000):
        suffix = f"_{i}"
        trimmed = base[: MAX_CLAIM_ID - len(suffix)] + suffix
        if trimmed not in taken:
            return trimmed
    digest = hashlib.sha256(candidate.encode("utf-8")).hexdigest()[:8]
    return (base[: MAX_CLAIM_ID - 9] + "_" + digest)[:MAX_CLAIM_ID]


def _covered_span_text(text: str, spans: Sequence[StatementSpan]) -> Tuple[bool, List[Tuple[int, int]]]:
    """检查 spans 是否完整覆盖所有非空白字符；返回 (覆盖完整?, 缺口区间)。"""
    n = len(text)
    covered = [False] * n
    for sp in spans:
        for i in range(max(0, sp.start_cp), min(n, sp.end_cp)):
            covered[i] = True
    gaps: List[Tuple[int, int]] = []
    start = -1
    for i, ch in enumerate(text):
        needs = not ch.isspace()
        if needs and not covered[i]:
            if start < 0:
                start = i
        else:
            if start >= 0:
                gaps.append((start, i))
                start = -1
    if start >= 0:
        gaps.append((start, n))
    return (not gaps), gaps


def build_artifact_text(text: str, statement_ids: Sequence[str]) -> ArtifactText:
    """把一段生成文本切成**完整覆盖**的 ArtifactText。

    策略：按传入的 statement 顺序均分文本（服务端决定 span 边界），
    保证所有非空白字符都被某个 span 覆盖——否则契约校验会失败。
    """
    raw = text or ""
    ids = [sid for sid in statement_ids if sid]
    if not raw:
        return ArtifactText(text="", spans=[])
    if not ids:
        # 没有任何 statement 支撑 → 不生成"无引用副文案"
        return ArtifactText(text="", spans=[])

    n = len(raw)
    per = max(1, n // len(ids))
    spans: List[StatementSpan] = []
    cursor = 0
    for idx, sid in enumerate(ids):
        start = cursor
        end = n if idx == len(ids) - 1 else min(n, start + per)
        # 让边界落在非空白与空白之间，避免把词切成两半（可读性，不影响覆盖）
        if end < n:
            while end < n and not raw[end].isspace() and not raw[end - 1].isspace():
                end += 1
        spans.append(StatementSpan(start_cp=start, end_cp=max(end, start + 1), statement_id=sid))
        cursor = spans[-1].end_cp
        if cursor >= n:
            break
    # 兜底：确保覆盖到末尾（把尾巴并入最后一段）
    if spans and spans[-1].end_cp < n:
        last = spans[-1]
        spans[-1] = StatementSpan(
            start_cp=last.start_cp, end_cp=n, statement_id=last.statement_id
        )
    # 去掉空段并保持不重叠
    cleaned: List[StatementSpan] = []
    last_end = -1
    for sp in spans:
        if sp.end_cp <= last_end or sp.end_cp <= sp.start_cp:
            continue
        cleaned.append(sp)
        last_end = sp.end_cp
    if not cleaned:
        return ArtifactText(text="", spans=[])
    return ArtifactText(text=raw, spans=cleaned)


def _artifact_text_from_claims(text: str, claim_ids: Sequence[str]) -> ArtifactText:
    """以 claim 为粒度切分 ArtifactText（summary/key_point 用）。

    ``StatementSpan.statement_id`` 语义是"这句话的归属陈述"；在结构概览里
    我们以 claim 的 statement_id 作为归属（claim ↔ statement 一一对应）。
    """
    return build_artifact_text(text, list(claim_ids))


# =============================================================== extract


def extract(
    scope: Scope, block_ids: Sequence[str], ctx: CallContext
) -> ClaimDraftBatch:
    """从原文块抽取**候选**陈述（LLM 只选 block_id 引用，服务端补页/校验）。

    无 LLM 或空论文 → 返回空 batch + 明确 warning，绝不抛依赖异常。
    """
    _require_scope(scope)
    warnings: List[Warning] = []
    ids = list(block_ids or [])

    with session_scope() as db:
        rows = repo.get_block_rows(db, scope.revision_id, ids or None)
        if not rows:
            warnings.append(Warning(
                code="empty_source", message="没有可用的原文块（origin=source_extraction）",
                stage="claims",
            ))
            return ClaimDraftBatch(scope=scope, drafts=[], warnings=warnings)
        corpus, block_index = _build_corpus(rows, warnings)

    if not settings.has_llm:
        warnings.append(Warning(
            code="llm_unavailable",
            message="未配置 LLM，无法抽取断言；返回候选空集而不是伪造结果",
            stage="claims",
        ))
        return ClaimDraftBatch(scope=scope, drafts=[], warnings=warnings)

    raw = _call_extraction(corpus, block_index, scope, ctx, warnings)
    drafts, extract_warnings = _draft_batch_from_raw(raw, scope, block_index)
    warnings.extend(extract_warnings)
    return ClaimDraftBatch(scope=scope, drafts=drafts, warnings=warnings)


#: 没有可识别标题时，整篇作为一个"章节"处理时的标签
_PREAMBLE_LABEL = "题名与摘要"

#: 每条语料条目的固定开销（"[B123] "）
_ENTRY_OVERHEAD = 12

#: **不进入语料**的页码/页眉/页脚类块：它们永远不可能成为断言的一级依据
#: （与解析层 ``mineru_adapter._META_KINDS`` 同一概念），实测却占掉
#: paper 1/2/3 语料的 22%(17/77)/24%/21% 预算。更糟的是模型会**引用页码或
#: 论文标题当证据**，被 gate 以 ``semantic_status=insufficient`` 拒掉 ——
#: fresh seed 实测 paper 1 的 6 条 claim 全部因此被拒、讲解为空（ADR-0025）。
#: 标题块仍保留（提供章节上下文）。
_NON_EVIDENCE_KINDS = frozenset({"header", "footer", "page_number", "page_footnote"})

#: 不进入语料的章节：参考文献/致谢产生不了断言，占份额纯属浪费预算，
#: 还会诱发模型去引用文献而非正文。实测 paper 1/2/3 的 ``References:``
#: 各占走 12/16/9 块（约 10% 预算）。
_SKIPPABLE_SECTION_RE = re.compile(
    r"^\s*(references?|bibliography|参考文献|引用文献|致谢|"
    r"acknowledge?ments?|funding)\s*[:：]?\s*$",
    re.I,
)


def _is_skippable_section(heading: str) -> bool:
    return bool(_SKIPPABLE_SECTION_RE.match((heading or "").strip()))


def _heading_groups(rows) -> List[Tuple[str, List]]:
    """按原文**一级标题**把文档序块切成章节；标题前的块并入第一节。

    复用与结构分节相同的 ``heading_body``（确定性、不调模型），
    保证「语料怎么分节」与「结构怎么分节」是同一套判据。
    参考文献/致谢类章节被剔除（见 ``_SKIPPABLE_SECTION_RE``）；若整篇都被
    剔除（异常输入），则保留原文，避免静默产出空语料。
    """
    groups: List[Tuple[str, List]] = []
    for row in rows:
        head = heading_body(row.text or "")
        if head:
            groups.append((head, [row]))
        else:
            if not groups:
                groups.append((_PREAMBLE_LABEL, []))
            groups[-1][1].append(row)
    non_empty = [(head, group) for head, group in groups if group]
    kept = [(head, group) for head, group in non_empty if not _is_skippable_section(head)]
    return kept or non_empty


def _nonblank(rows) -> List[Tuple[object, str]]:
    """(row, 去空白文本) 列表；跳过空白块与页码/页眉/页脚类块。

    排除后者见 ``_NON_EVIDENCE_KINDS``：白占预算，且会被模型当引文。
    """
    out: List[Tuple[object, str]] = []
    for row in rows:
        if (getattr(row, "kind", "") or "").lower() in _NON_EVIDENCE_KINDS:
            continue
        text = (row.text or "").strip()
        if text:
            out.append((row, text))
    return out


def _sample_group(group_rows, share: int) -> List[Tuple[object, str]]:
    """在 ``share`` 字符内挑块：够放则全取；超份额则**均匀取样**。

    - 标题块**优先保留**（给模型章节上下文，本身几乎不产生断言）；
    - 正文块**均匀取样**（首块与末块必取）——长章节的关键断言可能在中间或末尾，
      "每节只看到开头"会重演"只读头部"那类覆盖缺口（ADR-0022）。
    """
    items = _nonblank(group_rows)
    if not items:
        return []
    total = sum(len(text) + _ENTRY_OVERHEAD for _, text in items)
    if total <= share:
        return items

    head = items[0] if heading_body(items[0][1]) else None
    body = items[1:] if head else items
    if not body:
        return [head] if head else []

    body_share = max(0, share - ((len(head[1]) + _ENTRY_OVERHEAD) if head else 0))
    body_total = sum(len(text) + _ENTRY_OVERHEAD for _, text in body)

    if body_total <= body_share:
        picked_body = body
    else:
        n = len(body)
        average = body_total / n
        keep = max(2, min(int(body_share // max(1.0, average)), n))
        if keep >= n:
            picked_body = body
        else:
            idxs = sorted({int(round(i * (n - 1) / (keep - 1))) for i in range(keep)})
            picked_body = [body[i] for i in idxs]

    return ([head] if head else []) + picked_body


def _build_corpus(rows, warnings: List[Warning]) -> Tuple[str, Dict[str, Tuple[str, str]]]:
    """按**章节公平分配预算**拼正文，并返回短编号索引（ADR-0022）。

    返回 ``block_index``：短编号（如 ``B1``）→ ``(uuid, text)``。
    用短编号而非 36 字符 UUID，避免 LLM 拒绝复制长 UUID 导致 quotes 为空。

    分配规则（确定性，不调模型）：

    - 用 ``heading_body`` 按原文一级标题分章节（标题前的块并入第一节）；
    - 每节份额 = ``min(PER_SECTION_CHAR_BUDGET, 剩余预算 / 剩余节数)``，
      保证**每一节都有内容**、总量不超 ``TOTAL_CHAR_BUDGET``；
    - 节内容超过份额时**均匀取样**（首块与末块必取）；
    - 被截断的章节**逐一点名**（``section_truncated``），否则覆盖缺口不可见。

    修复背景：原实现按文档顺序累加到 ``TOTAL_CHAR_BUDGET`` 就 ``break``，
    等于"只读头部"——实测 paper 3 只有前 29% 正文（页 0..6 / 共 25 页）进入模型，
    方法章与实验章完全缺席，直接导致 ``method_steps=0`` 与场景只剩 1 个。
    """
    groups = _heading_groups(rows)
    if not groups:
        return "", {}

    parts: List[str] = []
    block_index: Dict[str, Tuple[str, str]] = {}
    remaining = prompts.TOTAL_CHAR_BUDGET
    ordinal = 0
    truncated: List[str] = []
    budget_limited = False

    for idx, (heading, group_rows) in enumerate(groups):
        sections_left = len(groups) - idx
        share = min(prompts.PER_SECTION_CHAR_BUDGET, remaining // max(1, sections_left))
        if share <= 0:
            truncated.append(heading)
            continue
        if share < prompts.PER_SECTION_CHAR_BUDGET:
            budget_limited = True

        picked = _sample_group(group_rows, share)
        used = 0
        for row, text in picked:
            candidate = f"[B{ordinal + 1}] {text}"
            if used + len(candidate) > share:
                break
            ordinal += 1
            parts.append(candidate)
            block_index[f"B{ordinal}"] = (row.id, text)
            used += len(candidate)
        if len(picked) < len(_nonblank(group_rows)):
            truncated.append(heading)
        remaining = max(0, remaining - used)

    if truncated:
        warnings.append(Warning(
            code="section_truncated",
            message=("以下章节内容超出分配份额，已按均匀取样截断（覆盖受限）："
                     + "、".join(truncated)),
            stage="claims",
        ))
    if budget_limited:
        warnings.append(Warning(
            code="budget_truncated",
            message=(f"总预算 {prompts.TOTAL_CHAR_BUDGET} 字符不足以让每节都拿到 "
                     f"{prompts.PER_SECTION_CHAR_BUDGET} 字符，已按剩余量公平分配"),
            stage="claims",
        ))
    return "\n".join(parts), block_index


def _call_extraction(
    corpus: str, block_index: Dict[str, str], scope: Scope,
    ctx: CallContext, warnings: List[Warning],
):
    """调用 LLM 抽取；失败降级为 warning + 空候选（不抛依赖异常）。"""
    try:
        from app.contracts.ai import ChatMessage, CompletionRequest
        from app.modules import ai as ai_module

        result = ai_module.complete(
            CompletionRequest(
                messages=[
                    ChatMessage(role="system", content=prompts.CLAIM_EXTRACTION_PROMPT),
                    ChatMessage(role="user", content=corpus),
                ],
                output_schema=prompts._ClaimExtraction,
                max_output_tokens=4096,
            ),
            ctx,
        )
    except Exception as exc:  # noqa: BLE001 —— 云调用失败必须降级而非中断流水线
        warnings.append(Warning(
            code="llm_failed", message=f"断言抽取调用失败，已降级：{exc}", stage="claims",
        ))
        return None
    return result.value


def _trimmed_across_blocks(locator_mod, proposed_quote: str, block_index, uuid, block_text):
    """在块集合里找"最长逐字子串"（模型给引文套了非原文前后缀时）。

    先试模型自报的那个块，再按语料顺序试其余块；取第一个能产生 span 的结果。
    """
    first = locator_mod.match_quote_trimmed(
        block_id=uuid, text=block_text, proposed_quote=proposed_quote
    )
    if first is not None and first.span is not None:
        return first
    for other_uuid, other_text in block_index.values():
        if other_uuid == uuid:
            continue
        hit = locator_mod.match_quote_trimmed(
            block_id=other_uuid, text=other_text, proposed_quote=proposed_quote
        )
        if hit is not None and hit.span is not None:
            return hit
    return None


def _draft_batch_from_raw(
    raw, scope: Scope, block_index: Dict[str, Tuple[str, str]]
) -> Tuple[List[StatementDraft], List[Warning]]:
    """把模型输出转成受控 StatementDraft 候选（服务端补页、校验引用）。"""
    warnings: List[Warning] = []
    if raw is None:
        return [], warnings
    items = getattr(raw, "claims", None)
    if items is None and isinstance(raw, dict):
        items = raw.get("claims")
    if not isinstance(items, list):
        warnings.append(Warning(
            code="schema_mismatch", message="抽取结果不是合法结构，已忽略", stage="claims",
        ))
        return [], warnings

    drafts: List[StatementDraft] = []
    taken: Set[str] = set()
    for item in items:
        obj = item if isinstance(item, dict) else item.model_dump() if hasattr(item, "model_dump") else None
        if not obj:
            continue
        statement = str(obj.get("statement") or "").strip()
        if not statement:
            continue
        claim_id = _unique_claim_id(
            _sanitize_claim_id(str(obj.get("claim_id") or ""), fallback_seed=statement),
            taken,
        )
        taken.add(claim_id)

        citations: List[CitationCandidate] = []
        for quote in (obj.get("quotes") or []):
            q = quote if isinstance(quote, dict) else getattr(quote, "model_dump", lambda: {})()
            short_id = str(q.get("block_id") or "").strip()
            if short_id not in block_index:
                warnings.append(Warning(
                    code="unknown_block",
                    message=f"模型引用了不存在的 block {short_id}，已丢弃该引用（服务端不补页）",
                    stage="claims",
                ))
                continue
            uuid, block_text = block_index[short_id]
            cite_quote = (q.get("quote") or "").strip()
            if not cite_quote:
                # 以前这里是**静默 continue**：模型没给引用这件事在 warning 里完全
                # 看不到（ADR-0022 记录的观测性缺口）。现在显式报告。
                warnings.append(Warning(
                    code="quote_missing",
                    message=f"block {short_id} 的引用为空，已丢弃该引用",
                    stage="claims",
                ))
                continue
            # 复用 M04 的定位器（精确 → 规范化 → 空白无关 → 模糊），而不是自己做
            # 精确子串比较：MinerU 排版插空格/全角/连字会让**真实存在**的引用被误判
            # 为"不在原文中"丢弃（实测 paper 2 一轮 12 条 claim 里 8 条因此变成
            # "证据原文为空"、全被 gate 拒）。命中后回填**原文真实切片**，不伪造 quote。
            from app.modules.evidence import locator as locator_mod

            matched = locator_mod.match_quote_text(
                block_id=uuid, text=block_text, proposed_quote=cite_quote
            )
            if matched.span is None:
                # 跨块纠错（ADR-0040）：模型报的块号可能错位（MinerU 把一段话拆进相邻块、
                # 跨页、表题与表体相邻），而引文本身**逐字存在**于别的块里。实测 paper 2
                # 一轮 12 条断言里 8 条报 quote_not_in_block，其中相当一部分并非编造。
                # 只在**本次语料覆盖的块**里找，且只认能产生 QuoteSpan 的档位（不含 fuzzy）。
                recovered = locator_mod.match_quote_across_blocks(
                    proposed_quote=cite_quote,
                    blocks=[(v[0], v[1]) for v in block_index.values()],
                )
                if recovered is None or recovered.span is None:
                    # 最后一道：引文**逐字存在**但被套了非原文前后缀（实测 paper 2：
                    # 模型在原文句子前加了 "Download Percentile (i) = "）。
                    # 只取最长逐字子串，且要求够长且占引文比例够高；译文仍会被拒。
                    recovered = _trimmed_across_blocks(
                        locator_mod, cite_quote, block_index, uuid, block_text
                    )
                if recovered is not None and recovered.span is not None:
                    corrected_short = next(
                        (k for k, v in block_index.items() if v[0] == recovered.block_id), "?"
                    )
                    warnings.append(Warning(
                        code="quote_block_corrected" if recovered.kind != "trimmed" else "quote_trimmed",
                        message=(
                            f"引用报的是 block {short_id}，实际逐字命中 block "
                            f"{corrected_short}（{recovered.kind}），已按原文纠正"
                        ),
                        stage="claims",
                    ))
                    citations.append(CitationCandidate(
                        block_id=recovered.block_id,
                        proposed_quote=recovered.span.source_text,
                    ))
                    continue
                warnings.append(Warning(
                    code="quote_not_in_block",
                    message=(
                        f"引用不在 block {short_id} 原文中、也不在本次语料任何块中，"
                        f"已丢弃（{matched.kind}）"
                    ),
                    stage="claims",
                ))
                continue
            citations.append(CitationCandidate(
                block_id=uuid, proposed_quote=matched.span.source_text,
            ))

        drafts.append(StatementDraft(
            scope=scope,
            id=f"stmt-{hashlib.sha256((scope.revision_id + '|' + claim_id).encode()).hexdigest()[:24]}",
            claim_id=claim_id,
            text=statement,
            kind="fact",
            citations=citations,
            qualifiers=[str(q) for q in (obj.get("qualifiers") or [])],
        ))
    return drafts, warnings


# =============================================================== register


def reextract(scope: Scope, ctx: CallContext) -> ClaimBuildResult:
    """**重新抽取**：先清掉该 revision 的断言派生数据，再按当前语料重跑抽取与落库。

    为什么需要它（ADR-0022）：``upsert_claim`` 以 ``(revision_id, claim_id)`` 为键、
    ``upsert_statement`` 以 statement id 为键，而 claim_id 由**模型输出**决定——
    换一份语料（例如把"只读头部"改成"按章节分配"）必然产生一批新 id，
    旧行不会被覆盖，而是**残留成孤儿**：新旧 claim 同时挂在同一 revision 上，
    图谱与讲解会看到两套。所以重抽取必须显式清理。

    审计：清理行数写进 ``reextract_reset`` 警告，避免"悄悄清库"。
    仅用于运维/重建路径，**不接入正常 ingest 流水线**。
    """
    _require_scope(scope)
    with session_scope() as db:
        removed = repo.delete_claim_artifacts(db, scope.revision_id)

    batch = extract(scope, [], ctx)
    built = verify_and_store(batch, ctx)

    warnings = [
        Warning(
            code="reextract_reset",
            message=(
                "重抽取前已清理该 revision 的断言派生数据（"
                + "、".join(f"{k}={v}" for k, v in removed.items()) + "）"
            ),
            stage="claims",
        )
    ]
    # **必须重建 media 绑定**：清理阶段把 ``bindings`` 一起删了（它是断言派生物），
    # 而 statement→media 的 ``illustrates`` 边正是图谱"断言↔图表"与讲解"关联图表"的来源。
    # 不重建的后果实测：重抽取后 paper 1 的 bindings 由 6 条变 0 条，图谱的
    # illustrates 边整块消失（只剩 supports），前端"关键图表"关联断掉。
    # 绑定失败只记告警：它是派生增强，不该让重抽取整体失败。
    try:
        from app.modules import evidence as evidence_mod

        rebound = evidence_mod.bind_media_for_statements(
            scope, list(built.statements or []), ctx
        )
        warnings.append(Warning(
            code="media_bindings_rebuilt",
            message=f"重抽取后已重建 statement→media 绑定 {len(rebound)} 条（清理阶段删除了旧绑定）",
            stage="claims",
        ))
    except Exception as exc:  # noqa: BLE001 - 派生增强失败不得中断重抽取
        warnings.append(Warning(
            code="media_bindings_rebuild_failed",
            message=f"重抽取后媒体绑定重建失败，图谱关联图表可能缺失：{type(exc).__name__}",
            stage="claims",
        ))
    # **deadline 陷阱**（ADR-0026）：``new_ctx()`` 默认只有 120s，而真实作业由
    # ``pipeline.service`` 按 ``budget.max_wall_ms``（默认 600s）设置。重抽取要跑
    # 「一次抽取 + 每条陈述一次语义判定」，用 120s 会中途过期——语义判定全部降级为
    # "未判定"，于是**所有 claim 变成 unverified**，看起来像"这篇论文没有可验证断言"。
    # 这里把它显式报出来，避免再次被误读成内容质量问题。
    if ctx is not None and getattr(ctx, "deadline_at", None) is not None:
        from app.core.clock import is_expired

        if is_expired(ctx.deadline_at):
            warnings.append(Warning(
                code="reextract_deadline_exceeded",
                message=(
                    "重抽取期间全局 deadline 已过期，语义判定可能已降级为未判定——"
                    "结果偏悲观；请用作业级 deadline（budget.max_wall_ms）重试"
                ),
                stage="claims",
            ))
    return built.model_copy(update={"warnings": warnings + list(built.warnings or [])})


def register_statement(
    draft: StatementDraft, visibility: str, ctx: CallContext
) -> ClaimRecord:
    """注册陈述身份：**只建立 unverified 身份**，不产生任何 evidence。

    scene/QA 的新事实必须先注册再校验；拒绝绕过注册直接插 evidence。
    """
    if not isinstance(draft, StatementDraft):
        raise invalid_input("draft 必须为 StatementDraft", field="draft")
    if visibility not in ("exhibit", "answer_only"):
        raise invalid_input("visibility 只能是 exhibit|answer_only", field="visibility")
    _require_scope(draft.scope)

    claim_id = _sanitize_claim_id(draft.claim_id, fallback_seed=draft.id)
    if not claim_id:
        raise invalid_input("claim_id 不能为空", field="claim_id")

    with session_scope() as db:
        existing = repo.get_claim_row(db, draft.scope.revision_id, claim_id)
        if existing is not None and existing.statement_id != draft.id:
            raise invalid_input(
                f"claim_id {claim_id} 已被占用（同 revision 必须唯一）", field="claim_id",
            )
        repo.upsert_statement(db, draft, origin="generated", display_class="unverified")
        record = ClaimRecord(
            scope=draft.scope,
            id=existing.id if existing else new_id(),
            legacy_id=existing.legacy_id if existing else None,
            claim_id=claim_id,
            statement_id=draft.id,
            type="RESULT",
            status="unverified",
            rationale="",
            evidence_ids=[],
            confidence=None,
            visibility=visibility,
        )
        repo.upsert_claim(db, record)
        repo.audit(
            # 审计 actor 用 ``getattr`` 兜底：``ctx`` 声明为非可选，但调用方一旦传 None
            # 就会 AttributeError，把整条"注册陈述"链路打成 gate_unavailable
            # （真实事故：QA 因此永远拿不到句子 → 拒答）。宁可用 "system"，不要炸。
            db, kind="statement_registered", scope=draft.scope,
            actor=getattr(ctx, "request_id", "") or "system",
            payload={"claim_id": claim_id, "statement_id": draft.id, "visibility": visibility},
        )
        return record


def verify_registered_statement(
    draft: StatementDraft, report: Any, visibility: str, ctx: CallContext
) -> Optional[VerifiedStatement]:
    """把 gate 报告落库到**已注册**的陈述上：证据 + ``display_class`` + claim 状态。

    为什么必须有这个入口（真实缺陷）：``register_statement`` 契约上**只建立
    unverified 身份、不产生任何 evidence**。QA 的 ``answer_only`` 事实句此前只调了
    ``register_statement`` 就去看 ``display_class`` —— 于是每一句都停在
    ``unverified`` → 句子全被丢弃 → 整题判"无可用证据"并**拒答**（用户看到空气泡）。
    ``verify_and_store`` 内部早就有这套动作，这里把它抽成可单独调用的公共入口，
    供"先注册、后校验"的调用方（QA / 复核）复用，避免再各写一遍而漏步骤。
    """
    from app.modules import evidence as evidence_mod

    if report is None:
        return None
    saved = evidence_mod.save_report(report, ctx)
    evidence_ids = [ev.id for ev in (saved.evidence or [])]

    with session_scope() as db:
        repo.update_statement_validation(
            db, draft.id,
            validation=saved.model_dump(mode="json"),
            evidence_ids=evidence_ids,
            display_class=display_class_for(draft, saved),
        )
        claim = ClaimRecord(
            scope=draft.scope,
            id=_claim_row_id(db, draft.scope, draft.claim_id),
            claim_id=draft.claim_id,
            statement_id=draft.id,
            type=_claim_type_for(draft),
            status=_status_for(saved),
            rationale="",
            evidence_ids=evidence_ids,
            confidence=saved.confidence,
            visibility=visibility,
        )
        repo.upsert_claim(db, claim)

    stored = get_statements(draft.scope, [draft.id])
    return stored[0] if stored else None


# =============================================================== verify_and_store


def verify_and_store(batch: ClaimDraftBatch, ctx: CallContext) -> ClaimBuildResult:
    """跑 M04 gate 并保存最终状态（**短事务**；云调用不在写事务内）。

    - draft 永不直接 SUPPORTED：状态 = gate decision 的映射；
    - evidence 的 source_text 由 M04 服务端从原文拼接；
    - 生成文字全部注册 statements。
    """
    if not isinstance(batch, ClaimDraftBatch):
        raise invalid_input("batch 必须为 ClaimDraftBatch", field="batch")
    scope = batch.scope
    _require_scope(scope)

    from app.modules import evidence as evidence_mod

    warnings: List[Warning] = list(batch.warnings)

    # ---------- 阶段一：无写事务地跑 gate（可能含云调用） ----------
    reports: List[Tuple[StatementDraft, object]] = []
    for draft in batch.drafts:
        try:
            report = evidence_mod.validate(draft, ctx)
        except Exception as exc:  # noqa: BLE001
            warnings.append(Warning(
                code="validate_failed",
                message=f"陈述 {draft.id} 校验失败，已跳过：{exc}", stage="claims",
            ))
            continue
        reports.append((draft, report))

    # ---------- 阶段二：先注册陈述身份（短事务） ----------
    # save_report 只认**已持久化**的陈述行，因此必须先提交陈述身份，
    # 且云调用（阶段一）已结束，写事务里不再持有任何外部调用。
    stored_drafts: List[Tuple[StatementDraft, object]] = []
    with session_scope() as db:
        taken: Set[str] = set(repo.list_claim_ids(db, scope.revision_id))
        for ordinal, (draft, report) in enumerate(reports):
            claim_id = _unique_claim_id(
                _sanitize_claim_id(draft.claim_id, fallback_seed=draft.id), taken,
            )
            taken.add(claim_id)
            if claim_id != draft.claim_id:
                warnings.append(Warning(
                    code="claim_id_renamed",
                    message=f"claim_id {draft.claim_id} 碰撞，已重命名为 {claim_id}",
                    stage="claims",
                ))
            stored = draft.model_copy(update={"claim_id": claim_id})
            repo.upsert_statement(
                db, stored, origin="generated",
                display_class=display_class_for(stored, report), ordinal=ordinal,
            )
            stored_drafts.append((stored, report))

    # ---------- 阶段三：保存证据（M04 在自身短事务内完成） ----------
    claims: List[ClaimRecord] = []
    statements: List[VerifiedStatement] = []
    for stored, report in stored_drafts:
        try:
            saved_report = evidence_mod.save_report(report, ctx)
        except Exception as exc:  # noqa: BLE001
            warnings.append(Warning(
                code="save_failed", message=f"陈述 {stored.id} 证据保存失败：{exc}",
                stage="claims",
            ))
            continue
        evidence_ids = [ev.id for ev in saved_report.evidence]

        with session_scope() as db:
            repo.update_statement_validation(
                db, stored.id,
                validation=saved_report.model_dump(mode="json"),
                evidence_ids=evidence_ids,
                display_class=display_class_for(stored, saved_report),
            )
            claim = ClaimRecord(
                scope=scope,
                id=_claim_row_id(db, scope, stored.claim_id),
                claim_id=stored.claim_id,
                statement_id=stored.id,
                type=_claim_type_for(stored),
                status=_status_for(saved_report),
                rationale="",
                evidence_ids=evidence_ids,
                confidence=saved_report.confidence,
                visibility="exhibit",
            )
            repo.upsert_claim(db, claim)
        claims.append(claim)
        statements.append(
            VerifiedStatement.from_draft(
                stored, saved_report, evidence_ids=evidence_ids, origin="generated",
            )
        )

    with session_scope() as db:
        if len(batch.drafts) > prompts.MAX_EXHIBIT_CLAIMS:
            warnings.append(Warning(
                code="coverage_limited",
                message=f"生成规模超过展项上限 {prompts.MAX_EXHIBIT_CLAIMS}，超出部分保留候选不发布",
                stage="claims",
            ))
        repo.audit(
            db, kind="claims_verified", scope=scope, actor=ctx.request_id or "system",
            payload={"claim_count": len(claims),
                     "verified": sum(1 for c in claims if c.status == "verified")},
        )
    return ClaimBuildResult(scope=scope, claims=claims, statements=statements, warnings=warnings)


def _claim_row_id(db, scope: Scope, claim_id: str) -> str:
    existing = repo.get_claim_row(db, scope.revision_id, claim_id)
    return existing.id if existing else new_id()


def _status_for(report) -> str:
    """gate decision → ClaimStatus（**不允许任何形状的自动 SUPPORTED**）。"""
    decision = getattr(report, "decision", "unverified")
    if decision == "verified":
        return "verified"
    if decision == "inference":
        return "inference"
    if decision == "contested":
        return "contested"
    if decision == "rejected":
        return "rejected"
    return "unverified"


def _claim_type_for(draft: StatementDraft) -> str:
    """按陈述内容粗分类型；不改变状态，只做展示归类。"""
    text = (draft.text or "").lower()
    if any(k in text for k in ("局限", "限制", "不足", "limitation", "仅", "未验证")):
        return "LIMITATION"
    if any(k in text for k in ("方法", "算法", "流程", "训练", "method", "approach")):
        return "METHOD"
    if any(k in text for k in ("背景", "相关工作", "context", "已有")):
        return "CONTEXT"
    return "RESULT"


# =============================================================== 查询


def list_claims(scope: Scope) -> List[ClaimRecord]:
    """列表默认只返回 exhibit；answer_only 不暴露为展项。"""
    _require_scope(scope)
    with session_scope() as db:
        rows = repo.list_claim_rows(db, scope.revision_id, visibility="exhibit")
        return [repo.claim_dto(scope, row) for row in rows]


def get_claim(scope: Scope, claim_id: str) -> ClaimRecord:
    """同 scope 查找；可访问 answer_only 引用的 claim；不存在 404。"""
    _require_scope(scope)
    with session_scope() as db:
        row = repo.get_claim_row(db, scope.revision_id, claim_id)
        if row is None:
            raise not_found(f"claim {claim_id} 不存在")
        return repo.claim_dto(scope, row)


def get_statements(scope: Scope, ids: Sequence[str]) -> List[VerifiedStatement]:
    _require_scope(scope)
    with session_scope() as db:
        rows = repo.list_statement_rows(db, scope.revision_id, list(ids or []))
        return [repo.statement_dto(scope, row) for row in rows]


def get_verified_statements(scope: Scope) -> List[VerifiedStatement]:
    """只返回**已验证/推断**的陈述（场景与图谱的唯一合法输入）。

    **必须同时排除问答派生的 ``answer_only``**（ADR-0041）：QA 回答时会用
    ``register_statement`` 落库一批 ``visibility='answer_only'`` 的陈述，
    它们同样是 ``verified_fact``，此前只过滤 ``display_class`` → 泄漏进
    讲解分镜 / 研究图谱 / 展项包 / 评测指标（实测 paper 1 有 15 条 answer_only
    对 5 条 exhibit，论文产物被问答句子污染）。

    只排除**明确标记为 answer_only** 的；没有 claim 行的历史陈述一律保留，不误伤。
    """
    _require_scope(scope)
    with session_scope() as db:
        rows = repo.list_statement_rows(db, scope.revision_id)
        hidden = {
            row.statement_id
            for row in repo.list_claim_rows(db, scope.revision_id, visibility="answer_only")
        }
        out: List[VerifiedStatement] = []
        for row in rows:
            if (row.display_class or "unverified") in ("unverified",):
                continue
            if row.id in hidden:
                continue
            out.append(repo.statement_dto(scope, row))
        return out


# =============================================================== build_structure


def build_structure(scope: Scope, ctx: CallContext) -> StructureArtifact:
    """生成结构概览/地图/方法步骤（每个事实必须可追到 source）。

    只使用**已验证**的 statements/claims 作为事实来源；无 LLM 时退化为
    "原文分节 + 已验证 claim 的原文陈述"，绝不编造内容。
    """
    _require_scope(scope)
    with session_scope() as db:
        statement_rows = repo.list_statement_rows(db, scope.revision_id)
        # **只取展项断言**（ADR-0041）：问答产生的 ``answer_only`` 不得进入论文地图 /
        # 方法步骤 / 章节概览。此前这里是全量 list_claim_rows，实测跑过几轮问答后
        # paper 1 的 method_steps 从 1 条涨到 12 条，内容全部来自问答答案。
        claim_rows = repo.list_claim_rows(db, scope.revision_id, visibility="exhibit")
        block_rows = repo.list_block_rows(db, scope.revision_id)

    verified_claims = [
        repo.claim_dto(scope, row) for row in claim_rows
        if (row.status or "unverified") not in ("unverified", "rejected")
    ]
    # claim_id -> 该 claim 的**原文陈述**（唯一合法的事实文本来源）
    texts: Dict[str, str] = {}
    for row in statement_rows:
        for claim in verified_claims:
            if claim.statement_id == row.id:
                texts[claim.claim_id] = (row.text or "").strip()
    statement_ids_by_claim = {c.claim_id: c.statement_id for c in verified_claims}

    warnings: List[Warning] = []
    structure = _structure_without_llm(
        scope, statement_rows, verified_claims, block_rows, texts, statement_ids_by_claim, warnings
    )
    if settings.has_llm and verified_claims:
        llm_structure = _structure_with_llm(
            scope, verified_claims, block_rows, texts, statement_ids_by_claim, ctx, warnings
        )
        if llm_structure is not None:
            # ADR-0007：**section 一律采用确定性标题分节**（带块区间 → 可追溯）。
            # qwen-plus 在 strict json_schema 下只填它有把握的字段，实测它给出的
            # section 既没有可用 block_id、claim_ids 也对不上，导致 section 丢失块级
            # 归属、讲解退化为"每个场景塞满全部断言"。故这里只采纳其
            # ``map`` / ``method_steps``（本可由已验证断言确定性派生），
            # section 结构不再交给模型。
            updates = {}
            if llm_structure.method_steps:
                updates["method_steps"] = llm_structure.method_steps
            if llm_structure.map is not None:
                updates["map"] = llm_structure.map
            if updates:
                structure = structure.model_copy(update=updates)

    _assert_no_unsupported_leak(structure, verified_claims, warnings)

    with session_scope() as db:
        repo.replace_structure(db, structure)
        repo.audit(
            db, kind="structure_built", scope=scope, actor=ctx.request_id or "system",
            payload={"sections": len(structure.sections),
                     "method_steps": len(structure.method_steps)},
        )
    return structure


# =============================================================== 确定性分节
#
# ADR-0007：section 必须带**块区间**，否则讲解侧无法把断言归属到章节
# （真实论文实测：LLM 结构产出的 section 既无 source_block_ids 也无 summary.spans，
# 于是 scene 退化成"每个场景塞满全部断言"）。因此分节改为**确定性的标题检测**：
# 以原文一级标题切块区间，不依赖任何模型输出。

#: 一级标题最长期望（超过即视为正文/表格行，不是标题）
_HEADING_MAX_LEN = 60

#: 顶层编号标题：``1 引言`` / ``3 方法``；**排除** ``2.1.2 特性`` 这类多级编号。
_TOP_HEADING_RE = re.compile(r"^\s*(\d{1,2})(?![\d.])\s*[、.．]?\s*(\S.{0,55})$")

#: 无编号的常见章节名
_NAMED_HEADING_RE = re.compile(
    r"^\s*(摘要|abstract|引言|绪论|结论|结束语|总结与展望|总结|展望|"
    r"参考文献|references|致谢|acknowledgements?)\s*[:：]?\s*$",
    re.I,
)

#: 标题首字符若是这些，基本是图表/公式题注而非章节标题
_CAPTION_PREFIXES = ("表", "图", "式", "附", "(", "（", "[")

#: 章节标题关键词 → kind。**顺序即优先级**（"有效性分析"须先于"分析"）。
#: 注意：`scene/service._section_kind` 有一份等价表（模块边界内各自判 kind，
#: 避免 M09 反向依赖 M06 的内部实现）；两处改动需保持同步。
_SECTION_KIND_TOKENS: Tuple[Tuple[str, str], ...] = (
    ("摘要", "intro"), ("引言", "intro"), ("绪论", "intro"),
    ("abstract", "intro"), ("introduction", "intro"),
    ("背景", "problem"), ("相关工作", "problem"), ("研究现状", "problem"),
    ("问题", "problem"), ("background", "problem"), ("related work", "problem"),
    ("problem", "problem"),
    ("方法", "method"), ("设计", "method"), ("模型", "method"), ("算法", "method"),
    ("框架", "method"), ("实现", "method"), ("度量", "method"),
    ("method", "method"), ("approach", "method"), ("design", "method"),
    ("model", "method"), ("algorithm", "method"),
    ("实验", "experiment"), ("评估", "experiment"), ("数据集", "experiment"),
    ("experiment", "experiment"), ("evaluation", "experiment"), ("dataset", "experiment"),
    ("有效性", "limitation"), ("局限", "limitation"), ("威胁", "limitation"),
    ("结论", "limitation"), ("总结", "limitation"), ("展望", "limitation"),
    ("limitation", "limitation"), ("threat", "limitation"),
    ("conclusion", "limitation"), ("future", "limitation"),
    ("结果", "result"), ("分析", "result"), ("讨论", "result"),
    ("result", "result"), ("discussion", "result"), ("analysis", "result"),
)


def infer_section_kind(heading: str, fallback: str = "body") -> str:
    """由标题推断章节 kind（确定性、不调模型）。"""
    body = (_MULTISPACE_RE.sub(" ", (heading or "")).strip()).lower()
    for token, kind in _SECTION_KIND_TOKENS:
        if token in body:
            return kind
    return fallback


def heading_body(text: str) -> Optional[str]:
    """判断块文本是否一级章节标题；是则返回规范化标题，否则 ``None``。"""
    body = _MULTISPACE_RE.sub(" ", (text or "").replace("\n", " ")).strip()
    if not body or len(body) > _HEADING_MAX_LEN:
        return None
    if body.endswith(("。", ".", "；", ";", "，", ",")):
        return None
    if body.startswith(_CAPTION_PREFIXES):
        return None
    if _NAMED_HEADING_RE.match(body):
        return body

    match = _TOP_HEADING_RE.match(body)
    if not match:
        return None
    rest = match.group(2)
    # 编号后必须是真正的"标题样"文本（至少 2 个字母/汉字），排除数字表格行
    letters = sum(1 for ch in rest if ch.isalpha())
    if letters < 2:
        return None
    return body


def _dedup_anchors(anchor_ids: Iterable[Optional[str]]) -> List[str]:
    """按出现顺序去重锚点 id，丢掉空值。

    章节的锚点由**本节块的页锚点**派生（ADR-0029）：章节自己不产生锚点，
    只汇总它覆盖的块的锚点。块没有锚点时留空——绝不伪造。
    """
    out: List[str] = []
    seen: Set[str] = set()
    for anchor_id in anchor_ids:
        if not anchor_id:
            continue
        text = str(anchor_id)
        if text in seen:
            continue
        seen.add(text)
        out.append(text)
    return out


def _sections_from_headings(
    scope: Scope, block_rows, statement_rows, verified_claims, warnings: List[Warning]
) -> List[SectionRecord]:
    """按原文一级标题确定性分节，并为每节建立**块区间**。

    块区间 = ``[标题块, 下一个一级标题之前的所有块)``；第一个标题之前的块
    （题名/摘要/关键词）并入第一节，避免丢失块覆盖。每节的 summary 只取
    引用块落在本节区间内的**已验证** claim 陈述。
    """
    headings = [
        (idx, heading_body(row.text))
        for idx, row in enumerate(block_rows)
    ]
    headings = [(idx, head) for idx, head in headings if head]
    if not headings:
        # 没有可识别的标题：退回"逐块分节"，至少不丢内容
        return _sections_from_blocks(scope, block_rows, statement_rows, verified_claims, warnings)

    sections: List[SectionRecord] = []
    for order, (start, head) in enumerate(headings):
        if order >= prompts.MAX_SCENE_COUNT:
            warnings.append(Warning(
                code="coverage_limited",
                message=f"章节数量超过上限 {prompts.MAX_SCENE_COUNT}，已截断并保留候选",
                stage="claims",
            ))
            break
        end = headings[order + 1][0] if order + 1 < len(headings) else len(block_rows)
        covered = block_rows[start:end] if order > 0 else block_rows[:end]
        block_ids = [row.id for row in covered]
        sections.append(SectionRecord(
            scope=scope, id=f"sec-{start}-{scope.revision_id[:8]}", heading=head,
            kind=infer_section_kind(head), source_block_ids=block_ids,
            anchor_ids=_dedup_anchors(getattr(row, "anchor_id", None) for row in covered),
            summary=_summary_for_blocks(block_ids, statement_rows, verified_claims),
        ))
    return sections


def _summary_for_blocks(
    block_ids: Sequence[str], statement_rows, verified_claims
) -> ArtifactText:
    """只取引用块落在给定块集合内的已验证陈述作为 summary。"""
    claim_by_statement = {c.statement_id: c for c in verified_claims}
    wanted = set(block_ids)
    matched: List[Tuple[str, str]] = []
    for statement in statement_rows:
        claim = claim_by_statement.get(statement.id)
        if claim is None:
            continue
        cites = _citation_block_ids(statement)
        if not any(bid in wanted for bid in cites):
            continue
        matched.append((claim.claim_id, statement.id))
    if not matched:
        return ArtifactText(text="", spans=[])
    text = "；".join(_statement_text(sid, statement_rows) for _, sid in matched)
    return build_artifact_text(text, [sid for _, sid in matched])


def _citation_block_ids(statement_row) -> List[str]:
    """从 statement 的 citations 抽 block_id（容忍 dict/对象两种历史形态）。"""
    out: List[str] = []
    for cite in (getattr(statement_row, "citations", None) or []):
        bid = cite.get("block_id") if isinstance(cite, dict) else getattr(cite, "block_id", None)
        if bid:
            out.append(str(bid))
    return out


def _sections_from_blocks(
    scope: Scope, block_rows, statement_rows, verified_claims, warnings: List[Warning]
) -> List[SectionRecord]:
    """按原文块分节；summary 只取落在该节 block 上的**已验证** claim 陈述。"""
    sections: List[SectionRecord] = []
    claim_by_statement = {c.statement_id: c for c in verified_claims}
    for ordinal, row in enumerate(block_rows):
        if ordinal >= prompts.MAX_SCENE_COUNT:
            warnings.append(Warning(
                code="coverage_limited",
                message=f"章节数量超过上限 {prompts.MAX_SCENE_COUNT}，已截断并保留候选",
                stage="claims",
            ))
            break
        heading = (row.text or "").strip().split("\n", 1)[0][:80]
        section = SectionRecord(
            scope=scope, id=f"sec-{row.id}", heading=heading or f"第 {ordinal + 1} 节",
            kind="body", source_block_ids=[row.id],
            anchor_ids=_dedup_anchors([getattr(row, "anchor_id", None)]),
        )
        # 归入本节：引用块命中该节 block 的已验证 statement
        matched: List[Tuple[str, str]] = []
        for st in statement_rows:
            claim = claim_by_statement.get(st.id)
            if claim is None:
                continue
            if not repo_statement_belongs(st.id, [st], [row.id]):
                continue
            matched.append((claim.claim_id, st.id))
        if matched:
            text = "；".join(_statement_text(sid, statement_rows) for _, sid in matched)
            section.summary = build_artifact_text(text, [sid for _, sid in matched])
        sections.append(section)
    return sections


def _structure_without_llm(
    scope: Scope, statement_rows, verified_claims: List[ClaimRecord], block_rows,
    texts: Dict[str, str], statement_ids_by_claim: Dict[str, str], warnings: List[Warning],
) -> StructureArtifact:
    """无 LLM 退化路径：原文分节 + 已验证 claim 的原文陈述。"""
    sections = _sections_from_headings(
        scope, block_rows, statement_rows, verified_claims, warnings
    )

    map_items: List[MapItem] = []
    if verified_claims:
        by_kind: Dict[str, List[str]] = {"problem": [], "method": [], "result": [], "limitation": []}
        for claim in verified_claims:
            kind = {"METHOD": "method", "LIMITATION": "limitation"}.get(claim.type, "result")
            by_kind[kind].append(claim.claim_id)
        for kind in ("problem", "method", "result", "limitation"):
            claim_ids = by_kind[kind]
            if not claim_ids:
                continue
            text = "；".join(_claim_text(cid, texts) for cid in claim_ids)
            artifact = build_artifact_text(text, [statement_ids_by_claim[cid] for cid in claim_ids])
            if not artifact.text:
                continue
            map_items.append(MapItem(
                id=f"map-{kind}-{scope.revision_id[:8]}", kind=kind, text=artifact,
                claim_ids=list(claim_ids),
            ))

    steps = _steps_from_sections(
        scope, sections, statement_rows, verified_claims, texts, statement_ids_by_claim,
        {row.id: idx for idx, row in enumerate(block_rows)},
    )
    if not steps:
        # 兜底：方法/实验章没有可归属的断言时，退回"METHOD 类型断言"（保持旧行为）。
        steps = _steps_from_method_claims(
            scope, verified_claims, texts, statement_ids_by_claim
        )

    map_artifact = (
        MapArtifact(scope=scope, id=f"map-{scope.revision_id}", items=map_items)
        if map_items else None
    )
    return StructureArtifact(scope=scope, sections=sections, map=map_artifact, method_steps=steps)


#: 能承载"方法步骤"的章节 kind（标题确定性推断出来的）
_STEP_SECTION_KINDS = ("method", "experiment")


def _steps_from_sections(
    scope: Scope, sections, statement_rows, verified_claims: List[ClaimRecord],
    texts: Dict[str, str], statement_ids_by_claim: Dict[str, str],
    doc_pos: Dict[str, int],
) -> List[MethodStepRecord]:
    """**方法/实验章内的已验证陈述** → 有序方法步骤（确定性，不调 LLM）。

    为什么（真实缺陷，paper 1 实测）：此前只把 ``type == "METHOD"`` 的断言当步骤，
    而 ``_claim_type_for`` 是关键词启发式（文本含"方法/算法/流程/训练"才算 METHOD）。
    paper 1 有 2 个 method 章 + 1 个 experiment 章，但 5 条展项断言里只有 1 条被判成
    METHOD → "方法动画"只有 1 步（LLM 结构路径对这篇实测返回 method_steps=0，
    没有任何补充）。

    这里改为**按章节归属**取步骤：与讲解侧同源的块级判定（陈述引用的块落在本节
    ``source_block_ids``），文本仍是断言原文、``phase`` 用章节标题。
    同一断言只归属一个步骤（与讲解侧同一条不变式）。

    **顺序按引用块的文档位置**（``doc_pos``），不能沿用 ``verified_claims`` 的顺序——
    后者来自 ``repo.list_claim_rows``，按 ``ClaimRecordORM.id``（随机 UUID）排序，
    会让步骤顺序每次构建都不一样（真实缺陷：单测因此随机失败）。
    """
    steps: List[MethodStepRecord] = []
    assigned: Set[str] = set()
    statement_by_id = {row.id: row for row in statement_rows}
    cited_blocks = {
        cid: _citation_block_ids(statement_by_id.get(sid)) for cid, sid in statement_ids_by_claim.items()
    }
    for section in sections:
        if (getattr(section, "kind", "") or "") not in _STEP_SECTION_KINDS:
            continue
        block_ids = set(getattr(section, "source_block_ids", []) or [])
        if not block_ids:
            continue
        # 本节内、按文档顺序排列的候选
        candidates: List[Tuple[int, ClaimRecord]] = []
        for claim in verified_claims:
            if claim.claim_id in assigned:
                continue
            hits = [b for b in cited_blocks.get(claim.claim_id, []) if b in block_ids]
            if not hits:
                continue
            candidates.append((min(doc_pos.get(b, 10 ** 6) for b in hits), claim))
        for _pos, claim in sorted(candidates, key=lambda kv: kv[0]):
            if claim.claim_id in assigned:
                continue
            text = _claim_text(claim.claim_id, texts)
            artifact = build_artifact_text(text, [statement_ids_by_claim[claim.claim_id]])
            if not artifact.text:
                continue
            assigned.add(claim.claim_id)
            steps.append(MethodStepRecord(
                scope=scope,
                id=f"step-{claim.claim_id}",
                order=len(steps),
                label=artifact,
                # detail 仍留空：``ArtifactText`` 的 spans 是 statement 级且必须**完整覆盖**
                # 文本，模型给的自由散文无法落 span（§"禁止无引用副文案"），
                # 前端取 ``label`` 文本渲染，不需要重复一份。
                detail=ArtifactText(text="", spans=[]),
                phase=(getattr(section, "heading", "") or None),
                claim_ids=[claim.claim_id],
            ))
            if len(steps) >= prompts.MAX_METHOD_STEPS:
                return steps
    return steps


def _steps_from_method_claims(
    scope: Scope, verified_claims: List[ClaimRecord],
    texts: Dict[str, str], statement_ids_by_claim: Dict[str, str],
) -> List[MethodStepRecord]:
    """兜底：一条 METHOD 类型断言 = 一个步骤（旧行为，保持兼容）。"""
    steps: List[MethodStepRecord] = []
    for order, claim in enumerate(
        [c for c in verified_claims if c.type == "METHOD"][: prompts.MAX_METHOD_STEPS]
    ):
        text = _claim_text(claim.claim_id, texts)
        artifact = build_artifact_text(text, [statement_ids_by_claim[claim.claim_id]])
        if not artifact.text:
            continue
        steps.append(MethodStepRecord(
            scope=scope,
            id=f"step-{claim.claim_id}-{order}",   # id 必填（§6.8）
            order=order,
            label=artifact,
            detail=ArtifactText(text="", spans=[]),
            phase=None,
            claim_ids=[claim.claim_id],
        ))
    return steps


def _structure_with_llm(
    scope: Scope, verified_claims: List[ClaimRecord], block_rows,
    texts: Dict[str, str], statement_ids_by_claim: Dict[str, str],
    ctx: CallContext, warnings: List[Warning],
) -> Optional[StructureArtifact]:
    """LLM 生成结构；**任何不可追溯到已验证 claim 的文字都被丢弃**。"""
    claim_lines = "\n".join(
        f"[{c.claim_id}] ({c.type}) {texts.get(c.claim_id, '')}" for c in verified_claims
    )
    block_lines = "\n".join(f"[{r.id}] {(r.text or '')[:400]}" for r in block_rows[:120])
    try:
        from app.contracts.ai import ChatMessage, CompletionRequest
        from app.modules import ai as ai_module

        result = ai_module.complete(
            CompletionRequest(
                messages=[
                    ChatMessage(role="system", content=prompts.STRUCTURE_PROMPT),
                    ChatMessage(role="user", content=(
                        f"已验证断言：\n{claim_lines}\n\n原文块：\n{block_lines}"
                    )),
                ],
                output_schema=prompts._StructureDraft,
                max_output_tokens=4096,
            ),
            ctx,
        )
    except Exception as exc:  # noqa: BLE001 —— 云调用失败必须降级
        warnings.append(Warning(
            code="llm_failed", message=f"结构生成失败，回退原文模板：{exc}", stage="claims",
        ))
        return None

    raw = result.value
    if raw is None:
        return None
    known = {c.claim_id for c in verified_claims}
    known_blocks = {r.id for r in block_rows}
    anchor_by_block = {r.id: getattr(r, "anchor_id", None) for r in block_rows}

    sections: List[SectionRecord] = []
    for idx, sec in enumerate(getattr(raw, "sections", []) or []):
        if idx >= prompts.MAX_SCENE_COUNT:
            warnings.append(Warning(
                code="coverage_limited",
                message=f"章节数量超过上限 {prompts.MAX_SCENE_COUNT}，已截断",
                stage="claims",
            ))
            break
        valid_ids = [cid for cid in (sec.claim_ids or []) if cid in known]
        text = "；".join(_claim_text(cid, texts) for cid in valid_ids)
        artifact = build_artifact_text(
            text, [statement_ids_by_claim[cid] for cid in valid_ids]
        )
        if (sec.summary or "").strip() and not valid_ids:
            warnings.append(Warning(
                code="unsupported_summary",
                message=f"章节 {sec.heading} 的概览无可追溯依据，已丢弃该段文字",
                stage="claims",
            ))
        accepted_blocks = [b for b in (sec.source_block_ids or []) if b in known_blocks]
        sections.append(SectionRecord(
            scope=scope, id=f"sec-{idx}-{scope.revision_id[:8]}", heading=sec.heading or "",
            kind=sec.kind or "body",
            source_block_ids=accepted_blocks,
            anchor_ids=_dedup_anchors(anchor_by_block.get(b) for b in accepted_blocks),
            summary=artifact,
        ))

    map_items: List[MapItem] = []
    raw_map_items = list(getattr(raw, "map_items", []) or [])
    for idx, item in enumerate(raw_map_items):
        valid_ids = [cid for cid in (item.claim_ids or []) if cid in known]
        if not valid_ids:
            continue
        text = "；".join(_claim_text(cid, texts) for cid in valid_ids)
        artifact = build_artifact_text(text, [statement_ids_by_claim[cid] for cid in valid_ids])
        if not artifact.text:
            continue
        map_items.append(MapItem(
            id=f"map-{idx}-{scope.revision_id[:8]}", kind=item.kind or "result",
            text=artifact, claim_ids=valid_ids,
        ))

    steps: List[MethodStepRecord] = []
    raw_steps = list(getattr(raw, "method_steps", []) or [])
    for idx, step in enumerate(raw_steps):
        if idx >= prompts.MAX_METHOD_STEPS:
            break
        valid_ids = [cid for cid in (step.claim_ids or []) if cid in known]
        if not valid_ids:
            continue
        text = "；".join(_claim_text(cid, texts) for cid in valid_ids)
        artifact = build_artifact_text(text, [statement_ids_by_claim[cid] for cid in valid_ids])
        if not artifact.text:
            continue
        steps.append(MethodStepRecord(
            scope=scope, id=f"step-{idx}-{scope.revision_id[:8]}", order=idx,
            label=artifact, detail=ArtifactText(text="", spans=[]),
            phase=step.phase, claim_ids=valid_ids,
        ))
    if raw_steps and not steps:
        # 可观测性（此前是静默 continue）：模型给了步骤但**全部**因 claim_ids 对不上
        # 而被丢弃时，必须说出来——否则"方法动画只有 1 步/ 没步骤"看起来像模型没产出。
        warnings.append(Warning(
            code="method_steps_dropped",
            message=(
                f"模型给出 {len(raw_steps)} 个方法步骤，但其 claim_ids 无一命中已验证断言，"
                "已全部丢弃（将使用确定性章节归属生成步骤）"
            ),
            stage="claims",
        ))
    if raw_map_items and not map_items:
        warnings.append(Warning(
            code="map_items_dropped",
            message=(
                f"模型给出 {len(raw_map_items)} 条论文地图项，但其 claim_ids 无一命中已验证断言，"
                "已全部丢弃（将使用按类型确定性生成的地图）"
            ),
            stage="claims",
        ))

    map_artifact = (
        MapArtifact(scope=scope, id=f"map-{scope.revision_id}", items=map_items)
        if map_items else None
    )
    return StructureArtifact(scope=scope, sections=sections, map=map_artifact, method_steps=steps)


def repo_statement_belongs(statement_id: str, statement_rows, block_ids: Sequence[str]) -> bool:
    """陈述的引用块是否落在给定块集合内（用于归入章节）。"""
    wanted = set(block_ids)
    for row in statement_rows:
        if row.id != statement_id:
            continue
        for cite in (row.citations or []):
            bid = cite.get("block_id") if isinstance(cite, dict) else getattr(cite, "block_id", None)
            if bid in wanted:
                return True
    return False


def _statement_text(statement_id: str, statement_rows) -> str:
    for row in statement_rows:
        if row.id == statement_id:
            return (row.text or "").strip()
    return ""


def _claim_text(claim_id: str, texts: Dict[str, str]) -> str:
    return texts.get(claim_id, "")


def _assert_no_unsupported_leak(
    structure: StructureArtifact, verified_claims: List[ClaimRecord], warnings: List[Warning]
) -> None:
    """自检：结构产物的文本必须能追溯到已验证 claim，否则报警。"""
    known = {c.claim_id for c in verified_claims}
    for section in structure.sections:
        if section.summary.text and not section.summary.spans:
            warnings.append(Warning(
                code="unsupported_summary",
                message=f"章节 {section.id} 的 summary 无可追溯 span，已置空",
                stage="claims",
            ))
    for item in (structure.map.items if structure.map else []):
        for cid in item.claim_ids:
            if cid not in known:
                warnings.append(Warning(
                    code="unknown_claim_ref",
                    message=f"地图项引用了未知 claim {cid}", stage="claims",
                ))



# =============================================================== 校验工具


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


def get_structure(scope: Scope) -> StructureArtifact:
    """读取结构产物（GET：不调用 LLM、不写库）。"""
    _require_scope(scope)
    with session_scope() as db:
        return repo.get_structure(db, scope)


__all__ = [
    "extract",
    "verify_and_store",
    "build_structure",
    "list_claims",
    "get_claim",
    "get_structure",
    "get_statements",
    "get_verified_statements",
    "register_statement",
    "build_artifact_text",
]
