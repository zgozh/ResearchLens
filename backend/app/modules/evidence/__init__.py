"""M04 — 证据、绑定与事实发布闸门（REFACTOR_SPEC §6.6）。

**全系统 Evidence Gate**。已验证事实 / 推断 / 争议 / 缺证之间有不可绕过的状态边界。

边界：M04 不 import M06（避免 claims ↔ evidence 循环）；接收 ``StatementDraft``。
"""
from .service import (  # noqa: F401
    CAPTION_REF_MAX_PER_STATEMENT,
    CAPTION_REF_MIN_SHARED_TOKENS,
    bind,
    bind_media_for_statements,
    export,
    get_anchor,
    get_bindings,
    get_evidence,
    get_evidence_with_validation,
    get_reviews,
    get_verified_media_for_claims,
    mark_review_applied,
    resolve_legacy,
    review,
    save_report,
    validate,
)

__all__ = [
    "CAPTION_REF_MIN_SHARED_TOKENS",
    "CAPTION_REF_MAX_PER_STATEMENT",
    "validate",
    "save_report",
    "get_evidence",
    "get_evidence_with_validation",
    "get_anchor",
    "resolve_legacy",
    "bind",
    "bind_media_for_statements",
    "get_bindings",
    "get_verified_media_for_claims",
    "review",
    "get_reviews",
    "mark_review_applied",
    "export",
]
