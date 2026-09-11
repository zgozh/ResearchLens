"""M04 — 旧引用字符串解析（REFACTOR_SPEC §5.2、§5.10）。

职责：把旧数据里的 ``"p.1587"`` / ``"fig_2"`` / ``"表 S1"`` / ``"图 2(a)"``
这类**字符串引用**解析成受控 ``SourceRef`` 或 ``MediaLinkCandidate``。

硬约束：
- ``resolved`` 仅表示**定位已解出**，不表示支持已验证；
- 图号匹配必须**整号相等**（``fig_1`` ≠ ``fig_10``），不做子串包含；
- 印刷页 ``p.1587`` 先查映射；**多个映射即 ambiguous，不猜全局固定偏移**；
- 只有唯一且已验证映射才可定位页面，仍不能凭同页建立语义支持；
- 解析不出的进 ``unresolved``，**不伪造**归属。
"""
from __future__ import annotations

import re
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from app.contracts.artifacts import Media, MediaLinkCandidate
from app.contracts.common import AnchorId, Scope, SourceRef, Warning
from app.contracts.documents import PageLabelMapping
from app.contracts.evidence import LegacyRef, ResolutionReport

#: 图号：Fig. 2 / Figure 2 / 图 2 / 图2(a) / Table 1 / 表 S1 / 表1
_FIG_LABEL_RE = re.compile(
    r"(?:图|表|式|fig(?:ure)?\.?|tab(?:le)?\.?|eq(?:uation)?\.?)\s*"
    r"([A-Za-z]?\s*\d+[A-Za-z]?)\s*(\([a-zA-Z0-9]+\))?",
    re.IGNORECASE,
)
#: 印刷页：p.1587 / p1587 / 第 1587 页 / page 1587
_PAGE_RE = re.compile(r"(?:^|\b)(?:p|page|页)\.?\s*(\d{1,5})(?:\b|$)", re.IGNORECASE)
_CN_PAGE_RE = re.compile(r"第\s*(\d{1,5})\s*页")
#: 整数图号兼容编号：fig_2 / figure_2 / table_1
_LEGACY_NO_RE = re.compile(
    r"(?:fig(?:ure)?|tab(?:le)?|tbl)[_\-\s]?(\d{1,3})\b", re.IGNORECASE
)


def _norm_label(raw: str) -> str:
    """编号规范化：折叠空白、统一大小写、去括号后缀空格。"""
    return re.sub(r"\s+", "", (raw or "").strip()).lower()


def normalize_media_label(media: Media) -> List[str]:
    """一个 Media 的全部可匹配编号（原始编号 + 兼容整数编号）。

    注意：解析侧 ``parse_ref`` 提取的图号是**去掉 "图/Figure/Table" 前缀**后的
    纯编号（如 ``"图 2(a)"`` → ``"2"``），因此这里必须同时登记
    前缀形式与纯编号形式，否则两侧永远对不上。
    """
    labels: List[str] = []

    def _add(value: str) -> None:
        norm = _norm_label(value)
        if norm and norm not in labels:
            labels.append(norm)

    raw = media.original_label or ""
    if raw:
        _add(raw)
        # 去掉括号子图后缀，"图 2(a)" 也能匹配到父图 "图 2"
        _add(re.sub(r"\([^)]*\)$", "", raw))
        # 去掉 图/表/式/fig/figure/table 前缀，得到纯编号
        stripped = _FIG_LABEL_RE.sub(lambda m: m.group(1) + (m.group(2) or ""), raw)
        _add(stripped)
        _add(re.sub(r"\([^)]*\)$", "", stripped))
    if media.legacy_no is not None:
        _add(f"fig_{media.legacy_no}")
        _add(f"figure_{media.legacy_no}")
        _add(f"table_{media.legacy_no}")
        _add(f"tab_{media.legacy_no}")
        _add(f"图{media.legacy_no}")
        _add(f"表{media.legacy_no}")
        _add(str(media.legacy_no))
    return labels


def parse_ref(text: str) -> Dict[str, Optional[str] | Optional[int]]:
    """把旧引用字符串拆成结构化成分（不做归属判断）。"""
    raw = (text or "").strip()
    fig_match = _FIG_LABEL_RE.search(raw)
    page_match = _PAGE_RE.search(raw) or _CN_PAGE_RE.search(raw)
    legacy_match = _LEGACY_NO_RE.search(raw)

    label: Optional[str] = None
    sub: Optional[str] = None
    if fig_match:
        label = _norm_label(fig_match.group(1))
        sub = (fig_match.group(2) or "").strip() or None

    page: Optional[int] = None
    if page_match:
        try:
            page = int(page_match.group(1))
        except (TypeError, ValueError):
            page = None

    legacy_no: Optional[int] = None
    if legacy_match:
        try:
            legacy_no = int(legacy_match.group(1))
        except (TypeError, ValueError):
            legacy_no = None

    return {"label": label, "sub": sub, "page": page, "legacy_no": legacy_no}


