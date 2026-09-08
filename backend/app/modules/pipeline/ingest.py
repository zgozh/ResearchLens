"""modules/pipeline/ingest — 真实论文 → 完整厚实中间表示（Reproducible Live 抽取）。

输入：真实公开论文 PDF bytes（+ 可选 url/title）。
输出：完整 IR（pages + 真实图 image_b64 + sections + claims/evidence + scenes/narration + qa + method_steps + graph + eval），并写入 DB。
用 Qwen(LLM) 做结构/断言/场景/问答生成；用 PyMuPDF 提取真实图（base64）。无 GPU。
"""
from __future__ import annotations

import base64
import hashlib
import io
import json
import logging
import re
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app import models
from app.modules.claims import extract_claims

log = logging.getLogger("researchlens.ingest")

try:
    import pymupdf  # type: ignore  (AGPL, 本地/可选依赖；离线处理用)
except Exception:  # pragma: no cover
    pymupdf = None


# --------------------------------------------------------------------- parse
def parse_pdf(data: bytes) -> Dict:
    pages = []
    full_text = ""
    if pymupdf:
        doc = pymupdf.open(stream=data, filetype="pdf")
        texts = []
        for i, page in enumerate(doc):
            t = page.get_text() or ""
            texts.append(t)
            pages.append({"page_no": i + 1, "text": t.strip(), "blocks": []})
        full_text = "\n\n".join(texts)
        doc.close()
    return {"pages": pages, "full_text": full_text, "text": full_text[:24000]}


def extract_figures(data: bytes, max_figs: int = 6, min_target: int = 3) -> List[Dict]:
    """提取论文内真实图；若内置光栅图不足，用「整页图像」兜底（保证每篇都有可视图片）。

    返回 items: {page, image_b64, caption(kind)}  （kind: raster | page）
    """
    if not pymupdf:
        return []
    figs: List[Dict] = []
    seen = set()
    page_seen = set()
    try:
        doc = pymupdf.open(stream=data, filetype="pdf")
        # 1) 光栅内嵌图
        for pno in range(doc.page_count):
            page = doc[pno]
            for info in page.get_image_info(xrefs=True):
                xref = info.get("xref")
                w, h = info.get("width", 0), info.get("height", 0)
                if not xref or w < 150 or h < 80:
                    continue
                try:
                    base = doc.extract_image(xref)
                except Exception:  # noqa: BLE001
                    continue
                img = base.get("image", b"")
                if len(img) < 3000:
                    continue
                md5 = hashlib.md5(img).hexdigest()
                if md5 in seen:
                    continue
                seen.add(md5)
                figs.append({"page": pno + 1, "image_b64": base64.b64encode(img).decode("utf-8"),
                             "caption": f"论文内嵌图 {len(figs) + 1}"})
                if len(figs) >= max_figs:
                    return figs
        # 2) 兜底：整页图像（优先含图的页，其次前几页）
        if len(figs) < min_target:
            candidates = list(range(doc.page_count))
            # 优先有图片块的页
            def page_img_count(pno):
                try:
                    return len(doc[pno].get_image_info(xrefs=True))
                except Exception:  # noqa: BLE001
                    return 0
            candidates.sort(key=lambda p: (-page_img_count(p), p))
            for pno in candidates:
                if len(figs) >= min_target:
                    break
                if pno in page_seen:
                    continue
                page_seen.add(pno)
                try:
                    pix = doc[pno].get_pixmap(dpi=110)
                    img = pix.tobytes("png")
                except Exception:  # noqa: BLE001
                    continue
                md5 = hashlib.md5(img).hexdigest()
                if md5 in seen:
                    continue
                seen.add(md5)
                figs.append({"page": pno + 1, "image_b64": base64.b64encode(img).decode("utf-8"),
                             "caption": f"论文整页 p.{pno + 1}"})
        doc.close()
    except Exception as e:  # noqa: BLE001
        log.warning("extract_figures failed: %s", e)
    return figs[:max_figs]


