"""Grounded Q&A (Spec §20/§34): Answer + Evidence + Confidence. 禁止编造。

Demo path (no LLM): retrieval over the paper's qa_bank and claim/evidence store.
Live path: shallow RAG over the store (embeddings optional) → grounded synthesis.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Optional

from sqlalchemy.orm import Session, selectinload

from app import models
from app.schemas.schemas import AskResponse, EvidenceOut
from .ai import get_ai


@dataclass
class _Hit:
    text: str
    score: float
    evidence: List
    confidence: str


def _ngrams(text: str, n: int = 2) -> set:
    text = re.sub(r"[，。；：！？、\s,.!?;:()（）\[\]{}'\"“”‘’一-]+", "", text.lower())
    grams = {text[i : i + n] for i in range(len(text) - n + 1)} if len(text) >= n else set()
    if not grams:
        grams = {text}
    return grams


def _lexical_sim(a: str, b: str) -> float:
    ga, gb = _ngrams(a), _ngrams(b)
    if not ga or not gb:
        return 0.0
    inter = len(ga & gb)
    union = len(ga | gb)
    return inter / union if union else 0.0


def _ev_from_model(e) -> EvidenceOut:
    return EvidenceOut(id=e.id, page=e.page, region=e.region, region_type=e.region_type,
                       text=e.text, quote=e.quote, confidence=e.confidence)


def answer_question(db: Session, paper_id: int, question: str, top_k: int = 5) -> AskResponse:
    question = question.strip()

    # 1) QA bank exact-ish retrieval — strongest grounding
    qas = db.query(models.Question).filter(models.Question.paper_id == paper_id).all()
    best = None
    for q in qas:
        s = _lexical_sim(question, q.q)
        s2 = _lexical_sim(question, q.a) * 0.7
        score = max(s, s2)
        if best is None or score > best[0]:
            best = (score, q)
    if best and best[0] >= 0.16:
        _, q = best
        evs = [EvidenceOut(**e) if isinstance(e, dict) else e for e in (q.evidence_refs or [])]
        return AskResponse(
            answer=q.a, grounded=True, confidence=q.confidence,
            evidence=[EvidenceOut(page=e.get("page", 1), region=e.get("region", ""),
                                  region_type=e.get("region_type", "text"),
                                  text=e.get("text", ""), quote=e.get("quote", ""),
                                  confidence=e.get("confidence", 0.95)) for e in (q.evidence_refs or [])],
            note="依据论文唯一可追溯的证据作答。",
        )

    # 2) Claim/evidence retrieval — grounded answer from the store
    claims = (
        db.query(models.Claim)
        .options(selectinload(models.Claim.evidence))
        .filter(models.Claim.paper_id == paper_id)
        .all()
    )
    hits: List[_Hit] = []
    for c in claims:
        score = _lexical_sim(question, c.statement)
        for e in c.evidence:
            score = max(score, _lexical_sim(question, e.text) * 0.9)
        if score > 0:
            hits.append(_Hit(text=c.statement, score=score, evidence=list(c.evidence), confidence=c.confidence))
    hits.sort(key=lambda h: h.score, reverse=True)

    if hits and hits[0].score >= 0.14:
        top = hits[0]
        return AskResponse(
            answer=top.text,
            grounded=True,
            confidence="High" if top.score >= 0.3 else "Medium",
            evidence=[_ev_from_model(e) for e in top.evidence][: top_k],
            note="基于论文证据检索作答（引用自论文内断言与证据）。",
        )

    # 3) No grounding → refuse to fabricate (Spec §20)
    return AskResponse(
        answer="模型未在论文中找到直接依据。我不能编造，以下仅供参考/推断。",
        grounded=False,
        confidence="Low",
        evidence=[],
        note="无证据支持；已按 Evidence Gate 拒绝进入事实层。",
    )


def build_qa_hint(question: str) -> str:
    return question
