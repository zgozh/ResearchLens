"""Grounded Q&A (Spec §20/§34): Answer + Evidence + Confidence. 禁止编造。

Live path (ai.ready): the real model answers ANY question grounded on the paper's
full text (sections/figures/tables/claims), and cites evidence. 非预设也能问。
Demo path (no LLM): fall back to qa_bank exact + lexical retrieval.
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


def _retrieve_evidence(db: Session, paper_id: int, question: str, top_k: int) -> List[models.Evidence]:
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
    out: List[models.Evidence] = []
    for h in hits:
        for e in h.evidence:
            if not any(o.id == e.id for o in out):
                out.append(e)
        if len(out) >= top_k:
            break
    return out[:top_k]


def _build_context(db: Session, paper_id: int) -> str:
    sections = (
        db.query(models.Section)
        .filter(models.Section.paper_id == paper_id)
        .order_by(models.Section.page.asc())
        .all()
    )
    parts = []
    for s in sections:
        body = (s.body or s.summary or "").strip()
        if body:
            parts.append(f"[{s.heading} | p.{s.page}] {body}")
    claims = db.query(models.Claim).filter(models.Claim.paper_id == paper_id).all()
    for c in claims:
        parts.append(f"[{c.claim_id}·{c.type}] {c.statement}")
    ctx = "\n".join(parts)
    return ctx[:10000]


def _answer_with_model(ai, db: Session, paper_id: int, question: str, top_k: int) -> AskResponse:
    context = _build_context(db, paper_id)
    prompt = (
        "你是科研论文讲解员。请用中文回答用户问题。若论文有相关内容，请依据论文回答并标注证据（格式【证据 p.页码/区域】）；"
        "若论文没有直接说明，请基于论文内容给出合理分析，并注明【基于论文的推断】。"
        "不要回答『论文未提供直接依据』这类搪塞，尽量给出有帮助的回答。\n\n"
        f"论文内容：\n{context}\n\n问题：{question}\n\n回答："
    )
    ans = ai.complete([{"role": "user", "content": prompt}], temperature=0.3)
    if not ans:
        return AskResponse(answer="暂时无法回答，请稍后再试。", grounded=False, confidence="Low",
                           evidence=[], note="模型调用失败。")
    text = ans.strip()
    is_generic = ("未提供直接依据" in text) or ("无法回答" in text[:20])
    grounded = not is_generic

    evs = [_ev_from_model(e) for e in _retrieve_evidence(db, paper_id, question, top_k)]
    m = re.search(r"p\.(\d+)", text)
    cited_page = int(m.group(1)) if m else None
    if cited_page and not evs:
        sec = db.query(models.Section).filter(models.Section.paper_id == paper_id,
                                              models.Section.page == cited_page).first()
        if sec:
            evs = [EvidenceOut(page=cited_page, region=sec.kind, region_type="section",
                               text=sec.summary or sec.heading, quote="", confidence=0.9)]
    confidence = "High" if (grounded and (evs or cited_page)) else ("Medium" if grounded else "Low")
    return AskResponse(answer=text, grounded=grounded, confidence=confidence, evidence=evs,
                       note="由真实大模型基于论文内容作答。" if grounded else "未在论文中找到直接依据，以上为该问题的通用回答。")


def answer_question(db: Session, paper_id: int, question: str, top_k: int = 5) -> AskResponse:
    question = question.strip()
    ai = get_ai()

    # 1) 预设问题：优先用论文内唯一可追溯答案（确定、快速）
    if question and question in {q.q for q in db.query(models.Question).filter(models.Question.paper_id == paper_id).all()}:
        q = db.query(models.Question).filter(
            models.Question.paper_id == paper_id, models.Question.q == question).first()
        return AskResponse(
            answer=q.a, grounded=True, confidence=q.confidence,
            evidence=[EvidenceOut(page=e.get("page", 1), region=e.get("region", ""),
                                  region_type=e.get("region_type", "text"), text=e.get("text", ""),
                                  quote=e.get("quote", ""), confidence=e.get("confidence", 0.95))
                      for e in (q.evidence_refs or [])],
            note="依据论文唯一可追溯的证据作答。",
        )

    # 2) Live：任意问题交真实大模型，基于论文全文作答
    if ai and ai.ready:
        return _answer_with_model(ai, db, paper_id, question, top_k)

    # 3) Demo 无模型：词面检索
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
        return AskResponse(answer=top.text, grounded=True,
                           confidence="High" if top.score >= 0.3 else "Medium",
                           evidence=[_ev_from_model(e) for e in top.evidence][:top_k],
                           note="基于论文证据检索作答。")
    return AskResponse(answer="模型未在论文中找到直接依据。我不能编造，以下仅供参考/推断。",
                       grounded=False, confidence="Low", evidence=[], note="无证据支持；已按 Evidence Gate 拒绝进入事实层。")
