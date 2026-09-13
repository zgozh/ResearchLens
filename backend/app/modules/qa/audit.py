"""M7 — 流式问答审计（REFACTOR_PLAN_R3）。

## 为什么需要

用户实测："三条默认问题都显示『本次回答被中断』"。我用同样的 POST 复现时服务端
**每次都发了 final** —— 说明"被中断"是客户端侧的现象，但**线上没有任何对账数据**：
到底服务端发了什么、终结事件有没有出去、客户端有没有断开，事后完全查不到。

本模块把每次流式回答的生命周期落一行审计：事件类型序列（**不存正文**，控体积）、
终结事件类型、错误码、异常类型、耗时。审计写入**尽力而为**：失败只记日志，
绝不改变流的行为（审计不能成为新的故障点）。

`terminal='none'` 是**最有价值**的一行 —— 它代表"服务端没发出任何终结事件"，
正是"前端被中断"的对账数据源。
"""
from __future__ import annotations

import logging
import time
from typing import List, Optional

log = logging.getLogger("researchlens.qa.audit")


def record(
    *,
    paper_id: int,
    revision_id: Optional[str],
    answer_id: Optional[str],
    mode: str = "",
    events: Optional[List[str]] = None,
    terminal: str = "none",
    error_code: Optional[str] = None,
    exception_type: Optional[str] = None,
    elapsed_ms: Optional[int] = None,
) -> None:
    """写一条审计。**任何异常都只记日志**（不得影响流）。"""
    try:
        from app.core.db import session_scope
        from app.models.audit import QaStreamAuditORM
        from app.models.source import new_id

        with session_scope() as db:
            db.add(QaStreamAuditORM(
                id=new_id(),
                paper_id=paper_id,
                revision_id=revision_id,
                answer_id=answer_id,
                mode=(mode or "")[:32] or None,
                events=list(events or []),
                terminal=(terminal or "none")[:16],
                error_code=(error_code or None),
                exception_type=(exception_type or None),
                elapsed_ms=elapsed_ms,
            ))
    except Exception as exc:  # noqa: BLE001  审计是尽力而为，绝不阻断回答
        log.warning("qa 流式审计写入失败（忽略，不影响回答）：%s", exc)


def list_audits(paper_id: int, *, limit: int = 50) -> List[dict]:
    """按创建时间倒序查询某个 paper 的审计（limit ≤ 200）。"""
    from sqlalchemy import select

    from app.core.db import session_scope
    from app.models.audit import QaStreamAuditORM

    capped = max(1, min(int(limit or 50), 200))
    with session_scope() as db:
        rows = db.execute(
            select(QaStreamAuditORM)
            .where(QaStreamAuditORM.paper_id == paper_id)
            .order_by(QaStreamAuditORM.created_at.desc())
            .limit(capped)
        ).scalars().all()
        return [
            {
                "id": r.id,
                "paper_id": r.paper_id,
                "revision_id": r.revision_id,
                "answer_id": r.answer_id,
                "mode": r.mode,
                "events": list(r.events or []),
                "terminal": r.terminal,
                "error_code": r.error_code,
                "exception_type": r.exception_type,
                "elapsed_ms": r.elapsed_ms,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ]


class AuditTimer:
    """极小的计时器：给流式回答记 elapsed_ms。"""

    def __init__(self) -> None:
        self._t0 = time.time()

    @property
    def elapsed_ms(self) -> int:
        return int((time.time() - self._t0) * 1000)


__all__ = ["record", "list_audits", "AuditTimer"]
