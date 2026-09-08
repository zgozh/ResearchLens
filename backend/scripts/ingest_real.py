"""scripts/ingest_real.py — 把真实公开论文（中文软件学报，开放获取）处理后端管线，生成「真实」演示内容。

用法（backend/ 下）：
    python scripts/ingest_real.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx  # noqa: E402

from app.core.db import SessionLocal, init_db  # noqa: E402
import app.models  # noqa: F401
from app.modules.pipeline.ingest import ingest_paper_from_pdf  # noqa: E402

PAPERS = [
    ("https://www.jos.org.cn/josen/article/pdf/5281",
     "基于Haar小波域指标自适应选择载体的JPEG隐写"),
    ("https://www.jos.org.cn/josen/article/pdf/6106",
     "数据驱动的移动应用用户接受度建模与预测"),
    ("https://www.jos.org.cn/josen/article/pdf/6550",
     "基于软件度量的Solidity智能合约缺陷预测方法"),
]

HEADERS = {"User-Agent": "Mozilla/5.0 (ResearchLens) ResearchLens/1.0", "Accept": "application/pdf,*/*"}


def main() -> None:
    init_db()
    s = SessionLocal()
    for url, title in PAPERS:
        print(f"[ingest] {title} ...", flush=True)
        try:
            r = httpx.get(url, timeout=180, follow_redirects=True, headers=HEADERS)
            r.raise_for_status()
            data = r.content
            print(f"   downloaded {len(data)} bytes", flush=True)
            pid = ingest_paper_from_pdf(s, data, url, title)
            print(f"   -> paper_id {pid} saved ({title})", flush=True)
        except Exception as e:  # noqa: BLE001
            import traceback

            traceback.print_exc()
            print(f"   FAILED {title}: {e}", flush=True)
    s.close()
    print("DONE")


if __name__ == "__main__":
    main()
