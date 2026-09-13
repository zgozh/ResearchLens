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
    """写入**或刷新**该 (revision, golden) 的评测报告 —— 同 id 覆盖（upsert）。

    ## 为什么必须是 upsert（实测事故，2026-09-13）

    `report_id = service._report_id(revision_id, golden_id)` 对同一 (revision, golden)
    **是确定性的**：同一个字符串。旧实现是纯 ``db.add(...)``，于是

    1. 第一次写成功；
    2. 之后**每次** ``svc.compute()`` → ``_persist()`` 都在主键上冲突；
    3. 而 ``_persist`` 里是 ``except Exception: pass`` → **静默吞掉**。

    结果：canonical 报告永远停在第一次（实测停在 ``rl.eval/1``、2026-09-12T07:41），
    而 ``/evaluation`` 每次 GET 都重算并更新 legacy ``evaluations`` 行 ——
    两个数据源长期不一致，界面按"canonical 有值即权威"显示**过期的 0**。

    回归锁：`tests/unit/test_evaluation_report_refresh.py`。
    """
    from app.models.source import now as _now

    ts = _now()
    row = db.get(EvaluationReportORM, report_id)
    if row is None:
        db.add(EvaluationReportORM(
            id=report_id,
            paper_id=paper_id,
            revision_id=revision_id,
            version=version,
            overall_score=overall_score,
            metrics=metrics,
            golden_id=golden_id,
            warnings=warnings,
            computed_at=ts,
        ))
    else:
        row.paper_id = paper_id
        row.revision_id = revision_id
        row.version = version
        row.overall_score = overall_score
        row.metrics = metrics
        row.golden_id = golden_id
        row.warnings = warnings
        row.computed_at = ts
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
