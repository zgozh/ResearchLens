"""scripts/add_page_figures.py — 为已有真实论文补齐「整页图像」兜底图（不用重跑 LLM）。"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx  # noqa: E402

from app.core.db import SessionLocal, init_db  # noqa: E402
import app.models as models  # noqa: E402
from app.modules.pipeline.ingest import extract_figures  # noqa: E402

HEADERS = {"User-Agent": "Mozilla/5.0 (ResearchLens)", "Accept": "application/pdf,*/*"}


def main() -> None:
    init_db()
    s = SessionLocal()
    papers = s.query(models.Paper).filter(models.Paper.source_mode == "real").all()
    for p in papers:
        if not p.pdf_url:
            continue
        print(f"[figs] {p.slug} ...", flush=True)
        try:
            r = httpx.get(p.pdf_url, timeout=120, follow_redirects=True, headers=HEADERS)
            r.raise_for_status()
            figs = extract_figures(r.content)
            # 替换该论文的 figure rows
            s.query(models.Figure).filter(models.Figure.paper_id == p.id).delete()
            s.flush()
            for i, fig in enumerate(figs, start=1):
                s.add(models.Figure(paper_id=p.id, fig_no=i, caption=fig.get("caption", f"论文图 {i}"),
                                    page=fig["page"], image_b64=fig["image_b64"], importance="medium"))
            s.commit()
            print(f"   -> {len(figs)} figures added", flush=True)
        except Exception as e:  # noqa: BLE001
            import traceback; traceback.print_exc()
            print(f"   FAILED: {e}", flush=True)
    s.close()
    print("DONE")


if __name__ == "__main__":
    main()
