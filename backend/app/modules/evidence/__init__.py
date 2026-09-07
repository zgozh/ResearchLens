"""modules/evidence — 证据模块（Spec §B.4，Evidence Gate）。职责：断言↔证据链接 + Gate。
API: 复用 claims 的证据存取；对无证据断言标记 UNSUPPORTED。
评价：Citation Coverage / Alignment / Unsupported Claim Rate（目标≈0）。"""
# Evidence Gate 逻辑目前在 claims（存取）与 qa（检索）中；此为模块化入口。
from app.services.claims import get_claim, get_claims  # noqa: F401
