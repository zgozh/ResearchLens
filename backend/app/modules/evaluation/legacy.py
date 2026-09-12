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
    """``EvaluationReport → EvaluationOut`` 兼容 dict（含 not_evaluated 标记）。

    **proxy 也要如实呈现**：规格允许报告 proxy（只是必须标明），而旧实现把
    非 ``measured`` 一律丢成 null → 前端看到"未评测"，实际上值算出来了
    （实测 ``unsupported_fact_escape_rate`` 就是这样被藏起来的）。
    这里额外给出 ``proxy`` 名单，前端据此标"（proxy）"而不是"未评测"。
    """
    metrics: Dict[str, Any] = {}
    not_evaluated_names = []
    proxy_names = []
    for entry in report.metrics:
        value = entry.value
        if value.value is None or value.status == "not_evaluated":
            # 未评估：**不写 0**，写入 None 并登记名字
            metrics[entry.name] = None
            not_evaluated_names.append(entry.name)
        elif value.status == "proxy":
            metrics[entry.name] = value.value
            proxy_names.append(entry.name)
        else:
            metrics[entry.name] = value.value

    canonical = report.overall_score
    metrics["overall_score_available"] = canonical is not None
    metrics["not_evaluated"] = not_evaluated_names
    metrics["proxy"] = proxy_names
    metrics["golden_id"] = report.golden_id
    metrics["version"] = report.version
    metrics["warnings"] = [{"code": w.code, "message": w.message} for w in report.warnings]

    # 旧契约 overall_score 非 null 的 float：未评估时投影 0 并已显式标注
    legacy_overall = float(canonical) if canonical is not None else 0.0
    metrics["overall_score_canonical"] = canonical
    return {"metrics": metrics, "overall_score": legacy_overall}


def _navigation_checks(scope: Scope):
    """由 **证据锚点页 vs 引用块所在页** 的确定性对照生成导航校验样本（ADR-0046）。

    为什么需要：``anchor_page_accuracy`` 需要 ``navigation_checks``，而 ``_input_for``
    此前根本不传它 → 该指标永远 ``not_evaluated``，进而 ``overall_score`` 永远是 None。

    **真值来源独立**：期望页取自**引用块所在的物理页**（parser 事实），
    实际页取自**证据记录的锚点**（导航会打开的那一页）。两者来自不同的表，
    所以这是一个真实的交叉校验，不是"自己跟自己比"。
    缺锚点或缺引用块的证据**不产生样本**（不猜、不补 0）。
    """
    from sqlalchemy import select

    from app.contracts.evaluation import NavigationCheck
    from app.core.db import session_scope
    from app.models.artifacts import AnchorORM, BlockORM, PageORM
    from app.modules.evidence import repository as ev_repo

    out = []
    try:
        with session_scope() as db:
            block_page = {
                row[0]: int(row[1] or 0)
                for row in db.execute(
                    select(BlockORM.id, PageORM.pdf_page_index)
                    .outerjoin(PageORM, PageORM.id == BlockORM.page_id)
                    .where(BlockORM.revision_id == scope.revision_id)
                ).all()
            }
            anchor_page = {}
            for row in db.execute(
                select(AnchorORM).where(AnchorORM.revision_id == scope.revision_id)
            ).scalars().all():
                segments = row.segments or []
                if segments and isinstance(segments[0], dict):
                    index = segments[0].get("pdf_page_index")
                    if index is not None:
                        anchor_page[row.id] = int(index)
            for row in ev_repo.list_evidence_rows(db, scope.revision_id):
                if not row.anchor_id or row.anchor_id not in anchor_page:
                    continue
                regions = list(row.source_region or [])
                if not regions or not isinstance(regions[0], dict):
                    continue
                block_ids = list(regions[0].get("block_ids") or [])
                expected = next((block_page[b] for b in block_ids if b in block_page), None)
                if expected is None:
                    continue
                actual = anchor_page[row.anchor_id]
                out.append(NavigationCheck(
                    anchor_id=row.anchor_id,
                    page_correct=(actual == expected),
                    region_iou=None,      # 块没有矩形就不给 IoU（宁缺勿造）
                    latency_ms=0,
                ))
    except Exception:  # noqa: BLE001  评测输入装配失败不得让评测 500
        return []
    return out


def _input_for(scope: Scope):
    """旧入口没有现成 EvaluationInput：从库中收集 statements/answers/golden 等。"""
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

    # Golden Set：没有它 precision / 拒答率就没有分母（ADR-0046）。
    # 用 ``find_for_scope`` 按 scope 校验，避免把别篇真值套上来。
    # Golden Set：没有它 precision / 拒答率就没有分母（ADR-0046）。
    # 用 ``find_for_scope_ex`` 同时取回**是否为调参集**——机器自动构造的集合
    # 不能当人工真值（规格 L613），交由评测层降级为 not_evaluated。
    golden = None
    golden_is_tuning = False
    try:
        from app.modules.evaluation import golden_builder

        with session_scope() as db:
            golden, golden_is_tuning = golden_builder.find_for_scope_ex(db, scope)
    except Exception:  # noqa: BLE001
        golden, golden_is_tuning = None, False

    # 媒体：``source_asset_coverage`` 的分母（此前不传 → 该指标永远 not_evaluated，
    # 而实际上 media 表里有真实数据）。
    media = []
    try:
        from app.modules import visual as visual_mod

        media = list(visual_mod.list_media(scope, limit=500).items)
    except Exception:  # noqa: BLE001
        media = []

    return EvaluationInput(
        scope=scope, statements=statements, answers=answers, media=media,
        golden=golden, golden_is_tuning=golden_is_tuning,
        navigation_checks=_navigation_checks(scope),
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
