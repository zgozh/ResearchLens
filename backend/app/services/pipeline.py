"""Pipeline orchestration (Spec §5/§3). Compose the stateful, degradable flow:

parse → structure → claim_extract → evidence_link → build_graph → present → evaluate

In DEMO_MODE the seeds already encode this IR, so the pipeline is effectively
"ensure loaded". In LIVE mode it runs the real steps via the AI client with the
Evidence Gate always honored (a claim without evidence is marked UNSUPPORTED and
never enters the fact layer).
"""
from __future__ import annotations

import logging
from typing import Dict

from sqlalchemy.orm import Session

from app import models
from app.core.config import settings
from .ai import get_ai
from . import parser as parser_mod, evaluation

log = logging.getLogger("researchlens.pipeline")

_STAGES = ("parse", "claims", "evidence", "graph", "present", "evaluate")


def run_pipeline(db: Session, paper_id: int) -> Dict:
    paper = db.query(models.Paper).filter(models.Paper.id == paper_id).first()
    if not paper:
        return {"ok": False, "stage": "none", "reason": "paper not found"}

    job = db.query(models.GenerationJob).filter(
        models.GenerationJob.paper_id == paper_id,
        models.GenerationJob.status == "running",
    ).first()
    if job is None:
        job = models.GenerationJob(paper_id=paper_id, stage="parse", status="running")
        db.add(job)
        db.commit()
    else:
        job.status = "running"
        job.stage = "parse"
        db.commit()

    try:
        _stage_parse(paper, db, job)
        _stage_claims(paper, db, job)
        evaluation.compute_evaluation(db, paper_id)
        job.status = "done"
        job.stage = "evaluate"
        db.commit()
    except Exception as e:  # noqa: BLE001
        log.exception("pipeline failed")
        job.status = "failed"
        db.commit()
        return {"ok": False, "stage": job.stage, "reason": str(e)}

    return {"ok": True, "stage": "done", "paper_id": paper_id}


def _stage_parse(paper: models.Paper, db: Session, job: models.GenerationJob) -> None:
    if paper.pages or not paper.pdf_url:
        job.stage = "claims"
        db.commit()
        return
    # Live path expects pdf_url pointing to a stored file:
    if paper.pdf_url:
        from pathlib import Path as _P
        src = _P(paper.pdf_url)
        if src.exists():
            data = src.read_bytes()
            parsed = parser_mod.parse_pdf(data)
            # persist pages
            for pg in parsed["pages"]:
                db.add(models.PaperPage(paper_id=paper.id, page_no=pg["page_no"],
                                        text=pg["text"], region_map=pg["region_map"]))
            for sec in parsed["sections"]:
                db.add(models.Section(paper_id=paper.id, heading=sec["heading"],
                                      kind=sec["kind"], page=sec["page"]))
            db.commit()
    job.stage = "claims"
    db.commit()


def _stage_claims(paper: models.Paper, db: Session, job: models.GenerationJob) -> None:
    if paper.claims:
        job.stage = "evidence"
        db.commit()
        return
    ai = get_ai()
    if not ai.ready:
        log.info("no LLM; leaving claims empty (demo path is pre-seeded)")
        job.stage = "evidence"
        db.commit()
        return
    corpus = "\n\n".join(p.text for p in paper.pages)[:20000]
    claims = []
    # claims.py extract guarded by ai.ready
    from .claims import extract_claims

    raw_claims = extract_claims(ai, corpus, {})
    for rc in raw_claims:
        claim = models.Claim(paper_id=paper.id, claim_id=rc.get("claim_id", ""),
                             statement=rc.get("statement", ""), type=rc.get("type", "RESULT"),
                             confidence=rc.get("confidence", 0.9),
                             status="SUPPORTED" if rc.get("evidence") else "UNSUPPORTED")
        db.add(claim)
        db.flush()
        for e in rc.get("evidence", []):
            db.add(models.Evidence(claim_id=claim.id, page=e.get("page", 1),
                                   region=e.get("region", ""), region_type=e.get("region_type", "text"),
                                   text=e.get("text", ""), quote=e.get("quote", "")))
    db.commit()
    job.stage = "evidence"
    db.commit()
