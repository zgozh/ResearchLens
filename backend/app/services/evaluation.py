"""ResearchLens Evaluation — REAL computed metrics (Spec §21/§22/§35).

Metrics are computed from the actual claim↔evidence linkage in the store, so the
dashboard shows genuine numbers (not fabricated). For demo papers these are still
real: they count how many claims carry at least one evidence, the alignment, and
the unsupported-claim rate.
"""
from __future__ import annotations

from typing import Dict

from sqlalchemy.orm import Session, selectinload

from app import models

# Weighted overall score components.
_WEIGHTS = {
    "citation_coverage": 0.22,
    "claim_evidence_alignment": 0.24,
    "unsupported_claim_rate": 0.20,   # inverted
    "structure_accuracy": 0.14,
    "visual_consistency": 0.10,
    "answer_grounding": 0.10,
}


def compute_evaluation(db: Session, paper_id: int) -> models.Evaluation:
    paper = (
        db.query(models.Paper)
        .options(selectinload(models.Paper.claims))
        .filter(models.Paper.id == paper_id)
        .first()
    )
    claims: list = paper.claims if paper else []

    n = len(claims)
    supported = [c for c in claims if c.evidence]
    unsupported = [c for c in claims if not c.evidence]  # Evidence Gate violation
    citation_coverage = len(supported) / n if n else 0.0
    unsupported_rate = len(unsupported) / n if n else 0.0

    # claim↔evidence alignment: average confidence of the best evidence per claim
    aligns = []
    for c in supported:
        best = max((e.confidence for e in c.evidence), default=0.9)
        aligns.append(best)
    alignment = sum(aligns) / len(aligns) if aligns else 0.0

    # structure accuracy proxy: fraction of sections that carry a kind mapping
    section_kinds = {
        "intro": 1, "method": 1, "experiment": 1, "result": 1,
        "discussion": 1, "conclusion": 1,
    }
    total_sections = db.query(models.Section).filter(models.Section.paper_id == paper_id).count()
    known_sections = (
        db.query(models.Section)
        .filter(models.Section.paper_id == paper_id, models.Section.kind.in_(list(section_kinds)))
        .count()
    )
    structure_accuracy = known_sections / total_sections if total_sections else 0.0

    # visual consistency proxy: fraction of claims that refer to a figure/table region
    visual = 0
    for c in claims:
        if any(e.region_type in ("figure", "table") for e in c.evidence):
            visual += 1
    visual_consistency = visual / n if n else 0.0

    # answer grounding proxy: fraction of qa_bank entries that carry evidence
    qas = db.query(models.Question).filter(models.Question.paper_id == paper_id).all()
    grounded_qas = [q for q in qas if q.evidence_refs]
    answer_grounding = len(grounded_qas) / len(qas) if qas else 0.0

    metrics: Dict[str, float] = {
        "citation_coverage": round(citation_coverage * 100, 1),
        "claim_evidence_alignment": round(alignment * 100, 1),
        "unsupported_claim_rate": round(unsupported_rate * 100, 1),
        "structure_accuracy": round(structure_accuracy * 100, 1),
        "visual_consistency": round(visual_consistency * 100, 1),
        "answer_grounding": round(answer_grounding * 100, 1),
        "num_claims": n,
        "num_supported": len(supported),
        "num_unsupported": len(unsupported),
    }

    # overall (unsupported rate inverted so higher = better)
    overall = (
        _WEIGHTS["citation_coverage"] * citation_coverage
        + _WEIGHTS["claim_evidence_alignment"] * alignment
        + _WEIGHTS["unsupported_claim_rate"] * (1 - unsupported_rate)
        + _WEIGHTS["structure_accuracy"] * structure_accuracy
        + _WEIGHTS["visual_consistency"] * visual_consistency
        + _WEIGHTS["answer_grounding"] * answer_grounding
    )

    ev = (
        db.query(models.Evaluation)
        .filter(models.Evaluation.paper_id == paper_id)
        .order_by(models.Evaluation.id.desc())
        .first()
    )
    if ev is None:
        ev = models.Evaluation(paper_id=paper_id)
        db.add(ev)
    ev.metrics = metrics
    ev.overall_score = round(overall * 100, 1)
    db.commit()
    return ev
