"""M00 — 数据库引擎 / 会话 / 版本检查（REFACTOR_SPEC §1.5、§5.14）。

替换原实现的「create_all + 静默 ALTER + 吞掉迁移异常」：
- 表结构由 Alembic 版本迁移管理；
- 启动时检查数据库版本，不匹配不静默继续（`check_schema`）；
- SQLite 每连接开启 foreign_keys，并设置 WAL / busy_timeout。
"""
from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Optional

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import settings
from .errors import ErrorCode, DomainError


class Base(DeclarativeBase):
    pass


def _ensure_sqlite_dir(url: str) -> None:
    if url.startswith("sqlite"):
        raw = url.replace("sqlite:///", "", 1)
        if raw and not raw.startswith(":"):
            p = Path(raw)
            if p.parent and str(p.parent) not in ("", "."):
                p.parent.mkdir(parents=True, exist_ok=True)


_ensure_sqlite_dir(settings.database_url)

_engine_kwargs: dict = {"pool_pre_ping": True, "future": True}
if settings.database_url.startswith("sqlite"):
    _engine_kwargs["connect_args"] = {"check_same_thread": False}

engine = create_engine(settings.database_url, **_engine_kwargs)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


if settings.database_url.startswith("sqlite"):

    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_conn, _record):  # pragma: no cover - 依赖真实 sqlite
        cur = dbapi_conn.cursor()
        try:
            cur.execute("PRAGMA foreign_keys=ON")
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA busy_timeout=5000")
            cur.execute("PRAGMA synchronous=NORMAL")
        finally:
            cur.close()


def build_engine(database_url: str):
    """为测试/多环境构造独立引擎（同样的 pragma 策略）。"""
    kwargs: dict = {"pool_pre_ping": True, "future": True}
    if database_url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
    eng = create_engine(database_url, **kwargs)
    if database_url.startswith("sqlite"):

        @event.listens_for(eng, "connect")
        def _pragmas(dbapi_conn, _record):  # pragma: no cover
            cur = dbapi_conn.cursor()
            try:
                cur.execute("PRAGMA foreign_keys=ON")
                cur.execute("PRAGMA journal_mode=WAL")
                cur.execute("PRAGMA busy_timeout=5000")
            finally:
                cur.close()

    return eng


@contextmanager
def session_scope(factory=SessionLocal) -> Iterator[Session]:
    """短事务边界。跨模块不传递 Session；云调用不得持有写事务。"""
    db = factory()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def get_db() -> Iterator[Session]:
    """FastAPI 依赖：请求级只读/短事务会话。"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ---------------------------------------------------------------- 版本检查

ALEMBIC_INI = Path(__file__).resolve().parents[2] / "alembic.ini"


def get_db_revision(database_url: Optional[str] = None) -> Optional[str]:
    """读取数据库当前 Alembic 版本；无版本表返回 None。"""
    eng = engine if database_url is None else build_engine(database_url)
    try:
        insp = inspect(eng)
        if "alembic_version" not in insp.get_table_names():
            return None
        with eng.connect() as conn:
            row = conn.execute(text("SELECT version_num FROM alembic_version")).first()
            return row[0] if row else None
    finally:
        if database_url is not None:
            eng.dispose()


def required_revision() -> Optional[str]:
    """代码期望的 head revision（读 migrations/versions 下最大的 4 位前缀）。"""
    versions_dir = Path(__file__).resolve().parents[2] / "migrations" / "versions"
    if not versions_dir.is_dir():
        return None
    nums = sorted(
        p.name.split("_", 1)[0] for p in versions_dir.glob("*.py") if p.name[:4].isdigit()
    )
    return nums[-1] if nums else None


def check_schema(strict: bool = True) -> dict:
    """检查数据库版本是否与代码期望一致。

    不匹配时：``strict=True`` 抛 DomainError（启动失败），否则只报告。
    """
    current = get_db_revision()
    required = required_revision()
    status = {
        "current": current or "",
        "required": required or "",
        "compatible": bool(required) and current == required,
    }
    if not status["compatible"] and strict:
        raise DomainError(
            ErrorCode.INTERNAL_ERROR,
            f"数据库 schema 版本不符：current={current!r} required={required!r}；"
            "请先执行 alembic upgrade head",
            retryable=False,
        )
    return status


def run_migrations() -> None:
    """执行 alembic upgrade head（程序化调用，供启动/测试使用）。"""
    from alembic import command
    from alembic.config import Config as AlembicConfig

    cfg = AlembicConfig(str(ALEMBIC_INI))
    cfg.set_main_option("sqlalchemy.url", settings.database_url)
    cfg.set_main_option("script_location", str(ALEMBIC_INI.parent / "migrations"))
    # 不让 alembic 的 fileConfig 覆盖调用方的 logging 配置：
    # 否则 disable_existing_loggers 会吞掉 worker/backend 自己的 log（曾导致 worker 日志全空）。
    cfg.attributes["configure_logger"] = False
    command.upgrade(cfg, "head")


def init_db(*, strict: bool = False) -> None:
    """启动入口：确保数据目录存在并（可选严格）检查 schema。

    注意：不再使用 create_all + 静默 ALTER。本地演示若数据库为空，
    调用方应先执行 ``run_migrations()``。
    """
    for d in (settings.data_dir, settings.sources_dir, settings.parser_raw_dir, settings.assets_dir):
        d.mkdir(parents=True, exist_ok=True)
    if strict:
        check_schema(strict=True)


def create_all_fallback() -> None:
    """仅测试/应急：用模型元数据建表（生产路径必须走 Alembic）。"""
    from app import models  # noqa: F401  注册 ORM
    from app.models import source, artifacts, jobs as jobs_model, retrieval, audit  # noqa: F401

    Base.metadata.create_all(bind=engine)


__all__ = [
    "Base",
    "engine",
    "SessionLocal",
    "session_scope",
    "get_db",
    "build_engine",
    "check_schema",
    "run_migrations",
    "init_db",
    "get_db_revision",
    "required_revision",
    "create_all_fallback",
    "ALEMBIC_INI",
]


def _unused(_: int) -> int:  # pragma: no cover
    return os.getpid() + _


