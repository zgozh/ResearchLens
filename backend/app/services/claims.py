"""Claim extraction + serialization (Spec §19 Claim Schema) & Evidence linking."""
from __future__ import annotations

from typing import Dict, List

from sqlalchemy.orm import Session, selectinload

from app import models
from app.schemas.schemas import ClaimOut, ClaimSummary, EvidenceOut

# Accepted claim types mapped to the Evidence Gate status
_CLAIM_TYPES = ("RESULT", "METHOD", "LIMITATION", "CONTEXT")


def get_claims(db: Session, paper_id: int) -> List[ClaimSummary]:
    claims = (
        db.query(models.Claim)
        .options(selectinload(models.Claim.evidence))
        .filter(models.Claim.paper_id == paper_id)
        .order_by(models.Claim.id.asc())
        .all()
    )
    return [
        ClaimSummary(
            claim_id=c.claim_id,
            statement=c.statement,
            type=c.type,
            confidence=c.confidence,
            status=c.status,
            evidence_count=len(c.evidence),
        )
        for c in claims
    ]


def get_claim(db: Session, paper_id: int, claim_id: str) -> ClaimOut | None:
    c = (
        db.query(models.Claim)
        .options(selectinload(models.Claim.evidence))
        .filter(models.Claim.paper_id == paper_id, models.Claim.claim_id == claim_id)
        .first()
    )
    if c is None:
        return None
    return ClaimOut(
        id=c.id,
        claim_id=c.claim_id,
        statement=c.statement,
        type=c.type,
        confidence=c.confidence,
        status=c.status,
        evidence=[
            EvidenceOut(
                id=e.id, page=e.page, region=e.region, region_type=e.region_type,
                text=e.text, quote=e.quote, confidence=e.confidence,
            )
            for e in c.evidence
        ],
    )


# --- Live-mode structured extraction (used only when DEMO_MODE=false) ---
_CLAIM_EXTRACT_SCHEMA = {
    "type": "object",
    "properties": {
        "claims": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "claim_id": {"type": "string"},
                    "statement": {"type": "string"},
                    "type": {"type": "string", "enum": list(_CLAIM_TYPES)},
                    "confidence": {"type": "number"},
                    "evidence": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "page": {"type": "integer"},
                                "region": {"type": "string"},
                                "region_type": {"type": "string", "enum": ["text", "table", "figure", "section"]},
                                "text": {"type": "string"},
                                "quote": {"type": "string"},
                            },
                            "required": ["page", "region", "region_type", "text", "quote"],
                        },
                    },
                },
                "required": ["claim_id", "statement", "type", "confidence", "evidence"],
            },
        }
    },
    "required": ["claims"],
}


def extract_claims(ai, corpus_text: str, structure: Dict) -> List[Dict]:
    """LLM-driven claim extraction (LIVE). Returns raw claim IR dicts or []."""
    if not ai or not ai.ready:
        return []
    prompt = (
        "你是科研内容分析引擎。基于给定的论文结构与正文，提取可验证的断言(claim)。"
        "每个断言必须给出证据（页码/区域/原文引用）。若某断言找不到论文内证据，仍可返回，但 evidence 为空数组。"
        "只返回 JSON。\n\n论文正文摘录：\n" + corpus_text[:12000]
    )
    raw = ai.complete(
        [{"role": "user", "content": prompt}],
        json_schema=_CLAIM_EXTRACT_SCHEMA,
    )
    if not raw or not isinstance(raw, dict):
        return []
    return raw.get("claims", [])
