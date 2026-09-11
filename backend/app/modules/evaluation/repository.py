"""M12 — evaluation 私有持久化访问（REFACTOR_SPEC §6.14）。

只做表 ↔ DTO 投影与读写。**GET 不计算、不写库**：读取走只读查询。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.audit import EvaluationReportORM


@dataclass(frozen=True)
class ReportRow:
    """评测报告的**冻结快照**（离开 Session 后仍可读）。

    为什么需要它：ORM 实例在 ``session_scope()`` 关闭后属性会过期，
    上层再读 ``row.metrics`` 会触发 ``DetachedInstanceError``。
    """

    id: str
    version: str
    overall_score: Optional[float]
    metrics: List[Any] = field(default_factory=list)
    golden_id: Optional[str] = None
    computed_at: Optional[Any] = None
    warnings: List[Any] = field(default_factory=list)


def _snapshot(row: EvaluationReportORM) -> ReportRow:
    return ReportRow(
        id=row.id,
        version=row.version or "rl.eval/1",
        overall_score=row.overall_score,      # None 就是 None，绝不写成 0
        metrics=list(row.metrics or []),
        golden_id=row.golden_id,
        computed_at=row.computed_at,
        warnings=list(row.warnings or []),
    )


def latest_report(db: Session, revision_id: str) -> Optional[ReportRow]:
    stmt = (
        select(EvaluationReportORM)
        .where(EvaluationReportORM.revision_id == revision_id)
        .order_by(EvaluationReportORM.computed_at.desc())
        .limit(1)
    )
    row = db.execute(stmt).scalars().first()
    return _snapshot(row) if row is not None else None


def list_reports(db: Session, revision_id: str) -> List[ReportRow]:
    stmt = (
        select(EvaluationReportORM)
        .where(EvaluationReportORM.revision_id == revision_id)
        .order_by(EvaluationReportORM.computed_at)
    )
    return [_snapshot(row) for row in db.execute(stmt).scalars().all()]


def insert_report(
    db: Session,
    *,
    report_id: str,
    paper_id: int,
    revision_id: str,
    version: str,
    overall_score: Optional[float],
    metrics: list,
    golden_id: Optional[str],
    warnings: list,
) -> None:
    from app.models.source import now as _now

    db.add(EvaluationReportORM(
        id=report_id,
        paper_id=paper_id,
        revision_id=revision_id,
        version=version,
        overall_score=overall_score,
        metrics=metrics,
        golden_id=golden_id,
        warnings=warnings,
        computed_at=_now(),
    ))
    db.flush()


def paper_revision(db: Session, paper_id: int) -> Optional[str]:
    """旧 HTTP 入口用：解析该论文的可读 revision。"""
    from app.models.models import Paper
    from app.models.source import RevisionORM

    paper = db.get(Paper, paper_id)
    if paper is None:
        return None
    if paper.readable_revision_id:
        return paper.readable_revision_id
    stmt = (
        select(RevisionORM.id)
        .where(RevisionORM.paper_id == paper_id)
        .order_by(RevisionORM.created_at.desc())
        .limit(1)
    )
    found = db.execute(stmt).first()
    return found[0] if found else None


__all__ = [
    "ReportRow",
    "latest_report",
    "list_reports",
    "insert_report",
    "paper_revision",
]
