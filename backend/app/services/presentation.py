"""Presentation assembly (Spec §31/§41) — scenes with narration (script/tts/subtitle)."""
from __future__ import annotations

from typing import List

from sqlalchemy.orm import Session

from app import models


def get_presentation(db: Session, paper_id: int) -> dict:
    scenes = (
        db.query(models.Scene)
        .filter(models.Scene.paper_id == paper_id)
        .order_by(models.Scene.order.asc())
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
                "narration": s.narration or {},
            }
            for s in scenes
        ]
    }
