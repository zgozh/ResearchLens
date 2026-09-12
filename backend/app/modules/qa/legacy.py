"""M10 — 旧 HTTP 兼容适配（REFACTOR_SPEC §5.11）。

``api/routes.py`` 仍以 ``answer_question(db, paper_id, question, top_k)`` 调用本包，
返回 ``AskResponse``。本模块把旧 ``Session`` 用法翻译成 canonical ``answer()``，
再投影为 ``AskResponse``：

- **非流式与流式共用同一服务与同一 gate**；
- 旧 top_k 越界由服务层 clamp 并记 warning，不返回 422；
- 拒答也是 200，且 ``grounded=False``；**绝不按措辞判 grounded**。
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy.orm import Session

from app.contracts.common import CallContext, Scope
from app.contracts.qa import AnswerRecord, QARequest
from app.schemas.schemas import AskResponse

from . import repository as repo
from . import service as svc


def answer_question(
    db: Session,
    paper_id: int,
    question: str,
    top_k: int = 5,
) -> AskResponse:
    """旧签名：返回 ``AskResponse``；无证据时为带标记的拒答（仍 200）。"""
    resolved = _resolve_scope(db, paper_id)
    if resolved is None:
        # 论文不存在或没有 revision：明确拒答，不编造页码证据
        return AskResponse(
            answer="",
            grounded=False,
            confidence="Low",
            evidence=[],
            note="论文不存在或尚无可用 revision。",
        )

    scope, snapshot_id = resolved
    ctx = _legacy_ctx(scope, snapshot_id)
    record = svc.answer(
        scope,
        QARequest(question=(question or "").strip()[:2000], top_k=top_k),
        ctx,
    )
    return to_legacy_answer(record)


def to_legacy_answer(record: AnswerRecord) -> AskResponse:
    """``AnswerRecord → AskResponse``。

    **只保留一处实现**（ADR-0060）：这里改调 ``schemas/adapters.to_legacy_answer``。
    此前本模块自己写了一份，于是 ``schemas/adapters`` 修好的
    ``source_region[0].block_id`` → ``AttributeError``（带证据就 500）在这里**原样留着**，
    而且漏了 ``mode`` 字段（前端因此无法区分"通用回答"与"拒答"）。
    两处投影必须同口径——有测试锁住它们逐字段相等。
    """
    from app.schemas.adapters import to_legacy_answer as _project

    return _project(record)


def _resolve_scope(db: Session, paper_id: int):
    found = repo.paper_revision(db, paper_id)
    if found is None:
        return None
    revision_id, snapshot_id = found
    return Scope(paper_id=paper_id, revision_id=revision_id), snapshot_id


def _legacy_ctx(scope: Scope, snapshot_id: Optional[str]) -> Optional[CallContext]:
    """旧入口也必须给出**带模型快照**的 CallContext（ADR-0060）。

    此前直接 ``return None``，后果有两层（都已实测）：
    1. ``_draft`` 看到 ``snapshot_id is None`` → 走 ``llm_unavailable`` 抽取降级，
       旧接口**从不调用生成模型**；
    2. ``_general_answer`` 要求 ``_snapshot_id(ctx)`` → 直接返回 None，
       于是"与论文无关的问题走通用回答"（D-57）在旧接口上**永远不触发**
       （线上实测：问"什么是量子纠缠"仍被拒答）。

    取快照失败时返回 None（退化为旧行为），不让问答整体 500。
    """
    try:
        from app.contracts.common import Budget, new_ctx
        from app.modules import papers as papers_mod

        snapshot = papers_mod.snapshot_for_revision(scope)
        if snapshot is None:
            return None
        budget = Budget(
            max_calls=24, max_input_tokens=200_000, max_output_tokens=40_000,
            # 120s：与流式问答一致（ADR-0063）。此前 300s —— 实测"主要贡献是什么"
            # 会跑满 300s 让前端超时；现在到点就降级为抽取式作答/明确拒答。
            max_wall_ms=120_000, max_repair_rounds=2,
        )
        ctx = new_ctx(scope, snapshot=snapshot, deadline_ms=120_000, budget=budget)
        if snapshot_id and getattr(ctx, "model_snapshot", None) is None:
            return None
        return ctx
    except Exception:  # noqa: BLE001  拿不到上下文就退化为旧行为
        return None


__all__ = ["answer_question", "to_legacy_answer"]
