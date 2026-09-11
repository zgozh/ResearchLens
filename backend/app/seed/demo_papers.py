"""Demo paper loader — hydrates the DB from the IR (idempotent: skip-if-exists).

DEMO_MODE reads these seeds; no LLM / API key needed.
"""
from __future__ import annotations

from typing import Dict, List

from sqlalchemy.orm import Session

from app import models
from . import paper_learnflow, paper_netguard, paper_visionlens

FIRST_SLUGS = [paper_visionlens.SLUG, paper_netguard.SLUG, paper_learnflow.SLUG]

BUILDERS = {
    paper_visionlens.SLUG: paper_visionlens.build,
    paper_netguard.SLUG: paper_netguard.build,
    paper_learnflow.SLUG: paper_learnflow.build,
}


def _persist_paper(db: Session, ir: Dict) -> None:
    slug = ir["slug"]
    # 幂等：已存在则跳过（D20 禁止同 slug 删除重建破坏稳定 ID；
    # 且 canonical 表 revisions/source_documents 的 paper_id FK 无 CASCADE，
    # 批量 delete 会触发 FK 约束失败）。
    existing = db.query(models.Paper).filter(models.Paper.slug == slug).first()
    if existing is not None:
        return

    paper = models.Paper(
        slug=slug,
        title=ir["title"],
        subtitle=ir.get("subtitle", ""),
        authors=ir.get("authors", []),
        year=ir.get("year", 2026),
        domain=ir.get("domain", "general"),
        abstract=ir.get("abstract", ""),
        tags=ir.get("tags", []),
        source_mode="demo",
        status="ready",
        accent=ir.get("accent", "#6366F1"),
        map_summary=ir.get("map", {}),
        method_steps=ir.get("method_steps", []),
    )
    db.add(paper)
    db.flush()

    for pg in ir.get("pages", []):
        db.add(models.PaperPage(paper_id=paper.id, page_no=pg.get("page_no", 1),
                                text=pg.get("text", ""), blocks=pg.get("blocks", [])))
    for s in ir.get("sections", []):
        db.add(models.Section(paper_id=paper.id, heading=s["heading"], kind=s.get("kind", "body"),
                              page=s.get("page", 1), summary=s.get("summary", ""),
                              body=s.get("body", ""), key_points=s.get("key_points", [])))
    for f in ir.get("figures", []):
        db.add(models.Figure(paper_id=paper.id, fig_no=f["fig_no"], caption=f.get("caption", ""),
                             page=f.get("page", 1), glyph_svg=f.get("glyph_svg", ""),
                             importance=f.get("importance", "medium"), description=f.get("description", "")))
    for t in ir.get("tables", []):
        db.add(models.Table(paper_id=paper.id, table_no=t.get("table_no", 0), caption=t.get("caption", ""),
                            page=t.get("page", 1), content=t.get("content", []),
                            key_finding=t.get("key_finding", "")))
    for idx, c in enumerate(ir.get("claims", []), start=1):
        claim = models.Claim(
            paper_id=paper.id,
            claim_id=c["claim_id"],
            statement=c["statement"],
            type=c.get("type", "RESULT"),
            confidence=c.get("confidence", 0.9),
            status="SUPPORTED" if c.get("evidence") else "UNSUPPORTED",
            rationale=c.get("rationale", ""),
        )
        db.add(claim)
        db.flush()
        for e in c.get("evidence", []):
            db.add(models.Evidence(claim_id=claim.id, page=e.get("page", 1), region=e.get("region", ""),
                                   region_type=e.get("region_type", "text"), text=e.get("text", ""),
                                   quote=e.get("quote", ""), confidence=e.get("confidence", 0.95)))

    g = ir.get("graph", {})
    for n in g.get("nodes", []):
        db.add(models.ResearchGraphNode(paper_id=paper.id, node_id=n["node_id"], kind=n["kind"],
                                        label=n["label"], props=n.get("props", {})))
    for e in g.get("edges", []):
        db.add(models.ResearchGraphEdge(paper_id=paper.id, source=e["source"], target=e["target"],
                                        label=e.get("label", "")))

    for sc in ir.get("presentation", []):
        db.add(models.Scene(paper_id=paper.id, order=sc.get("order", 0), title=sc.get("title", ""),
                            kind=sc.get("kind", ""), summary=sc.get("summary", ""),
                            steps=sc.get("steps", []), evidence_refs=sc.get("evidence_refs", []),
                            figure_refs=sc.get("figure_refs", []),
                            narration=sc.get("narration", {})))

    for qa in ir.get("qa_bank", []):
        db.add(models.Question(paper_id=paper.id, q=qa["q"], a=qa["a"],
                               evidence_refs=qa.get("evidence_refs", []), confidence=qa.get("confidence", "High")))

    db.flush()


def load_demo_papers(db: Session) -> List[str]:
    """Ensure all demo papers exist; return slugs (in canonical order)."""
    for slug in FIRST_SLUGS:
        _persist_paper(db, BUILDERS[slug]())
    db.commit()
    return list(FIRST_SLUGS)


def list_demo_papers(db: Session) -> List[models.Paper]:
    load_demo_papers(db)
    return [q for q in db.query(models.Paper).filter(models.Paper.source_mode == "demo").all()]


def get_demo_metas() -> List[Dict]:
    """Lightweight list for the landing page (no DB required)."""
    out = []
    for slug in FIRST_SLUGS:
        ir = BUILDERS[slug]()
        out.append({
            "slug": ir["slug"],
            "title": ir["title"],
            "subtitle": ir.get("subtitle", ""),
            "domain": ir.get("domain", "general"),
            "year": ir.get("year", 2026),
            "tags": ir.get("tags", []),
            "abstract": ir.get("abstract", ""),
            "accent": ir.get("accent", "#6366F1"),
        })
    return out