def match_media(
    ref: LegacyRef, media_items: Sequence[Media]
) -> Tuple[List[Media], List[MediaLinkCandidate], List[str]]:
    """按**整号相等**匹配媒体；返回候选与命中方法。

    绝不使用 ``in`` 子串包含：``fig_1`` 不得命中 ``fig_10``。
    """
    parsed = parse_ref(ref.text)
    label = parsed["label"]            # type: ignore[assignment]
    legacy_no = parsed["legacy_no"]    # type: ignore[assignment]
    page = parsed["page"] if parsed["page"] is not None else ref.page  # type: ignore[assignment]

    exact: List[Media] = []
    methods: Dict[str, str] = {}

    if label:
        for media in media_items:
            labels = normalize_media_label(media)
            if _norm_label(str(label)) in labels:
                exact.append(media)
                methods[media.id] = "legacy_regex"
    if not exact and legacy_no is not None:
        for media in media_items:
            if media.legacy_no is not None and int(media.legacy_no) == int(legacy_no):
                exact.append(media)
                methods[media.id] = "legacy_regex"

    if not exact and page is not None:
        # 仅同页 → 只能是 same_page 候选，且**不构成支持**
        for media in media_items:
            pidx = _media_page_index(media)
            if pidx is not None and pidx + 1 == int(page):
                exact.append(media)
                methods[media.id] = "same_page"

    candidates = [
        MediaLinkCandidate(
            media_id=m.id,
            via_anchor_ids=list(m.anchor_ids),
            method=methods.get(m.id, "legacy_regex"),  # type: ignore[arg-type]
            score=None,
            reason="旧引用字符串解析所得候选，须经 verified Binding 才能展示",
        )
        for m in exact
    ]
    labels = [str(label)] if label else []
    return exact, candidates, labels


def _media_page_index(media: Media) -> Optional[int]:
    """从 media 的 provenance/anchor 推断物理页；推断不出返回 None。"""
    extra = getattr(media, "page_index", None)
    if isinstance(extra, int):
        return extra
    return None


def resolve_map(
    scope: Scope, mappings: Sequence[PageLabelMapping], labels: Iterable[str]
) -> Tuple[Dict[str, int], List[Warning], List[str]]:
    """印刷页 → 物理页解析。

    返回 ``(resolved, warnings, ambiguous_labels)``：
    - 唯一且 ``status=verified`` 才能 resolved；
    - 多个映射 → ambiguous，不猜偏移。
    """
    resolved: Dict[str, int] = {}
    warnings: List[Warning] = []
    ambiguous: List[str] = []
    by_label: Dict[str, List[PageLabelMapping]] = {}
    for mapping in mappings:
        by_label.setdefault(_norm_label(mapping.page_label), []).append(mapping)

    for raw in labels:
        key = _norm_label(raw)
        entries = by_label.get(key, [])
        if not entries:
            continue
        if len(entries) > 1:
            ambiguous.append(raw)
            warnings.append(
                Warning(code="ambiguous_page_label",
                        message=f"印刷页 {raw} 对应多个物理页，保持 ambiguous，不猜偏移",
                        stage="evidence")
            )
            continue
        only = entries[0]
        if only.status != "verified":
            ambiguous.append(raw)
            warnings.append(
                Warning(code="unverified_page_label",
                        message=f"印刷页 {raw} 只有 candidate 映射，不能定位",
                        stage="evidence")
            )
            continue
        resolved[key] = only.pdf_page_index
        _ = scope   # scope 已在调用方校验
    return resolved, warnings, ambiguous


def resolve_legacy_refs(
    scope: Scope,
    refs: Sequence[LegacyRef],
    *,
    media_items: Sequence[Media],
    label_mappings: Sequence[PageLabelMapping],
    anchor_of_media: Optional[Dict[str, AnchorId]] = None,
) -> ResolutionReport:
    """核心解析：旧引用字符串 → SourceRef / MediaLinkCandidate / unresolved。"""
    anchor_of_media = anchor_of_media or {}
    resolved: List[SourceRef] = []
    candidates: List[MediaLinkCandidate] = []
    unresolved: List[LegacyRef] = []
    warnings: List[Warning] = []

    for ref in refs:
        parsed = parse_ref(ref.text)
        page = parsed["page"] if parsed["page"] is not None else ref.page  # type: ignore[assignment]

        # 1) 图号 / 表号 → 媒体候选（整号相等）
        matched, cands, _labels = match_media(ref, media_items)
        if matched:
            candidates.extend(cands)
            for media in matched:
                anchor_id = anchor_of_media.get(media.id) or (
                    media.anchor_ids[0] if media.anchor_ids else None
                )
                if anchor_id:
                    resolved.append(SourceRef(kind="anchor", id=anchor_id))
                resolved.append(SourceRef(kind="media", id=media.id))
            continue

        # 2) 印刷页 → 物理页映射（唯一且 verified 才定位）
        if page is not None:
            resolved_pages, page_warnings, ambiguous = resolve_map(
                scope, label_mappings, [str(page)]
            )
            warnings.extend(page_warnings)
            if resolved_pages:
                # 页级依据：仅说明"在这一页"，不代表支持成立
                page_index = resolved_pages[str(page)]
                warnings.append(
                    Warning(code="page_only_reference",
                            message=f"旧引用 {ref.text} 仅能解到物理页，不构成精准定位",
                            stage="evidence")
                )
                candidates.append(
                    MediaLinkCandidate(
                        media_id="",
                        via_anchor_ids=[],
                        method="same_page",
                        score=None,
                        reason=f"仅页级候选：pdf_page_index={page_index}",
                    )
                )
                continue
            if ambiguous:
                unresolved.append(ref)
                continue

        unresolved.append(ref)

    return ResolutionReport(
        scope=scope,
        resolved=resolved,
        candidates=candidates,
        unresolved=unresolved,
        warnings=warnings,
    )


__all__ = [
    "parse_ref",
    "normalize_media_label",
    "match_media",
    "resolve_map",
    "resolve_legacy_refs",
]
