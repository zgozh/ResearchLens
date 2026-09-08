"""ResearchLens API entrypoint."""
from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import api_router
from app.core.config import settings
from app.core.db import init_db

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    # Docker-only 部署：若数据库为空且非 DEMO 模式，后台自举「真实中文论文」
    # （含 LLM 抽取，较慢；后台线程不阻塞健康检查）。
    if not settings.demo_mode:
        try:
            from app.modules.pipeline.seed_real import start_real_provision_thread
            start_real_provision_thread()
        except Exception:  # noqa: BLE001
            import traceback; traceback.print_exc()
    yield


app = FastAPI(title=settings.app_name, version=settings.version, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins or ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix="")


@app.get("/")
def root():
    return {"app": settings.app_name, "docs": "/docs", "demo_mode": settings.demo_mode}
