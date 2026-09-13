"""M12 — 旧 HTTP 兼容适配（REFACTOR_SPEC §5.11、§5.10 M13）。

旧 ``compute_evaluation(db, paper_id)`` 返回 ``models.Evaluation``（ORM），
前端的 ``EvaluationOut.metrics`` 读 dict。本模块把 canonical
``EvaluationReport`` 投影回该 ORM 形状：

- ``metrics`` 仍是 dict：给出 ``overall_score_available``、``not_evaluated`` 与
  ``proxy`` 名单，让「未评估」**不冒充 0**、让 proxy **标着标明地呈现**；
- ``overall_score`` 未评估时是 **null**（迁移 0008 把列放宽为可空之前只能填 0.0，
  实测 curl 顶层返回 ``"overall_score": 0.0`` 会被读成"评了 0 分"）；
  canonical 值另在 ``overall_score_canonical``。
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from app.contracts.common import Scope
from app.contracts.evaluation import AiJudgeResult, EvaluationReport

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
                metrics={"not_evaluated": ["*"], "note": "论文不存在或尚无可用 revision",
                         "overall_score_available": False, "proxy": []},
                overall_score=None,   # 没算过就是 null，不是 0（ADR-0055）
            )
            db.add(ev)
            db.commit()
            db.refresh(ev)
        return ev

    # AI 裁判结果缓存（ADR-0056）：摘要命中就直接复用，**不再调用模型**——
    # 这个入口每次 GET /evaluation 都会走到，不缓存的话每打开一次评测页就花一次云调用。
    previous = _latest_row(db, paper_id)
    cached_judge = _cached_ai_judge(previous)

    scope = Scope(paper_id=paper_id, revision_id=revision_id)
    inp = _input_for(scope, ai_judge=cached_judge)
    report = svc.compute(inp, _judge_ctx(scope))
    payload = to_legacy_evaluation(report)

    # 把本次的 AI 裁判结论按摘要存回 metrics，下一次打开评测页就不必再花云调用
    digest = svc.ai_judge_digest_for(inp)
    judged = _ai_judge_from_report(report, digest)
    if judged is not None:
        payload["metrics"]["ai_judge"] = judged.model_dump(mode="json")

    ev = _latest_row(db, paper_id)
    if ev is None:
        ev = models.Evaluation(paper_id=paper_id)
        db.add(ev)
    ev.metrics = payload["metrics"]
    ev.overall_score = payload["overall_score"]
    db.commit()
    db.refresh(ev)
    return ev


def _ai_judge_from_report(report: EvaluationReport, digest: Optional[str]):
    """从报告里回读 AI 裁判计数（用于缓存）；不是 AI 裁判口径时返回 ``None``。"""
    if not digest:
        return None
    precision = report.metric("support_precision")
    recall = report.metric("support_recall")
    if precision is None or precision.status != "proxy":
        return None
    if "ai_judge" not in (precision.method or ""):
        return None
    return AiJudgeResult(
        matches=[],   # 计数足够复现指标；具体配对不必回写
        true_positive=int(precision.numerator or 0),
        total_predicted=int(precision.denominator or 0),
        total_golden=int((recall.denominator if recall else 0) or 0),
        model="cached",
        digest=digest,
        judge_version="",
    )


def _judge_ctx(scope: Scope):
    """AI 裁判用的调用上下文（带论文快照与预算）；取不到就当没有裁判。"""
    try:
        from app.contracts.common import Budget, new_ctx
        from app.modules import papers as papers_mod

        snapshot = papers_mod.snapshot_for_revision(scope)
        if snapshot is None:
            return None
        return new_ctx(
            scope, snapshot=snapshot, deadline_ms=120_000,
            budget=Budget(max_calls=4, max_input_tokens=200_000,
                          max_output_tokens=8_000, max_wall_ms=120_000,
                          max_repair_rounds=1),
        )
    except Exception:  # noqa: BLE001  拿不到 ctx 就退化为"本次不判"
        return None


def _cached_ai_judge(row) -> Optional[AiJudgeResult]:
    """从上一行评测里取回 AI 裁判缓存（摘要校验交给评测层做）。"""
    if row is None:
        return None
    raw = (getattr(row, "metrics", None) or {}).get("ai_judge")
    if not isinstance(raw, dict):
        return None
    try:
        return AiJudgeResult.model_validate(raw)
    except Exception:  # noqa: BLE001  旧数据/形状不符一律当没有
        return None


def to_legacy_evaluation(report: EvaluationReport) -> Dict[str, Any]:
    """``EvaluationReport → EvaluationOut`` 兼容 dict。

    **M10 收敛**：这里原本是 `schemas/adapters.to_legacy_evaluation` 的一份**逐字段相同的副本**
    （实测两份输出的键集合与取值完全一致，既无超集也无差异）。两份并存只会重演
    D-48/D-60 那类"改了一处、另一处没改"的事故，因此改为**委托唯一实现**，
    本函数只负责把 Pydantic 结果摊平成旧调用方要的 dict。

    （历史上这两处确实分叉过：本模块漏了 `not_evaluated_reasons`、
    adapters 侧少了 `overall_score_canonical` —— 都是被双读一致性测试抓出来的。）
    """
    from app.schemas.adapters import to_legacy_evaluation as _project

    out = _project(report)
    data = out.model_dump() if hasattr(out, "model_dump") else dict(out)
    return data


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
    from app.modules.evaluation.region import (
        normalize_rect_from_block,
        region_iou_or_none,
    )

    out = []
    try:
        with session_scope() as db:
            block_page = {}
            block_rect = {}
            for row in db.execute(
                select(BlockORM.id, PageORM.pdf_page_index, BlockORM.raw_ref)
                .outerjoin(PageORM, PageORM.id == BlockORM.page_id)
                .where(BlockORM.revision_id == scope.revision_id)
            ).all():
                block_page[row[0]] = int(row[1] or 0)
                rect = normalize_rect_from_block(row[2])
                if rect is not None:
                    block_rect[row[0]] = rect
            anchor_page = {}
            anchor_rect = {}
            for row in db.execute(
                select(AnchorORM).where(AnchorORM.revision_id == scope.revision_id)
            ).scalars().all():
                segments = row.segments or []
                if segments and isinstance(segments[0], dict):
                    index = segments[0].get("pdf_page_index")
                    if index is not None:
                        anchor_page[row.id] = int(index)
                    rect = segments[0].get("rect")
                    if isinstance(rect, list) and len(rect) >= 4:
                        anchor_rect[row.id] = [float(v) for v in rect[:4]]
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
                # ---- 区域真值（R4-M6 / ADR D-107）----
                # `expected_rect` = 引用块矩形并集；`actual_rect` = 锚点 segment.rect。
                # **但两者的来源不独立**：证据锚点就是由这个引用块的 bbox 派生出来的
                # （`gate.block_rect` → `candidate_to_segment`），据此算 IoU 恒为 1.0。
                # 那是一张自证的满分，比"未评测"更糟 —— 所以这里显式传
                # `independent=False`，`region_iou` 保持 None，指标如实标
                # `no_independent_region_truth`。要让它可测，需要**第二个独立来源**
                # （例如同一 PDF 同时用 MinerU 与 PyMuPDF 解析再交叉比对区域）。
                expected_rects = [block_rect[b] for b in block_ids if b in block_rect]
                expected_rect = _union_rect(expected_rects)
                actual_rect = anchor_rect.get(row.anchor_id)
                out.append(NavigationCheck(
                    anchor_id=row.anchor_id,
                    page_correct=(actual == expected),
                    region_iou=region_iou_or_none(
                        expected=expected_rect, actual=actual_rect, independent=False,
                    ),
                    expected_rect=expected_rect,
                    actual_rect=actual_rect,
                    rect_units="unit_0_1" if (expected_rect or actual_rect) else "",
                    latency_ms=0,
                ))
    except Exception:  # noqa: BLE001  评测输入装配失败不得让评测 500
        return []
    return out


def _union_rect(rects: List[List[float]]) -> Optional[List[float]]:
    """矩形并集（用于"引用块矩形并集"）。空输入返回 ``None``（不造矩形）。"""
    if not rects:
        return None
    x0 = min(r[0] for r in rects)
    y0 = min(r[1] for r in rects)
    x1 = max(r[2] for r in rects)
    y1 = max(r[3] for r in rects)
    if not (x0 < x1 and y0 < y1):
        return None
    return [x0, y0, x1, y1]


def _input_for(scope: Scope, *, ai_judge: Optional[AiJudgeResult] = None):
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
            golden, _is_tuning = golden_builder.find_for_scope_ex(db, scope)
    except Exception:  # noqa: BLE001
        golden = None

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
        golden=golden,
        navigation_checks=_navigation_checks(scope),
        ai_judge=ai_judge,
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
