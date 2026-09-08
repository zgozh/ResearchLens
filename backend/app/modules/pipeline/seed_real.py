"""modules/pipeline/seed_real — 首次启动时自举「真实中文论文」。

Docker-only 部署下，数据库从空卷启动。为了让「真实论文」组自带中文论文，
本模块在后端 lifespan 中以后台线程方式抽取 3 篇中文软件学报论文（幂等：按 slug
去重，已存在则跳过）。DEMO_MODE=true 或没有 LLM Key 时不执行。
"""
from __future__ import annotations

import logging
import threading

import httpx

from app import models
from app.core.config import settings

log = logging.getLogger("researchlens.seed_real")

# 真实中文论文：软件学报（开放获取），均为正式出版的科研论文。
REAL_PAPERS = [
    ("https://www.jos.org.cn/josen/article/pdf/5281",
     "基于Haar小波域指标自适应选择载体的JPEG隐写"),
    ("https://www.jos.org.cn/josen/article/pdf/6106",
     "数据驱动的移动应用用户接受度建模与预测"),
    ("https://www.jos.org.cn/josen/article/pdf/6550",
     "基于软件度量的Solidity智能合约缺陷预测方法"),
]

HEADERS = {"User-Agent": "Mozilla/5.0 (ResearchLens) ResearchLens/1.0", "Accept": "application/pdf,*/*"}


def _slug_exists(slug: str) -> bool:
    from app.core.db import SessionLocal

    s = SessionLocal()
    try:
        return (
            s.query(models.Paper)
            .filter(models.Paper.slug == slug)
            .first()
            is not None
        )
    finally:
        s.close()


def provision_real_papers() -> None:
    """如数据库尚无「真实中文论文」，逐一抽取；已在后台线程调用，不阻塞启动。
    按 slug 逐个幂等：某篇已存在则跳过。不设「只要有 real 就跳过」的全局开关，
    以便进程中断/重启（部分成功）后仍能补齐缺失篇目。"""
    if settings.demo_mode or not settings.has_llm:
        log.info("seed_real: DEMO_MODE=true or no LLM key — 跳过真实论文自举")
        return
    from app.modules.pipeline.ingest import _slug_from_title

    missing = [(u, t) for u, t in REAL_PAPERS if not _slug_exists(_slug_from_title(t))]
    if not missing:
        log.info("seed_real: 全部真实论文已存在，跳过")
        return

    from app.core.db import SessionLocal
    from app.modules.pipeline.ingest import ingest_paper_from_pdf

    log.info("seed_real: 自举 %d 篇缺失的真实中文论文", len(missing))
    s = SessionLocal()
    for url, title in missing:
        try:
            r = httpx.get(url, timeout=180, follow_redirects=True, headers=HEADERS)
            r.raise_for_status()
            pid = ingest_paper_from_pdf(s, r.content, url, title)
            log.info("seed_real: [%s] -> paper_id %s", title[:30], pid)
        except Exception as e:  # noqa: BLE001
            import traceback

            traceback.print_exc()
            log.warning("seed_real: %s 失败 %s", title[:30], e)
    s.close()
    log.info("seed_real: 完成")


def start_real_provision_thread() -> None:
    """在 lifespan 中调用：以后台守护线程运行，避免阻塞健康检查。"""
    t = threading.Thread(target=provision_real_papers, name="seed-real", daemon=True)
    t.start()
