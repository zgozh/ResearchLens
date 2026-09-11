"""M06 — 旧 HTTP 兼容适配（REFACTOR_SPEC §5.11、§5.10 M13）。

``api/routes.py`` 仍以 ``get_claims(db, paper_id)`` 调用本包；本模块把旧
``Session`` 用法翻译成 canonical 入口（内部自开 ``session_scope``），
再投影为 ``ClaimSummary`` 兼容形状。

## 为什么需要这个模块

真实论文的断言由 M11 pipeline 写入 **canonical** 表
（``claim_records`` / ``statements``），而旧 ``claims`` 表只在 **demo seed**
路径被填充。此前 ``get_claims`` 直接转发 ``app.services.claims``（读旧表）：

- demo/synthetic 论文：有内容（旧表被 seed 填过）；
- **真实论文：恒为空**——即使 canonical 里已有 17 条断言。

同目录之外的 ``graph/legacy.py``、``scene/legacy.py``、``evaluation/legacy.py``
早已是这种「canonical 优先 + 旧表兜底」的桥接写法，本模块补齐 claims 这一条。

纪律：找不到 revision 或无 canonical 断言时**兜底读旧表**，绝不编造断言。
"""
from __future__ import annotations

from typing import Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.contracts.common import Scope
from app.schemas.adapters import to_legacy_claim_summary
from app.schemas.schemas import ClaimSummary

from . import service as svc


def get_claims(db: Session, paper_id: int) -> List[ClaimSummary]:
    """旧签名：返回 ``ClaimSummary`` 列表（canonical 优先，旧表兜底）。"""
    revision_id = _readable_revision(db, paper_id)
    if revision_id:
        scope = Scope(paper_id=paper_id, revision_id=revision_id)
        try:
            claims = svc.list_claims(scope)
        except Exception:  # noqa: BLE001 - 兼容层不得把异常泄漏成 500
            claims = []
        if claims:
            texts = _statement_texts(scope)
            return [
                to_legacy_claim_summary(c).model_copy(
                    # 旧 ``ClaimSummary.statement`` 承载断言正文；canonical 把正文
                    # 放在 statements 表，故按 statement_id 回填，前端断言列表要用。
                    update={"statement": texts.get(c.statement_id or "", "") or ""}
                )
                for c in claims
            ]

    # 兜底：demo/synthetic 论文（只有旧表有数据）
    from app.services.claims import get_claims as _legacy

    return _legacy(db, paper_id)


def _statement_texts(scope: Scope) -> Dict[str, str]:
    """statement_id → 原文陈述文本。"""
    try:
        statements = svc.get_statements(scope, [])
    except Exception:  # noqa: BLE001
        return {}
    return {s.id: (s.text or "") for s in statements}


def _readable_revision(db: Session, paper_id: int) -> Optional[str]:
    """解析该论文当前可读 revision（只读，不写库）。

    与 ``graph/legacy.py`` 的同名函数保持一致：先取 readable 指针，
    再回退到最近一条 revision。
    """
    from app.models.models import Paper

    row = db.get(Paper, paper_id)
    if row is None:
        return None
    if row.readable_revision_id:
        return row.readable_revision_id
    from app.models.source import RevisionORM

    stmt = (
        select(RevisionORM.id)
        .where(RevisionORM.paper_id == paper_id)
        .order_by(RevisionORM.created_at.desc())
        .limit(1)
    )
    found = db.execute(stmt).first()
    return found[0] if found else None


__all__ = ["get_claims"]
