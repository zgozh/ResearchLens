"""FastAPI routes — ResearchLens REST API.

All views in the frontend bind to these endpoints END-TO-END (no fake data).
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, UploadFile, File
from pydantic import BaseModel
from sqlalchemy.orm import Session, selectinload

from app.core.config import settings
from app.core.db import get_db
from app import models
from app.schemas.schemas import (
    AskRequest,
    AskResponse,
    ClaimOut,
    ClaimSummary,
    DemoPaperListItem,
    EvaluationOut,
    GraphOut,
    HealthOut,
    PaperOut,
    PresentationOut,
    SectionOut,
    FigureOut,
    TableOut,
)
from app.seed import demo_papers as demo
from app.modules import claims as claims_svc, evaluation as eval_svc
from app.modules import graph as graph_svc, scene as pres_svc
from app.modules import parse as parser_mod, pipeline
from app.modules import qa as qa_svc
from app.modules.pipeline.ingest import ingest_paper_from_pdf
from app.core import runtime

router = APIRouter(prefix="/api")


# ------------------------------------------------------------------ health
@router.get("/health", response_model=HealthOut)
def health():
    return HealthOut(status="ok", demo_mode=settings.demo_mode, version=settings.version)


# ------------------------------------------------------------------ demo
@router.get("/demo", response_model=List[DemoPaperListItem])
def demo_list(db: Session = Depends(get_db)):
    demo.load_demo_papers(db)  # 确保示例论文存在
    rows = (
        db.query(models.Paper)
        .filter(models.Paper.source_mode.in_(["demo", "real"]))
        .order_by(models.Paper.source_mode.asc(), models.Paper.id.asc())
        .all()
    )
    return [
        DemoPaperListItem(
            slug=p.slug, title=p.title, subtitle=p.subtitle, domain=p.domain, year=p.year,
            tags=p.tags or [], abstract=(p.abstract or "")[:420], accent=p.accent,
            source_mode=p.source_mode,
        )
        for p in rows
    ]


@router.get("/models")
def models_list():
    return {"models": runtime.DASHSCOPE_MODELS, "active": runtime.get_active_model()}


class ModelBody(BaseModel):
    model: str


@router.post("/models")
def models_set(body: ModelBody):
    runtime.set_active_model(body.model)
    return {"active": runtime.get_active_model()}


class FromUrlBody(BaseModel):
    url: str
    title: str = ""


@router.post("/papers/from-url")
def paper_from_url(body: FromUrlBody, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    """下载真实公开论文 PDF 并后台完整抽取；立即返回 paper_id，前端轮询。"""
    import re
    import time as _t
    import httpx as _httpx

    title = body.title.strip() or "Real Paper"
    slug = re.sub(r"[^A-Za-z0-9]+", "-", title).strip("-").lower()[:48] or f"real_{int(_t.time())}"

    pdf_path = None
    try:
        r = _httpx.get(body.url, timeout=120, follow_redirects=True,
                       headers={"User-Agent": "Mozilla/5.0 (ResearchLens)", "Accept": "application/pdf,*/*"})
        r.raise_for_status()
        pdf_path = parser_mod.save_upload(parser_mod.default_upload_dir(), f"{slug}.pdf", r.content)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, f"下载失败：{e}")

    p = models.Paper(slug=slug, title=title, source_mode="real", status="pending", accent="#22D3EE",
                     abstract="真实公开论文 · " + body.url, pdf_url=str(pdf_path))
    db.add(p)
    db.commit()
    pid = p.id

    def _work():
        from app.core.db import SessionLocal as _SL
        s = _SL()
        try:
            data = pdf_path.read_bytes() if pdf_path and pdf_path.exists() else b""
            ingest_paper_from_pdf(s, data, body.url, title)
        except Exception:  # noqa: BLE001
            import traceback; traceback.print_exc()
        finally:
            s.close()

    background_tasks.add_task(_work)
    return {"paper_id": pid, "status": "processing", "slug": slug}


class LoadDemoBody(BaseModel):
    slug: str


@router.post("/demo/load", response_model=PaperOut)
def demo_load(body: LoadDemoBody, db: Session = Depends(get_db)):
    demo.load_demo_papers(db)
    p = db.query(models.Paper).filter(models.Paper.slug == body.slug).first()
    if not p:
        raise HTTPException(404, "demo paper not found")
    return _paper_out(p)


# ------------------------------------------------------------------ papers
@router.get("/papers", response_model=List[PaperOut])
def papers_list(db: Session = Depends(get_db)):
    demo.load_demo_papers(db)
    rows = db.query(models.Paper).order_by(models.Paper.id.asc()).all()
    return [_paper_out(p) for p in rows]


@router.get("/papers/{paper_id}")
def paper_detail(paper_id: int, db: Session = Depends(get_db)):
    p = (
        db.query(models.Paper)
        .options(
            selectinload(models.Paper.sections),
            selectinload(models.Paper.figures),
            selectinload(models.Paper.tables),
        )
        .filter(models.Paper.id == paper_id)
        .first()
    )
    if not p:
        raise HTTPException(404, "paper not found")
    return {
        **_paper_out(p).model_dump(),
        "sections": [SectionOut(heading=s.heading, kind=s.kind, page=s.page, summary=s.summary,
                                body=s.body, key_points=s.key_points or []).model_dump() for s in p.sections],
        "figures": [FigureOut(fig_no=f.fig_no, caption=f.caption, page=f.page, glyph_svg=f.glyph_svg,
                              image_b64=f.image_b64, importance=f.importance, description=f.description).model_dump() for f in p.figures],
        "tables": [TableOut(table_no=t.table_no, caption=t.caption, page=t.page, content=t.content,
                            key_finding=t.key_finding).model_dump() for t in p.tables],
        "method_steps": p.method_steps or [],
        "accent": p.accent,
    }


@router.get("/papers/{paper_id}/claims", response_model=List[ClaimSummary])
def paper_claims(paper_id: int, db: Session = Depends(get_db)):
    return claims_svc.get_claims(db, paper_id)


@router.get("/papers/{paper_id}/claims/{claim_id}", response_model=ClaimOut)
def paper_claim(paper_id: int, claim_id: str, db: Session = Depends(get_db)):
    c = claims_svc.get_claim(db, paper_id, claim_id)
    if not c:
        raise HTTPException(404, "claim not found")
    return c


@router.get("/papers/{paper_id}/graph", response_model=GraphOut)
def paper_graph(paper_id: int, db: Session = Depends(get_db)):
    return GraphOut(**graph_svc.get_graph(db, paper_id))


@router.get("/papers/{paper_id}/presentation", response_model=PresentationOut)
def paper_presentation(paper_id: int, db: Session = Depends(get_db)):
    return PresentationOut(**pres_svc.get_presentation(db, paper_id))


@router.post("/papers/{paper_id}/qa", response_model=AskResponse)
def paper_qa(paper_id: int, body: AskRequest, db: Session = Depends(get_db)):
    return qa_svc.answer_question(db, paper_id, body.question, body.top_k)


@router.get("/papers/{paper_id}/evaluation", response_model=EvaluationOut)
def paper_evaluation(paper_id: int, db: Session = Depends(get_db)):
    ev = eval_svc.compute_evaluation(db, paper_id)
    return EvaluationOut(overall_score=ev.overall_score, metrics=ev.metrics)


# ------------------------------------------------------------------ upload (LIVE path)
@router.post("/papers/upload")
async def paper_upload(file: UploadFile = File(...), db: Session = Depends(get_db)):
    if settings.demo_mode:
        raise HTTPException(400, "DEMO_MODE=true — 请使用 /api/demo 选择内置论文；上传需 DEMO_MODE=false")
    data = await file.read()
    if len(data) > settings.max_upload_mb * 1024 * 1024:
        raise HTTPException(413, "file too large")
    path = parser_mod.save_upload(parser_mod.default_upload_dir(), file.filename or "paper.pdf", data)
    p = models.Paper(
        slug=f"upload_{int(__import__('time').time())}",
        title=file.filename or "Uploaded paper",
        source_mode="upload",
        status="pending",
        pdf_url=str(path),
    )
    db.add(p)
    db.commit()
    job = models.GenerationJob(paper_id=p.id, stage="parse", status="pending")
    db.add(job)
    db.commit()
    return {"paper_id": p.id, "job_id": job.id, "status": "pending"}


@router.post("/papers/{paper_id}/process")
def paper_process(paper_id: int, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    """Trigger the LIVE pipeline (parse → claims → evidence → evaluation) in the
    background. Returns immediately with a job id; poll /api/jobs/{id}."""

    def _work():
        from app.core.db import SessionLocal as _SessionLocal
        s = _SessionLocal()
        try:
            pipeline.run_pipeline(s, paper_id)
        finally:
            s.close()

    job = db.query(models.GenerationJob).filter(
        models.GenerationJob.paper_id == paper_id
    ).order_by(models.GenerationJob.id.desc()).first()
    if job is None:
        job = models.GenerationJob(paper_id=paper_id, stage="parse", status="running")
        db.add(job)
        db.commit()
    else:
        job.status = "running"
        job.stage = "parse"
        db.commit()
    job_id = job.id
    background_tasks.add_task(_work)
    return {"paper_id": paper_id, "job_id": job_id, "status": "running"}


@router.get("/jobs/{job_id}")
def job_status(job_id: int, db: Session = Depends(get_db)):
    j = db.query(models.GenerationJob).filter(models.GenerationJob.id == job_id).first()
    if not j:
        raise HTTPException(404, "job not found")
    from app.modules.pipeline import stage_label
    return {"job_id": j.id, "stage": j.stage, "stage_label": stage_label(j.stage),
            "status": j.status, "paper_id": j.paper_id}


# ------------------------------------------------------------------ helpers
def _paper_out(p: models.Paper) -> PaperOut:
    return PaperOut(
        id=p.id, slug=p.slug, title=p.title, subtitle=p.subtitle, authors=p.authors or [],
        year=p.year, domain=p.domain, abstract=p.abstract or "", tags=p.tags or [],
        source_mode=p.source_mode, status=p.status, map_summary=p.map_summary or {},
        pdf_url=p.pdf_url or "", method_steps=p.method_steps or [],
    )
