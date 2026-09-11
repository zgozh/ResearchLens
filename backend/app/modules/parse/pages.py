"""M02 — 页码解析与分页读取（REFACTOR_SPEC §5.2、§6.4）。

核心纪律：``resolve_page_label`` **绝不猜固定页差**。
- 唯一且已核实映射 → resolved；
- 多个映射（重号/罗马数字/`p.1587` 类）→ ambiguous，**不选第一页**；
- 查不到 → unresolved（candidates 为空）。

分页读取使用不透明 cursor，绑定 scope 与筛选。
"""
from __future__ import annotations

import base64
import json
from typing import List, Optional, Tuple

from app.contracts.common import PageResult, Scope
from app.contracts.documents import Page, PageLabelMapping, PageResolution
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
    payload = {
        "p": scope.paper_id,
        "r": scope.revision_id,
        "o": int(offset),
        "f": filter_key,
    }
    raw = json.dumps(payload, separators=(",", ":"), ensure_ascii=True)
    return base64.urlsafe_b64encode(raw.encode("utf-8")).decode("ascii")


def decode_cursor(cursor: Optional[str], scope: Scope, filter_key: str = "") -> int:
    """解析 cursor；不透明且绑定 scope/筛选，不匹配视为 INVALID_INPUT。"""
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


def paginate(items: List, scope: Scope, offset: int, limit: int, filter_key: str = "") -> Tuple[List, Optional[str]]:
    """对已排序列表切片；返回 (page_items, next_cursor)。"""
    window = items[offset : offset + limit]
    next_offset = offset + len(window)
    next_cursor = (
        encode_cursor(scope, next_offset, filter_key) if next_offset < len(items) else None
    )
    return window, next_cursor


def page_result(items: List, scope: Scope, total: int, next_cursor: Optional[str]) -> PageResult:
    return PageResult(items=items, next_cursor=next_cursor, total=int(total))


# --------------------------------------------------------------- 标签解析


def resolve_label(
    mappings: List[PageLabelMapping],
    label: str,
    *,
    pdf_page_count: Optional[int] = None,
) -> PageResolution:
    """解析印刷页标签 → PageResolution。

    不做任何"页码 - 物理页 = 常数"的推断。归一化只做无害的空白/大小写处理。
    """
    key = normalise_label(label)
    if not key:
        return PageResolution(status="unresolved", candidates=[])

    exact = [m for m in mappings if normalise_label(m.page_label) == key]
    if not exact:
        # 允许 "12" 与 "p.12" / "第12页" 的等价形式
        alt_key = digit_form(key)
        if alt_key is not None:
            exact = [m for m in mappings if digit_form(normalise_label(m.page_label)) == alt_key]
    if not exact:
        return PageResolution(status="unresolved", candidates=[])

    indices = {m.pdf_page_index for m in exact}
    if len(indices) > 1:
        return PageResolution(status="ambiguous", candidates=exact)

    verified = [m for m in exact if m.status == "verified"]
    if verified:
        return PageResolution(status="resolved", candidates=exact)
    # 唯一但只是 candidate：仍标记为 ambiguous，交由上层决定是否呈现候选
    return PageResolution(status="ambiguous", candidates=exact)


def normalise_label(label: str) -> str:
    return (label or "").strip().strip("·•-–—[]()|").lower()


def digit_form(label: str) -> Optional[str]:
    """把 ``p.12`` / ``第12页`` / ``page 12`` 归一成 ``12``；非数字返回 None。"""
    import re

    if not label:
        return None
    if label.isdigit():
        return label
    match = re.search(r"([0-9]{1,4})", label)
    return match.group(1) if match else None


def find_page_by_index(pages: List[Page], pdf_page_index: int) -> Optional[Page]:
    return next((p for p in pages if p.pdf_page_index == pdf_page_index), None)


def find_page_by_no(pages: List[Page], pdf_page_no: int) -> Optional[Page]:
    """路径物理页 1-based；超范围返回 None（由调用方 404）。"""
    if pdf_page_no < 1:
        return None
    return next((p for p in pages if p.pdf_page_no == pdf_page_no), None)


__all__ = [
    "DEFAULT_LIMIT",
    "MAX_LIMIT",
    "clamp_limit",
    "encode_cursor",
    "decode_cursor",
    "paginate",
    "page_result",
    "resolve_label",
    "normalise_label",
    "digit_form",
    "find_page_by_index",
    "find_page_by_no",
]
