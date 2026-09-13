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
from app.modules.pipeline.ingest import ingest_paper_from_pdf, ingest_pdf_for_paper
from app.core import runtime

router = APIRouter(prefix="/api")


# ------------------------------------------------------------------ health
@router.get("/health", response_model=HealthOut)
def health():
    return HealthOut(status="ok", version=settings.version)


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


def _looks_like_pdf(response) -> bool:
    """响应体是不是真 PDF（**字节优先**）。

    实测：arXiv 的 ``/abs/`` 摘要页、站点报错页都会返回 HTML；有的还在报错页上挂
    ``content-type: application/pdf``。旧实现不看内容就存成 ``.pdf`` 入库，
    于是库里多出一篇永远解析不出来的"论文"。这里以魔数 ``%PDF-`` 为准。
    """
    content = bytes(getattr(response, "content", b"") or b"")
    if content.startswith(b"%PDF-"):
        return True
    ctype = str((getattr(response, "headers", {}) or {}).get("content-type", "")).lower()
    if "pdf" in ctype:
        # 声称是 PDF 但魔数不对：仍按**字节**判断，取前 1KB 里找一眼魔数
        return b"%PDF-" in content[:1024]
    return False


def _pdf_rejection_reason(response) -> str:
    """给用户一句能照做的说明（不要只说"无效"）。"""
    ctype = str((getattr(response, "headers", {}) or {}).get("content-type", "") or "未知")
    return (
        f"该网址返回的不是 PDF（content-type={ctype}）。"
        "请粘贴**论文 PDF 的直链**（例如 arXiv 的 /pdf/xxxx 形式），"
        "不要粘贴摘要页/HTML 页面。"
    )


class FromUrlBody(BaseModel):
    url: str
    title: str = ""


def slug_for_import(*, url: str, title: str = "") -> str:
    """给"网址导入"派生一个**唯一且可读**的 slug（R4 紧急修复）。

    ## 为什么必须派生而不是写常量

    旧实现是 `title = body.title.strip() or "Real Paper"` → `slug = "real-paper"`，
    一个**常量**。而 `papers.slug` 上有唯一索引 —— 只要库里已有一篇 `real-paper`，
    **之后每一次不带标题的网址导入都会 IntegrityError → HTTP 500**（实测日志见
    `test_from_url_slug.py`）。前端 `api.paperFromUrl(url)` 从不传 title，
    所以"粘贴网址"这条路从第二篇起就是坏的。

    ## 派生规则（确定性，便于幂等复用）

    1. 显式给了 `title` → 从标题派生（用户意图优先）；
    2. 否则从 **URL 的路径段**派生，取最后一段有信息量的（`.../pdf/5281` → `jos-5281`）；
    3. 都取不到信息时退化为 URL 摘要哈希（仍然唯一、稳定）。

    **同 URL 必得同 slug** —— 这是"重复导入复用同一篇"的前提。
    """
    import hashlib
    import re as _re

    def _clean(text: str) -> str:
        return _re.sub(r"[^A-Za-z0-9\u4e00-\u9fff]+", "-", text or "").strip("-").lower()

    candidate = _clean(title or "")
    if not candidate:
        path = (url or "").split("?", 1)[0].split("#", 1)[0]
        host = ""
        if "//" in path:
            host = path.split("//", 1)[1].split("/", 1)[0]
            host = _re.sub(r"^www\.", "", host).split(".")[0]   # arxiv / jos / example
        segments = [s for s in path.split("/") if s]
        for seg in reversed(segments):
            cleaned = _clean(_re.sub(r"\.pdf$", "", seg, flags=_re.I))
            # 纯泛化词不算信息量（否则 slug 会退化成 `arxiv-pdf` 这种常量）
            if cleaned and cleaned not in {"pdf", "article", "file", "download", "full", "abs"}:
                candidate = f"{host}-{cleaned}" if host else cleaned
                break
    if not candidate:
        candidate = "paper-" + hashlib.sha256((url or "").encode("utf-8")).hexdigest()[:12]
    return candidate[:56]


