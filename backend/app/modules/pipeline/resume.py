"""M12 — 断点续跑：决定"从哪个阶段开始跑"（REFACTOR_PLAN_R3 §M12-4）。

## 为什么只做"决定"

先查再动的结论（D-94）：后端**已经有**阶段进度事件与幂等键表
（`job_stage_keys`，唯一键 `revision_id+stage+input_digest+algorithm_version`），
`service.py` 里也已经会在"产物 digest 命中"时返回 `skipped`。
真正缺的是**入口**：没有地方告诉管线"这次从哪个阶段开始"。

因此本模块只承担**决策**，并且刻意做成两层：

- `plan_resume(succeeded, from_stage)` —— **纯函数**，无 DB、无副作用，单测覆盖全部分支；
- `resolve_start_stage(scope, from_stage)` —— 薄薄一层 DB 读取（查该 revision 已成功的阶段），
  把结果交给纯函数。

业务规则（方案 §M12-4）：
- 传了 `from_stage` → 从它开始，**它之前的阶段一律 skipped**；
- 没传 → 从**第一个未成功**的阶段开始（"默认安全"：不会重复跑已完成的 AI 阶段、不重复计费）；
- 全部已完成 → `start_stage=None` + 明确原因（调用方据此决定是否还需要建 job）。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, List, Optional, Set

from app.contracts.jobs import STAGE_ORDER


@dataclass
class ResumePlan:
    """续跑计划：从哪个阶段开始、哪些可以跳过、为什么。"""

    #: 应该从哪个阶段开始跑；None = 没有要跑的阶段（全部已完成）
    start_stage: Optional[str]
    #: 在 start_stage 之前、已经成功因而可以跳过的阶段（顺序与 STAGE_ORDER 一致）
    skipped: List[str] = field(default_factory=list)
    reason: str = ""


def plan_resume(succeeded: Iterable[str], from_stage: Optional[str] = None) -> ResumePlan:
    """纯函数：按"已成功阶段集合 + 可选起点"算出续跑计划。

    - `from_stage` 非法（不在 STAGE_ORDER 里）→ 视同没传（**不猜**，走默认安全路径），
      并把原因写进 `reason` 以便调用方提示用户。
    """
    done: Set[str] = {s for s in (succeeded or []) if s in STAGE_ORDER}
    order = list(STAGE_ORDER)

    if from_stage and from_stage in order:
        idx = order.index(from_stage)
        return ResumePlan(
            start_stage=from_stage,
            skipped=[s for s in order[:idx] if s in done],
            reason=f"按指定起点从 {from_stage} 开始（之前的阶段跳过）",
        )
    note = ""
    if from_stage:
        note = f"未知起点 {from_stage!r} 已忽略；"

    for stage in order:
        if stage not in done:
            idx = order.index(stage)
            return ResumePlan(
                start_stage=stage,
                skipped=[s for s in order[:idx] if s in done],
                reason=f"{note}从第一个未完成阶段 {stage} 开始",
            )
    return ResumePlan(start_stage=None, skipped=list(order), reason=f"{note}全部阶段已完成，无需重跑")


def resolve_start_stage(scope, from_stage: Optional[str] = None) -> ResumePlan:
    """DB 层包装：查该 revision 已成功的阶段，交给 `plan_resume` 决策。

    "已成功"的判据是 `job_stage_keys` 里存在该阶段且状态为 succeeded
    （与 `service.py` 复用产物 digest 的判据同源）。
    """
    from sqlalchemy import select

    from app.core.db import session_scope
    from app.models.jobs import JobStageKeyORM

    with session_scope() as db:
        rows = db.execute(
            select(JobStageKeyORM.stage)
            .where(
                JobStageKeyORM.revision_id == scope.revision_id,
                JobStageKeyORM.status == "succeeded",
            )
            .distinct()
        ).all()
    succeeded = {r[0] for r in rows if r and r[0]}
    return plan_resume(succeeded, from_stage)


__all__ = ["ResumePlan", "plan_resume", "resolve_start_stage"]
