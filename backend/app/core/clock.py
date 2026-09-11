"""M00 — 时间原语。契约要求所有时间统一 UTC ISO8601（§5.1）。"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone


def utc_now() -> datetime:
    """当前 UTC 时间（aware）。"""
    return datetime.now(timezone.utc)


def utc_iso(dt: datetime | None = None) -> str:
    """UTC ISO8601 字符串；naive datetime 视为 UTC。"""
    value = dt or utc_now()
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def parse_iso(text: str) -> datetime:
    """解析 ISO8601；naive 视为 UTC。"""
    dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def plus_ms(ms: int) -> datetime:
    return utc_now() + timedelta(milliseconds=ms)


def plus_seconds(seconds: int) -> datetime:
    return utc_now() + timedelta(seconds=seconds)


def is_expired(deadline: datetime | None, *, now: datetime | None = None) -> bool:
    if deadline is None:
        return False
    ref = now or utc_now()
    if deadline.tzinfo is None:
        deadline = deadline.replace(tzinfo=timezone.utc)
    return ref >= deadline


__all__ = ["utc_now", "utc_iso", "parse_iso", "plus_ms", "plus_seconds", "is_expired"]
