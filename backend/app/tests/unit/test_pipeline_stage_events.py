"""M12：阶段事件序列的契约（进度事件 + 幂等抑制）。

实测（job 7）：`stage_started acquire` 与 `stage_started claims` 各出现两次 ——
两处语义不同的 emit 共用了同一事件类型。本文件锁住：
1. **连续重复的 stage_started 被抑制**（同一次执行只留一条）；
2. 阶段跑完再重跑时，**新的 stage_started 必须保留**（不能把合法的重新开始也吞掉）；
3. progress 单调不减（方案 §M12 测试要点）。
"""
from __future__ import annotations

from sqlalchemy import select


def _job() -> int:
    """建一个**真实**的 paper+revision 再建 job（jobs.paper_id 有外键）。"""
    from uuid import uuid4

    from app.contracts.documents import PaperCreate, SourceMetadata
    from app.core.db import session_scope
    from app.models.jobs import JobORM
    from app.modules import papers as papers_mod

    paper = papers_mod.create_paper(
        PaperCreate(title=f"阶段事件测试-{uuid4().hex[:8]}", source_mode="upload",
                    provenance_class="source_document")
    )
    source = papers_mod.store_source(
        paper.id, b"%PDF-1.4\n%%EOF\n", SourceMetadata(original_filename="e.pdf")
    )
    revision = papers_mod.create_revision(paper.id, source.id, "source")
    with session_scope() as db:
        row = JobORM(paper_id=paper.id, revision_id=revision.id, kind="ingest",
                     spec={}, budget={}, model_snapshot={},
                     idempotency_key=f"k-evt-{uuid4().hex[:8]}")
        db.add(row)
        db.flush()
        return int(row.id)


def _types(job_id: int) -> list[str]:
    from app.core.db import session_scope
    from app.models.jobs import JobEventORM

    with session_scope() as db:
        rows = db.execute(
            select(JobEventORM).where(JobEventORM.job_id == job_id)
            .order_by(JobEventORM.event_id.asc())
        ).scalars().all()
        return [r.type for r in rows]


def _progress(job_id: int) -> list[float]:
    from app.core.db import session_scope
    from app.models.jobs import JobEventORM

    with session_scope() as db:
        rows = db.execute(
            select(JobEventORM).where(JobEventORM.job_id == job_id)
            .order_by(JobEventORM.event_id.asc())
        ).scalars().all()
        return [float((r.data or {}).get("progress") or 0.0) for r in rows]


class TestStageEventDedupe:
    def test_consecutive_duplicate_start_is_suppressed(self):
        from app.core.db import session_scope
        from app.modules.pipeline import service as svc

        job_id = _job()
        with session_scope() as db:
            svc._emit(db, job_id, "stage_started", stage="acquire", progress=0.0,
                      message="任务已入队")
            svc._emit(db, job_id, "stage_started", stage="acquire", progress=0.0,
                      message="worker=w1 已领取")
            svc._emit(db, job_id, "stage_finished", stage="acquire", progress=0.05,
                      message="acquire 完成")
        assert _types(job_id) == ["stage_started", "stage_finished"]

    def test_restart_after_finish_is_kept(self):
        """阶段跑完再重跑：新的 stage_started 必须保留（不能吞掉合法重启）。"""
        from app.core.db import session_scope
        from app.modules.pipeline import service as svc

        job_id = _job()
        with session_scope() as db:
            svc._emit(db, job_id, "stage_started", stage="claims", progress=0.5)
            svc._emit(db, job_id, "stage_finished", stage="claims", progress=0.7)
            svc._emit(db, job_id, "stage_started", stage="claims", progress=0.7,
                      message="重跑 claims")
        assert _types(job_id) == ["stage_started", "stage_finished", "stage_started"]

    def test_different_stage_start_is_kept(self):
        from app.core.db import session_scope
        from app.modules.pipeline import service as svc

        job_id = _job()
        with session_scope() as db:
            svc._emit(db, job_id, "stage_started", stage="parse", progress=0.05)
            svc._emit(db, job_id, "stage_started", stage="normalize", progress=0.25)
        assert _types(job_id) == ["stage_started", "stage_started"]

    def test_progress_is_monotonic(self):
        from app.core.db import session_scope
        from app.modules.pipeline import service as svc

        job_id = _job()
        seq = [("acquire", 0.0), ("parse", 0.05), ("parse", 0.25), ("normalize", 0.3)]
        with session_scope() as db:
            for stage, pct in seq:
                svc._emit(db, job_id, "stage_started", stage=stage, progress=pct)
        values = _progress(job_id)
        assert values == sorted(values), values
