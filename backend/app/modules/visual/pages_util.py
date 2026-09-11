"""M03 — 分页游标（REFACTOR_SPEC §5.1 PageResult）。

与 M02 的 cursor 语义一致（不透明、绑定 scope/筛选），但保持模块自洽——
M03 不导入 M02 的内部实现，避免把 parse 的私有实现变成跨模块契约。
"""
from __future__ import annotations

import base64
import json
from typing import Optional

from app.contracts.common import Scope
from app.core.errors import invalid_input

DEFAULT_LIMIT = 50
MAX_LIMIT = 200


def clamp_limit(limit: Optional[int]) -> int:
    if limit is None:
        return DEFAULT_LIMIT
    try:
        value = int(limit)
    except (TypeError, ValueError):
        raise invalid_input("limit 必须是整数", field="limit")
    if value <= 0:
        raise invalid_input("limit 必须为正整数", field="limit")
    return min(value, MAX_LIMIT)


def encode_cursor(scope: Scope, offset: int, filter_key: str = "") -> str:
    payload = {"p": scope.paper_id, "r": scope.revision_id, "o": int(offset), "f": filter_key}
    raw = json.dumps(payload, separators=(",", ":"), ensure_ascii=True)
    return base64.urlsafe_b64encode(raw.encode("utf-8")).decode("ascii")


def decode_cursor(cursor: Optional[str], scope: Scope, filter_key: str = "") -> int:
    if not cursor:
        return 0
    try:
        raw = base64.urlsafe_b64decode(cursor.encode("ascii")).decode("utf-8")
        payload = json.loads(raw)
    except Exception as exc:  # noqa: BLE001
        raise invalid_input("cursor 无效", field="cursor") from exc
    if int(payload.get("p", -1)) != int(scope.paper_id):
        raise invalid_input("cursor 与当前论文不匹配", field="cursor")
    if str(payload.get("r", "")) != str(scope.revision_id):
        raise invalid_input("cursor 与当前修订版不匹配", field="cursor")
    if str(payload.get("f", "")) != filter_key:
        raise invalid_input("cursor 与当前筛选条件不匹配", field="cursor")
    return max(0, int(payload.get("o", 0)))


__all__ = ["DEFAULT_LIMIT", "MAX_LIMIT", "clamp_limit", "encode_cursor", "decode_cursor"]
