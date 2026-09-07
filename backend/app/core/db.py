"""SQLAlchemy engine / session setup.

Decision D-05: SQLite for local dev (zero-dependency), Postgres+pgvector for
Docker/prod; switch via DATABASE_URL. SQLite needs the adjacent directory to exist.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import settings


class Base(DeclarativeBase):
    pass


def _ensure_sqlite_dir(url: str) -> None:
    if url.startswith("sqlite"):
        # sqlite:///./data/researchlens.db  → ensure ./data exists
        raw = url.replace("sqlite:///", "", 1)
        if raw and not raw.startswith(":"):
            p = Path(raw)
            if p.parent and str(p.parent) not in ("", "."):
                p.parent.mkdir(parents=True, exist_ok=True)
        elif raw and raw.startswith(":memory:"):
            pass


_ensure_sqlite_dir(settings.database_url)

_connect_args = {}
_engine_kwargs: dict = {"pool_pre_ping": True}
if settings.database_url.startswith("sqlite"):
    _connect_args = {"check_same_thread": False}
    _engine_kwargs = {"connect_args": _connect_args, "pool_pre_ping": True}

engine = create_engine(settings.database_url, **_engine_kwargs)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def init_db() -> None:
    """Create tables. Import models to register them on Base.metadata."""
    from app import models  # noqa: F401  (register ORM)

    Base.metadata.create_all(bind=engine)


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
