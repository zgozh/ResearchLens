"""M12 — 旧 HTTP 兼容适配（REFACTOR_SPEC §5.11、§5.10 M13）。

旧 ``compute_evaluation(db, paper_id)`` 返回 ``models.Evaluation``（ORM），
前端的 ``EvaluationOut.metrics`` 读 dict。本模块把 canonical
``EvaluationReport`` 投影回该 ORM 形状：

- ``metrics`` 仍是 dict：新增 ``overall_score_available`` 与
  ``not_evaluated`` 列表，让「未评估」**不冒充 0**；
- 旧 ``overall_score`` 字段（float 非空）在未评估时投影 **0 并显式标注**，
  因为旧契约不接受 null；canonical 值在 ``overall_score_canonical``。
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from app.contracts.common import Scope
from app.contracts.evaluation import EvaluationReport

from . import service as svc


def compute_evaluation(db: Session, paper_id: int) -> Any:
    """旧签名：计算并返回 ``models.Evaluation``（保持既有前端读取形状）。"""
    from app import models

    revision_id = _readable_revision(db, paper_id)
    if not revision_id:
        ev = _latest_row(db, paper_id)
        if ev is None:
            ev = models.Evaluation(
                paper_id=paper_id,
                metrics={"not_evaluated": ["*"], "note": "论文不存在或尚无可用 revision"},
                overall_score=0.0,
            )
            db.add(ev)
            db.commit()
            db.refresh(ev)
        return ev

    report = svc.compute(_input_for(Scope(paper_id=paper_id, revision_id=revision_id)))
    payload = to_legacy_evaluation(report)

    ev = _latest_row(db, paper_id)
    if ev is None:
        ev = models.Evaluation(paper_id=paper_id)
        db.add(ev)
    ev.metrics = payload["metrics"]
    ev.overall_score = payload["overall_score"]
    db.commit()
    db.refresh(ev)
    return ev


def to_legacy_evaluation(report: EvaluationReport) -> Dict[str, Any]:
    """``EvaluationReport → EvaluationOut`` 兼容 dict（含 not_evaluated 标记）。"""
    metrics: Dict[str, Any] = {}
    not_evaluated_names = []
    for entry in report.metrics:
        value = entry.value
        if value.status == "measured" and value.value is not None:
            metrics[entry.name] = value.value
        else:
            # 未评估：**不写 0**，写入 None 并登记名字
            metrics[entry.name] = None
            not_evaluated_names.append(entry.name)

    canonical = report.overall_score
    metrics["overall_score_available"] = canonical is not None
    metrics["not_evaluated"] = not_evaluated_names
    metrics["golden_id"] = report.golden_id
    metrics["version"] = report.version
    metrics["warnings"] = [{"code": w.code, "message": w.message} for w in report.warnings]

    # 旧契约 overall_score 非 null 的 float：未评估时投影 0 并已显式标注
    legacy_overall = float(canonical) if canonical is not None else 0.0
    metrics["overall_score_canonical"] = canonical
    return {"metrics": metrics, "overall_score": legacy_overall}


def _input_for(scope: Scope):
    """旧入口没有现成 EvaluationInput：从库中收集 statements/answers。"""
    from app.contracts.evaluation import EvaluationInput
    from app.core.db import session_scope

    statements = []
    answers = []
    try:
        from app.modules import claims as claims_svc

        statements = list(claims_svc.get_verified_statements(scope))
    except Exception:  # noqa: BLE001  证据层不可用时不阻断评测
        statements = []
    try:
        from app.modules.qa import repository as qa_repo
        from app.modules.qa import service as qa_service

        with session_scope() as db:
            rows = qa_repo.list_answers(db, scope.revision_id)
            for row in rows:
                record = qa_service._row_to_answer(row)
                if record is not None:
                    answers.append(record)
    except Exception:  # noqa: BLE001
        answers = []

    return EvaluationInput(
        scope=scope, statements=statements, answers=answers,
    )


def _latest_row(db: Session, paper_id: int):
    from app import models

    return (
        db.query(models.Evaluation)
        .filter(models.Evaluation.paper_id == paper_id)
        .order_by(models.Evaluation.id.desc())
        .first()
    )


def _readable_revision(db: Session, paper_id: int) -> Optional[str]:
    from app import models
    from app.models.source import RevisionORM
    from sqlalchemy import select

    paper = db.get(models.Paper, paper_id)
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


__all__ = ["compute_evaluation", "to_legacy_evaluation"]
