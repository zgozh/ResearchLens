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

from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.contracts.common import Scope


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