# --------------------------------------------------------------------- LLM IR
_SECTIONS_SCHEMA = {
    "type": "object",
    "properties": {
        "sections": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "heading": {"type": "string"},
                    "kind": {"type": "string", "enum": ["intro", "method", "experiment", "result", "discussion", "conclusion"]},
                    "page": {"type": "integer"},
                    "summary": {"type": "string"},
                    "body": {"type": "string"},
                    "key_points": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["heading", "kind", "page", "summary", "body", "key_points"],
            },
        }
    },
    "required": ["sections"],
}


def extract_sections(ai, text: str) -> List[Dict]:
    if not ai or not ai.ready:
        return []
    prompt = (
        "你是论文结构分析引擎。阅读论文，提取章节（引言/方法/实验/结果/讨论/结论）。"
        "所有输出用中文。每章节给 heading(中文或原名)、kind、page(估计页码)、summary(一句话)、"
        "body(该章节 4~6 句的中文正文，覆盖关键内容)、key_points(3 个中文要旨)。只返回 JSON。\n\n论文：\n" + text
    )
    raw = ai.complete([{"role": "user", "content": prompt}], json_schema=_SECTIONS_SCHEMA, json_object=True)
    if not isinstance(raw, dict):
        return []
    return raw.get("sections", [])


_SCENES_SCHEMA = {
    "type": "object",
    "properties": {
        "scenes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "kind": {"type": "string", "enum": ["intro", "problem", "method", "experiment", "result", "limitation"]},
                    "summary": {"type": "string"},
                    "steps": {"type": "array", "items": {"type": "object", "properties": {"label": {"type": "string"}, "detail": {"type": "string"}}, "required": ["label", "detail"]}},
                    "narration": {"type": "object", "properties": {"script": {"type": "string"}, "subtitle": {"type": "string"}}, "required": ["script", "subtitle"]},
                    "evidence_refs": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["title", "kind", "summary", "steps", "narration", "evidence_refs"],
            },
        }
    },
    "required": ["scenes"],
}


def extract_scenes(ai, text: str) -> List[Dict]:
    if not ai or not ai.ready:
        return []
    prompt = (
        "你是论文讲解策划。为论文生成 5~6 个讲解场景（研究背景/问题/方法/实验/结果/局限），放在同一种数组中。"
        "每场景给 title、kind、summary(两三句)、steps(每步 {label,detail})、narration({script 讲解词两三句, subtitle 一句话})、evidence_refs(引用如 p.3/Method 或 图1)。"
        "只返回 JSON。\n\n论文：\n" + text
    )
    raw = ai.complete([{"role": "user", "content": prompt}], json_schema=_SCENES_SCHEMA, json_object=True)
    if not isinstance(raw, dict):
        return []
    return raw.get("scenes", [])


_QA_SCHEMA = {
    "type": "object",
    "properties": {
        "qa": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "q": {"type": "string"},
                    "a": {"type": "string"},
                    "confidence": {"type": "string", "enum": ["High", "Medium", "Low"]},
                    "evidence_refs": {"type": "array", "items": {"type": "object", "properties": {"page": {"type": "integer"}, "region": {"type": "string"}, "text": {"type": "string"}, "quote": {"type": "string"}}, "required": ["page", "region", "text", "quote"]}},
                },
                "required": ["q", "a", "confidence", "evidence_refs"],
            },
        }
    },
    "required": ["qa"],
}


def extract_qa(ai, text: str) -> List[Dict]:
    if not ai or not ai.ready:
        return []
    prompt = (
        "为这篇论文生成 4~5 组常见问答，每组含 q(问题)、a(基于论文的中文回答)、confidence(High/Medium/Low)、"
        "evidence_refs(数组，每项 {page 页码, region 区域, text 佐证句, quote 原文引用})。只返回 JSON。\n\n论文：\n" + text
    )
    raw = ai.complete([{"role": "user", "content": prompt}], json_schema=_QA_SCHEMA, json_object=True)
    if not isinstance(raw, dict):
        return []
    return raw.get("qa", [])


