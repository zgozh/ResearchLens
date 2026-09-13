"""ResearchLens API entrypoint."""
from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api import api_router
from app.core.config import settings
from app.core.db import check_schema, init_db, run_migrations
from app.core.errors import DomainError

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    # 正式版本迁移 + 启动版本检查（§2.2 / §5.14）：
    # 迁移幂等（migrations/helpers.py 用 checkfirst），迁移失败或版本不符
    # 直接抛 DomainError 使服务 readiness 失败，绝不静默降级到未知 schema。
    run_migrations()
    check_schema(strict=True)
    # Docker-only 部署：若数据库为空则后台自举「真实中文论文」
    # （含 LLM 抽取，较慢；后台线程不阻塞健康检查）。
    # R4：**不再有 DEMO_MODE 门禁** —— 启动就一定自举，产品永远走完整链路。
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


@app.exception_handler(DomainError)
async def _domain_error_handler(_req: Request, exc: DomainError) -> JSONResponse:
    """把结构化领域错误映射到对应 HTTP 状态（§5.1 错误码表）。

    旧接口兼容：``detail`` 保留字符串或 FastAPI 422 detail 数组（见 legacy_detail）。
    """
    body: dict = {"detail": exc.legacy_detail}
    body["error"] = exc.to_dict()
    return JSONResponse(status_code=exc.http_status, content=body)


@app.get("/")
def root():
    return {"app": settings.app_name, "docs": "/docs"}
