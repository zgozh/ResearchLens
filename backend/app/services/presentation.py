"""Presentation/scene assembly (Spec §B.6) — scenes with narration + linked evidence.

增强：每个场景通过 evidence_refs 强关联到论文内的真实断言证据（原文引文/页码/区域），
供「讲解」视图在右侧弹出对应证据。
"""
from __future__ import annotations

import re

from sqlalchemy.orm import Session, selectinload

from app import models


def _discover_evidence(refs, all_evidence, limit: int = 6):
    """把场景的 evidence_refs 解析为论文内真实证据（原文引文）。"""
    items = []
    used = set()
    for ref in refs or []:
        r = str(ref)
        pm = re.search(r"p\.?(\d+)", r)
        page = int(pm.group(1)) if pm else None
        low = r.lower()
        for ev in all_evidence:
            if ev.id in used:
                continue
            ok = False
            if page and ev.page == page:
                ok = True
            for kw in ("method", "experiment", "result", "discussion", "intro", "conclusion", "abstract"):
                if kw in low and kw in (ev.region or "").lower():
                    ok = True
            if ok:
                used.add(ev.id)
                items.append({
                    "type": "text", "page": ev.page, "region": ev.region,
                    "text": ev.text or "", "quote": ev.quote or "",
                })
                if len(items) >= limit:
                    break
        if len(items) >= limit:
            break
    return items


def _discover_figure_refs(scene, paper_id: int) -> list:
    """从场景的 evidence_refs / summary / narration 中提取「图N」「Fig.N」引用，
    仅保留论文内真实存在的图号，用于「讲解」涉及内容点击。"""
    if not scene:
        return []
    text = " ".join(str(x) for x in (scene.evidence_refs or [])) + " " \
        + (scene.summary or "") + " " + str((scene.narration or {}).get("script", ""))
    nums = {int(m.group(1)) for m in re.finditer(r"(?:图|Fig\.?)\s*(\d+)", text)}
    if not nums:
        return []
    from app.core.db import SessionLocal
    from app import models as _m
    s = SessionLocal()
    try:
        existing = {row.fig_no for row in s.query(_m.Figure).filter(_m.Figure.paper_id == paper_id).all()}
    finally:
        s.close()
    return [n for n in sorted(nums) if n in existing]


def _discover_table_refs(scene, paper_id: int) -> list:
    """与 _discover_figure_refs 类似，提取「表N」引用并只保留存在表号。"""
    if not scene:
        return []
    text = " ".join(str(x) for x in (scene.evidence_refs or [])) + " " \
        + (scene.summary or "") + " " + str((scene.narration or {}).get("script", ""))
    nums = {int(m.group(1)) for m in re.finditer(r"(?:表|Table\.?)\s*(\d+)", text)}
    if not nums:
        return []
    from app.core.db import SessionLocal
    from app import models as _m
    s = SessionLocal()
    try:
        existing = {row.table_no for row in s.query(_m.Table).filter(_m.Table.paper_id == paper_id).all()}
    finally:
        s.close()
    return [n for n in sorted(nums) if n in existing]


def get_presentation(db: Session, paper_id: int) -> dict:
    scenes = (
        db.query(models.Scene)
        .filter(models.Scene.paper_id == paper_id)
        .order_by(models.Scene.order.asc())
        .all()
    )
    all_evidence = (
        db.query(models.Evidence)
        .join(models.Claim)
        .filter(models.Claim.paper_id == paper_id)
        .all()
    )
    return {
        "scenes": [
            {
                "order": s.order,
                "title": s.title,
                "kind": s.kind,
                "summary": s.summary,
                "steps": s.steps if s.steps is not None else [],
                "evidence_refs": s.evidence_refs if s.evidence_refs is not None else [],
                "figure_refs": (s.figure_refs if s.figure_refs is not None else []) or _discover_figure_refs(s, paper_id),
                "table_refs": _discover_table_refs(s, paper_id),
                "narration": s.narration or {},
                "linked": _discover_evidence(s.evidence_refs, all_evidence),
            }
            for s in scenes
        ]
    }