_STEPS_SCHEMA = {
    "type": "object",
    "properties": {
        "steps": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "label": {"type": "string"},
                    "phase": {"type": "string"},
                    "detail": {"type": "string"},
                    "text": {"type": "string"},
                    "figure_ref": {"type": "integer"},
                    "color": {"type": "string"},
                },
                "required": ["label", "phase", "detail", "text", "color"],
            },
        }
    },
    "required": ["steps"],
}


def extract_method_steps(ai, text: str) -> List[Dict]:
    if not ai or not ai.ready:
        return []
    prompt = (
        "把论文方法提炼为核心算法流程步骤（4~6 步），所有输出用中文。每步给 label(中文)、phase(如 input/encoder/module/decoder/output)、"
        "detail(一句话)、text(2~3 句中文说明该步骤做什么、为什么)、figure_ref(若该方法图在论文里，给对应图号，否则省略)、"
        "color(六位hex)。只返回 JSON。\n\n论文方法相关：\n" + text[-7000:]
    )
    raw = ai.complete([{"role": "user", "content": prompt}], json_schema=_STEPS_SCHEMA, json_object=True)
    if not isinstance(raw, dict):
        return []
    return raw.get("steps", [])


# --------------------------------------------------------------------- 入库
def _slug_from_title(title: str) -> str:
    import hashlib
    import re

    # 保留 ASCII 词素；中文等非 ASCII 全数折叠后补一个基于标题的稳定哈希后缀，
    # 保证中文标题也能生成唯一、稳定、幂等的 slug。
    s = re.sub(r"[^A-Za-z0-9]+", "-", title).strip("-").lower()
    if not s:
        s = "paper"
    s = s[:100]
    return f"{s}-{hashlib.md5(title.encode('utf-8')).hexdigest()[:6]}"


def ingest_paper_from_pdf(db: Session, data: bytes, url: str = "", title: str = "") -> int:
    parsed = parse_pdf(data)
    text = parsed["text"] or ""
    figures = extract_figures(data)
    ai = None
    from app.services.ai import get_ai
    ai = get_ai()

    title = title.strip() or "Uploaded Paper"
    slug = _slug_from_title(title)
    # 幂等：同 slug 先删旧（含级联子表）
    existing = db.query(models.Paper).filter(models.Paper.slug == slug).first()
    if existing:
        db.delete(existing)
        db.flush()
    paper = models.Paper(slug=slug, title=title, source_mode="real", status="ready",
                         abstract=(parsed["full_text"] or "")[:1200], pdf_url=url or "",
                         accent="#6366F1", map_summary=_default_map(), method_steps=[])
    db.add(paper)
    db.flush()

    for pg in parsed["pages"]:
        db.add(models.PaperPage(paper_id=paper.id, page_no=pg["page_no"], text=pg["text"], blocks=[]))

    # figures
    fig_models = []
    for i, fig in enumerate(figures, start=1):
        fig_no = i
        f = models.Figure(paper_id=paper.id, fig_no=fig_no, caption=fig.get("caption", f"论文图 {fig_no}"),
                          page=fig["page"], image_b64=fig["image_b64"], importance="medium")
        db.add(f)
        fig_models.append(f)
        db.flush()

    # sections
    sections = extract_sections(ai, text) if ai and ai.ready else []
    paper.map_summary = _default_map()
    for s in sections:
        db.add(models.Section(paper_id=paper.id, heading=s.get("heading", ""), kind=s.get("kind", "body"),
                              page=s.get("page", 1), summary=s.get("summary", ""),
                              body=s.get("body", ""), key_points=s.get("key_points", [])))
        _fill_map(paper.map_summary, s.get("kind", ""), s.get("summary", ""))

    # 摘要：优先用引言的摘录，否则用首段正文概括，避免洁面成 PDF 页眉垃圾文本。
    if sections:
        intro = next((x for x in sections if x.get("kind") == "intro"), sections[0])
        abstract = (intro.get("summary") or intro.get("body") or "").strip()
    else:
        abstract = re.sub(r"\s+", " ", parsed["full_text"] or "")[:1200]
    if abstract:
        paper.abstract = abstract[:2000]
    db.flush()

    # claims + evidence
    claims = extract_claims(ai, text, {}) if ai and ai.ready else []
    for c in claims:
        claim = models.Claim(paper_id=paper.id, claim_id=c.get("claim_id", ""), statement=c.get("statement", ""),
                             type=c.get("type", "RESULT"), confidence=c.get("confidence", 0.9),
                             status="SUPPORTED" if c.get("evidence") else "UNSUPPORTED", rationale="")
        db.add(claim)
        db.flush()
        for e in c.get("evidence", []):
            db.add(models.Evidence(claim_id=claim.id, page=e.get("page", 1), region=e.get("region", ""),
                                   region_type=e.get("region_type", "text"), text=e.get("text", ""),
                                   quote=e.get("quote", "")))

    # graph (derived, with real content)
    _add_graph(db, paper.id, claims, paper.map_summary)

    # scenes
    scenes = extract_scenes(ai, text) if ai and ai.ready else []
    for i, sc in enumerate(scenes, start=1):
        db.add(models.Scene(paper_id=paper.id, order=i, title=sc.get("title", ""), kind=sc.get("kind", ""),
                            summary=sc.get("summary", ""), steps=sc.get("steps", []),
                            evidence_refs=sc.get("evidence_refs", []), figure_refs=[],
                            narration=sc.get("narration", {})))

    # qa
    qalist = extract_qa(ai, text) if ai and ai.ready else []
    for qa in qalist:
        db.add(models.Question(paper_id=paper.id, q=qa.get("q", ""), a=qa.get("a", ""),
                               confidence=qa.get("confidence", "High"), evidence_refs=qa.get("evidence_refs", [])))

    # method steps
    steps = extract_method_steps(ai, text) if ai and ai.ready else []
    paper.method_steps = steps

    db.commit()
    from app.modules.evaluation import compute_evaluation
    compute_evaluation(db, paper.id)
    return paper.id


