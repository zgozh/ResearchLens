"""M01/M13 — 旧论文详情兼容投影（REFACTOR_SPEC §5.11）。

``api/routes.py`` 的 ``GET /papers/{paper_id}`` 仍返回旧 ``PaperDetail``
形状（sections / figures / tables / method_steps / pages）。此前该路由**直接读
legacy ORM**（``p.figures`` / ``p.tables`` / ``p.sections`` / ``p.pages`` /
``p.method_steps``），而那些表只被 **demo seed** 填充：

- demo/synthetic 论文：有内容；
- **真实论文：全空** —— 即使 canonical 里已有 17 张 media、17 条 statements、
  7 个 section。前端「原图 / 原表 / 章节 / 方法步骤 / 原文页」几处因此空白。

``schemas/adapters.to_legacy_detail`` 早已实现该投影，但**零调用**。
本模块补齐数据装配：canonical 优先，无 canonical 数据时返回 ``None``，
由路由回退到旧表读取（保住 demo 论文的行为）。

纪律：不编造。没有 anchor 的 media 页码记 0；没有 canonical 数据的论文
一律返回 ``None`` 交给旧路径，绝不返回半真半假的结构。
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.contracts.common import Scope


# =============================================================== 路线 A：canonical → 旧 DTO
#
# 为什么需要这些函数（ADR-0027）：``/api/papers/{id}`` 仍返回旧 ``PaperDetail``，
# 其中 map_summary/abstract/authors 取自 **legacy ``papers`` 表列**，而真实论文
# 这些列是空的（实测 map_summary={}、abstract 长度 0、authors=[]）→ 地图页六维卡片
# 全渲染成 "—"、摘要与作者行全空；figures 也只给空 ``image_b64``/``glyph_svg``
# （图其实在 canonical 的 asset 里）→ "有摘要没图"。
# 这里把 canonical 产物补进旧 DTO；**没有来源就不给键**，绝不编造。

#: 摘要起止标记（中英双语论文都要支持）。
#: 起始标记**必须带冒号**：否则正文里的普通词（"没有任何摘要标记"）会被误判成摘要头。
_ABSTRACT_START_RE = re.compile(r"(?:摘\s*要|abstract)\s*[:：]", re.I)
_ABSTRACT_END_RE = re.compile(
    r"(?:关\s*键\s*词|key\s*words?|中图法分类号|中图分类号|CCS\s*Concepts)\s*[:：]?", re.I
)


def map_summary_from_structure(structure: Any, sections: Any) -> Dict[str, str]:
    """canonical 结构 → 旧 ``map_summary``（MapView 的六维卡片）。

    - ``problem/method/result/limitation`` 取自 ``structure.map.items``（已验证内容）；
    - ``experiment``/``dataset`` 在 canonical map 里没有对应 kind，用**章节**兜底
      （kind=experiment 的章节摘要 / 标题含"数据"的章节摘要）；
    - 没有来源的键**不出现**——前端自然显示 "—"，而不是被占位文本充数。
    """
    out: Dict[str, str] = {}
    items = list(getattr(getattr(structure, "map", None), "items", None) or [])
    for item in items:
        kind = (getattr(item, "kind", "") or "").strip()
        text = _text(getattr(item, "text", None)).strip()
        if kind and text and kind not in out:
            out[kind] = text

    secs = list(sections or [])
    if "experiment" not in out:
        for s in secs:
            if (getattr(s, "kind", "") or "").lower() == "experiment":
                text = _text(getattr(s, "summary", None)).strip()
                if text:
                    out["experiment"] = text
                    break
    if "dataset" not in out:
        for s in secs:
            heading = (getattr(s, "heading", "") or "")
            if "数据" in heading or "dataset" in heading.lower():
                text = _text(getattr(s, "summary", None)).strip()
                if text:
                    out["dataset"] = text
                    break
    return out


def abstract_from_page_text(text: str, *, limit: int = 1200) -> str:
    """从首页正文切出摘要；**没有可识别标记就返回空串**（宁缺勿造，不把整页当摘要）。"""
    raw = text or ""
    start = _ABSTRACT_START_RE.search(raw)
    if not start:
        return ""
    tail = raw[start.end():]
    end = _ABSTRACT_END_RE.search(tail)
    body = (tail[: end.start()] if end else tail).strip()
    return re.sub(r"\s+", " ", body)[:limit]


def figure_image_url(media: Any) -> str:
    """媒体 → 可访问的图片 URL（第一个真实图资产）；**无资产则空串**。

    绝不回退到 ``raw_asset_id``：那是 ``parser_raw`` 的 JSON，前端会把它当图渲染
    （D-24 已把真图落成 ``kind="crop"`` 的 asset，这里只认它）。
    """
    asset_ids = [a for a in (getattr(media, "original_asset_ids", None) or []) if a]
    if not asset_ids:
        return ""
    try:
        from app.modules.papers import service as papers_service

        return papers_service.asset_url(asset_ids[0])
    except Exception:  # noqa: BLE001 - URL 拼装失败不得让详情 500
        return ""


def get_detail(db: Session, paper_id: int) -> Optional[Any]:
    """canonical 优先的旧详情投影；无 canonical 数据返回 ``None``。"""
    revision_id = _readable_revision(db, paper_id)
    if not revision_id:
        return None
    scope = Scope(paper_id=paper_id, revision_id=revision_id)

    # 惰性导入：papers ← parse/visual/claims 存在反向依赖，模块级导入会成环。
    from app.modules import claims as claims_mod
    from app.modules import parse as parse_mod
    from app.modules import papers as papers_mod
    from app.modules import visual as visual_mod
    from app.schemas.adapters import _legacy_step, to_legacy_detail

    try:
        structure = claims_mod.get_structure(scope)
    except Exception:  # noqa: BLE001 - 兼容层不得把异常泄漏成 500
        structure = None
    try:
        media_items = list(visual_mod.list_media(scope, limit=500).items)
    except Exception:  # noqa: BLE001
        media_items = []
    try:
        page_items = list(parse_mod.get_pages(scope, limit=500).items)
    except Exception:  # noqa: BLE001
        page_items = []

    sections = list(getattr(structure, "sections", None) or [])
    steps = list(getattr(structure, "method_steps", None) or [])
    if not (sections or media_items or page_items or steps):
        # 没有 canonical 产物：交给旧表路径（demo 论文）
        return None

    page_of_media = _media_pages(scope)

    figures: List[Dict[str, Any]] = []
    tables: List[Dict[str, Any]] = []
    for m in media_items:
        if m.kind == "figure":
            figures.append({
                "fig_no": m.legacy_no or (len(figures) + 1),
                "caption": m.caption or "",
                "page": page_of_media.get(m.id, 0),
                "glyph_svg": "",
                "image_b64": "",
                "image_mime": "image/png",
                # 真实图资产的可访问 URL（D-24 落库的 crop asset）。
                # 前端 FigureImage 优先用它；此前只给空 b64/svg → "有摘要没图"。
                "image_url": figure_image_url(m),
                "importance": "medium",
                "description": "",
                # 前端用 media_id 打开真实原件（M03 的 policy 决定展示什么）
                "media_id": m.id,
            })
        elif m.kind == "table":
            extracted = m.extracted
            tables.append({
                "table_no": m.legacy_no or (len(tables) + 1),
                "caption": m.caption or "",
                "page": page_of_media.get(m.id, 0),
                "content": [],
                "table_html": (getattr(extracted, "table_html", "") or ""),
                "key_finding": "",
                "media_id": m.id,
            })

    section_dicts = [
        {
            "heading": s.heading or "",
            "kind": s.kind or "body",
            "page": 1,
            "summary": _text(s.summary),
            "body": _text(s.summary),
            "key_points": [_text(k) for k in (s.key_points or [])],
        }
        for s in sections
    ]
    page_dicts = [
        {"page_no": int(getattr(p, "pdf_page_no", 0) or 0), "text": _page_text(scope, p)}
        for p in page_items
    ]

    paper = papers_mod.get_paper(paper_id)
    metadata = papers_mod.get_metadata(paper_id)
    revision = papers_mod.get_revision(scope)

    detail = to_legacy_detail(
        paper, metadata, revision,
        sections=section_dicts, figures=figures, tables=tables, pages=page_dicts,
    )

    # 路线 A（ADR-0027）：legacy ``papers`` 表里这几列对真实论文是空的，
    # 用 canonical 产物补上——否则地图页六维卡片全是 "—"、摘要/作者行全空。
    derived: Dict[str, Any] = {}
    derived_map = map_summary_from_structure(structure, sections)
    if derived_map:
        derived["map_summary"] = derived_map
    if not (detail.abstract or "").strip() and page_dicts:
        derived_abstract = abstract_from_page_text(page_dicts[0].get("text") or "")
        if derived_abstract:
            derived["abstract"] = derived_abstract
    if derived:
        detail = detail.model_copy(update=derived)

    # method_steps：真实论文的旧 ``papers.method_steps`` 列为空（canonical 把
    # 步骤写进 section_records/method_steps 产物），故用 canonical 结构覆盖。
    if steps:
        detail = detail.model_copy(update={
            "method_steps": [
                _legacy_step(
                    {
                        "id": st.id,
                        "label": _text(st.label),
                        "detail": _text(st.detail),
                        "phase": st.phase,
                    },
                    i,
                )
                for i, st in enumerate(steps)
            ]
        })
    return detail


def _text(value: Any) -> str:
    """``ArtifactText | str | None`` → 纯文本。"""
    if value is None:
        return ""
    text = getattr(value, "text", None)
    if isinstance(text, str):
        return text
    return value if isinstance(value, str) else ""


def _page_text(scope: Scope, page: Any) -> str:
    """旧详情只给页级正文预览（截断由契约方决定，这里限量避免超大响应）。"""
    text = getattr(page, "text", None)
    if isinstance(text, str):
        return text[:4000]
    return ""


def _media_pages(scope: Scope) -> Dict[str, int]:
    """media_id → 物理页码（1-based）；无 anchor 的不出现（调用方记 0）。"""
    from app.models.artifacts import AnchorORM, MediaORM

    out: Dict[str, int] = {}
    with _session() as db:
        rows = db.execute(
            select(MediaORM.id, MediaORM.anchor_ids).where(
                MediaORM.revision_id == scope.revision_id
            )
        ).all()
        anchor_ids = sorted({a for _mid, ids in rows for a in (ids or [])})
        if not anchor_ids:
            return {}
        anchors = db.execute(
            select(AnchorORM.id, AnchorORM.segments).where(AnchorORM.id.in_(anchor_ids))
        ).all()
        page_of_anchor: Dict[str, int] = {}
        for aid, segments in anchors:
            for seg in (segments or []):
                idx = seg.get("pdf_page_index")
                if idx is not None:
                    page_of_anchor[aid] = int(idx) + 1
                    break
        for mid, ids in rows:
            for aid in (ids or []):
                if aid in page_of_anchor:
                    out[mid] = page_of_anchor[aid]
                    break
    return out


def _session():
    from app.core.db import session_scope

    return session_scope()


def _readable_revision(db: Session, paper_id: int) -> Optional[str]:
    """解析该论文当前可读 revision（只读）。与其它 legacy 桥接保持一致。"""
    from app.models.models import Paper

    row = db.get(Paper, paper_id)
    if row is None:
        return None
    if row.readable_revision_id:
        return row.readable_revision_id
    from app.models.source import RevisionORM

    stmt = (
        select(RevisionORM.id)
        .where(RevisionORM.paper_id == paper_id)
        .order_by(RevisionORM.created_at.desc())
        .limit(1)
    )
    found = db.execute(stmt).first()
    return found[0] if found else None


__all__ = ["get_detail"]
