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
        rationale=c.rationale or "",
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
        "你是科研内容分析引擎。仔细阅读下面的论文正文，提取**尽可能多且彼此独立**的可验证断言(claim)。\n"
        "要求：\n"
        "1. 每个独立的事实/结论/方法/局限，都作为单独的 claim 提取（通常 8~12 条，不要合并）。\n"
        "2. 每条 claim 必须给出证据 evidence：page(页码)、region(区域如 table_1 / fig_2 / discussion / method)、"
        "region_type(text|table|figure|section)、text(论文原文佐证句)、quote(关键引用)。\n"
        "3. 每条 claim 只关联最相关的 1~2 条证据，不要把所有证据塞进一条。\n"
        "4. 若某条断言在正文找不到对应证据，evidence 可为空数组（但尽量找）。\n"
        "5. 只返回 JSON。\n\n论文正文：\n" + corpus_text[:14000]
    )
    raw = ai.complete(
        [{"role": "user", "content": prompt}],
        json_schema=_CLAIM_EXTRACT_SCHEMA,
        json_object=True,
    )
    if not raw or not isinstance(raw, dict):
        return []
    claims = raw.get("claims", [])
    if not isinstance(claims, list):
        return []
    return [c for c in claims if isinstance(c, dict) and c.get("statement")]