# --------------------------------------------------------------------- helpers
def _default_map() -> Dict:
    return {"problem": "", "method": "", "dataset": "", "experiment": "", "result": "", "limitation": ""}


def _fill_map(m: Dict, kind: str, summary: str) -> None:
    key = {"intro": "problem", "method": "method", "experiment": "experiment",
           "result": "result", "discussion": "limitation", "conclusion": "result"}.get(kind)
    if key and summary:
        m[key] = summary


def _add_graph(db: Session, paper_id: int, claims: List[Dict], pmap: Optional[Dict] = None) -> None:
    pmap = pmap or {}
    nodes = [
        {"id": "g_problem", "kind": "problem", "label": "问题", "props": {"text": pmap.get("problem") or "研究问题与背景"}},
        {"id": "g_method", "kind": "method", "label": "方法", "props": {"text": pmap.get("method") or "方法"}},
        {"id": "g_exp", "kind": "experiment", "label": "实验", "props": {"text": pmap.get("experiment") or pmap.get("dataset") or "实验"}},
    ]
    edges = [{"source": "g_problem", "target": "g_method", "label": "针对"},
             {"source": "g_method", "target": "g_exp", "label": "评测于"}]
    for i, c in enumerate(claims[:6]):
        cid = c.get("claim_id", f"claim_{i}")
        node_id = f"g_claim{i}"
        nodes.append({"id": node_id, "kind": "claim", "label": f"断言 {i+1}", "props": {"text": (c.get("statement") or "")[:120], "claim_id": cid}})
        edges.append({"source": "g_exp", "target": node_id, "label": "支持"})
        for j, e in enumerate((c.get("evidence") or [])[:2]):
            nid = f"g_ev{i}{j}"
            nodes.append({"id": nid, "kind": "evidence", "label": f"证据 p.{e.get('page','')}", "props": {"text": (e.get('text') or e.get('quote') or '')[:80]}})
            edges.append({"source": node_id, "target": nid, "label": "引用"})
    for n in nodes:
        db.add(models.ResearchGraphNode(paper_id=paper_id, node_id=n["id"], kind=n["kind"], label=n["label"], props=n["props"]))
    for e in edges:
        db.add(models.ResearchGraphEdge(paper_id=paper_id, source=e["source"], target=e["target"], label=e["label"]))