@router.post("/papers/from-url")
def paper_from_url(body: FromUrlBody, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    """下载真实公开论文 PDF 并后台完整抽取；立即返回 paper_id，前端轮询。

    **幂等**（R4 修复）：同一 URL 重复导入会复用已有论文，而不是再撞一次唯一索引。
    """
    import httpx as _httpx

    title = body.title.strip()
    slug = slug_for_import(url=body.url, title=title)

    # 幂等：同 URL 已导入过就直接复用（省掉重复下载与重复 LLM 开销，也避免唯一索引冲突）
    existing = db.query(models.Paper).filter(models.Paper.slug == slug).first()
    if existing is not None:
        return {"paper_id": existing.id, "status": "exists", "slug": slug}

    # 标题允许留空 —— publish 阶段会从解析产物回填真实标题/摘要（D-110）
    title = title or slug

    pdf_path = None
    try:
        r = _httpx.get(body.url, timeout=120, follow_redirects=True,
                       headers={"User-Agent": "Mozilla/5.0 (ResearchLens)", "Accept": "application/pdf,*/*"})
        r.raise_for_status()
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, f"下载失败：{e}")

    # **入库前验明是 PDF**（ADR-0064）：否则会建出一篇永远解析不出来的"论文"
    if not _looks_like_pdf(r):
        raise HTTPException(400, _pdf_rejection_reason(r))

    try:
        pdf_path = parser_mod.save_upload(parser_mod.default_upload_dir(), f"{slug}.pdf", r.content)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, f"保存 PDF 失败：{e}")

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
    # canonical 优先：真实论文的 图/表/章节/方法步骤/原文页 全部写在 canonical 表，
    # 而 legacy 的 figures/tables/sections/paper_pages/papers.method_steps 只被
    # demo seed 填充 —— 直接读旧 ORM 会让真实论文这几处全空。
    # 详见 modules/papers/legacy.py；无 canonical 数据时返回 None 走旧路径。
    from app.modules.papers import legacy as papers_legacy

    canonical = papers_legacy.get_detail(db, paper_id)
    if canonical is not None:
        return canonical

    p = (
        db.query(models.Paper)
        .options(
            selectinload(models.Paper.sections),
            selectinload(models.Paper.figures),
            selectinload(models.Paper.tables),
            selectinload(models.Paper.pages),
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
                            table_html=t.table_html or "", key_finding=t.key_finding).model_dump() for t in p.tables],
        "method_steps": p.method_steps or [],
        "pages": [{"page_no": pg.page_no, "text": (pg.text or "")[:4000]} for pg in sorted(p.pages, key=lambda x: x.page_no)],
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
async def paper_upload(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    data = await file.read()
    if len(data) > settings.max_upload_mb * 1024 * 1024:
        raise HTTPException(413, "file too large")
    path = parser_mod.save_upload(parser_mod.default_upload_dir(), file.filename or "paper.pdf", data)
    title = file.filename or "Uploaded paper"
    p = models.Paper(
        slug=f"upload_{int(__import__('time').time())}",
        title=title,
        source_mode="upload",
        status="pending",
        pdf_url=str(path),
    )
    db.add(p)
    db.commit()
    pid = p.id

    def _work():
        # 走**和"粘贴网址"同一条** canonical ingest（ADR-0066）：
        # 旧实现只建 legacy GenerationJob，没有任何消费者 → 论文永远 pending。
        from app.core.db import SessionLocal as _SL

        s = _SL()
        try:
            ingest_pdf_for_paper(pid, data, title=title)
        except Exception:  # noqa: BLE001  失败不入库垃圾状态，只记日志
            import traceback

            traceback.print_exc()
        finally:
            s.close()

    background_tasks.add_task(_work)
    return {"paper_id": pid, "status": "processing"}


@router.post("/papers/{paper_id}/process")
def paper_process(paper_id: int, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    """Trigger the LIVE pipeline (parse → claims → evidence → evaluation) in the
    background. Returns immediately with a job id; poll /api/jobs/{id}."""

    # §5.11：无论文 404（不得对不存在的论文建 job，否则 FK 约束失败）
    if db.query(models.Paper).filter(models.Paper.id == paper_id).first() is None:
        raise HTTPException(404, "paper not found")

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
def _official_url_for(p: models.Paper) -> str:
    """论文的"官网/原文"链接（ADR-0069）。

    真实缺陷（用户实测）：``pdf_url`` 存的是**容器内路径**
    （``/app/data/uploads/attention-is-all-you-need.pdf``），前端把它当相对路径拼到
    ``http://localhost:4002/app/data/...`` → 一定 404。修法两条：
    1. 网址导入的论文有**原始来源 URL**（``sources.source_url``）→ 直接用官网地址；
    2. 上传件没有官网地址 → 指向本服务的文档接口 ``/api/papers/{id}/document``
       （那是**可访问的**地址，不是容器内路径）。
    """
    if not p.pdf_url:
        return ""
    try:
        from sqlalchemy import select as _select

        from app.core.db import SessionLocal as _SL
        from app.models.source import SourceDocumentORM

        with _SL() as db:
            row = db.execute(
                _select(SourceDocumentORM.source_url)
                .where(SourceDocumentORM.paper_id == p.id)
                .order_by(SourceDocumentORM.created_at.desc())
                .limit(1)
            ).scalars().first()
        if row:
            return str(row)
    except Exception:  # noqa: BLE001  来源不可读时退回文档接口
        pass
    return f"/api/papers/{p.id}/document"


def _paper_out(p: models.Paper) -> PaperOut:
    return PaperOut(
        id=p.id, slug=p.slug, title=p.title, subtitle=p.subtitle, authors=p.authors or [],
        year=p.year, domain=p.domain, abstract=p.abstract or "", tags=p.tags or [],
        source_mode=p.source_mode, status=p.status, map_summary=p.map_summary or {},
        pdf_url=_official_url_for(p), method_steps=p.method_steps or [],
    )
