"""modules/claims — 断言模块（Spec §B.3）。职责：从正文提炼「可验证断言」。
API: get_claims / get_claim / extract_claims
评价：断言抽取精度/召回。"""
from app.services.claims import (  # noqa: F401
    extract_claims,
    get_claim,
    get_claims,
)
