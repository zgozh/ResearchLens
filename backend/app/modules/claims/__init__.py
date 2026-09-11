"""M06 — 断言、结构概览与方法步骤（REFACTOR_SPEC §6.8）。

边界：M06 调用 M04 gate，不直接修改 Page/Block；draft 永不直接 SUPPORTED；
生成文字全部注册 statements；public claim_id ≤32 且同 revision 唯一。
"""
from .service import (  # noqa: F401
    build_artifact_text,
    build_structure,
    extract,
    get_claim as _get_claim_canonical,
    get_statements,
    get_structure,
    get_verified_statements,
    list_claims,
    register_statement,
    verify_and_store,
)


def get_claim(*args, **kwargs):
    """兼容分派：``get_claim(scope, claim_id)`` 走 canonical；
    ``get_claim(db, paper_id, claim_id)`` 走旧 HTTP 投影（``ClaimOut``）。
    """
    from app.contracts.common import Scope

    if args and isinstance(args[0], Scope):
        return _get_claim_canonical(*args, **kwargs)
    from app.services.claims import get_claim as _legacy

    return _legacy(*args, **kwargs)


#: 旧 HTTP 兼容投影（canonical 优先 + 旧表兜底）。定义在 ``legacy.py``，
#: 与 graph/scene/evaluation 的同名桥接保持一致。
from .legacy import get_claims  # noqa: E402,F401

__all__ = [
    "extract",
    "verify_and_store",
    "build_structure",
    "list_claims",
    "get_claim",
    "get_structure",
    "get_statements",
    "get_verified_statements",
    "register_statement",
    "build_artifact_text",
    "extract_claims",
    "get_claims",
]


def extract_claims(ai, corpus_text, structure):
    """旧 pipeline 兼容入口（ingest 仍以 ``extract_claims(ai, text, {})`` 调用）。

    转发到 ``app.services.claims`` 的既有实现，保持旧 IR 形状；canonical
    入口是 ``extract``/``verify_and_store``。**惰性导入避免循环依赖。**
    """
    from app.services.claims import extract_claims as _impl

    return _impl(ai, corpus_text, structure)
