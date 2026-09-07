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
                "figure_refs": s.figure_refs if s.figure_refs is not None else [],
                "narration": s.narration or {},
                "linked": _discover_evidence(s.evidence_refs, all_evidence),
            }
            for s in scenes
        ]
    }
