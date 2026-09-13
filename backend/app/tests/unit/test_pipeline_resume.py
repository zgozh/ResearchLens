"""M12：断点续跑决策的纯函数测试（REFACTOR_PLAN_R3 §M12-4/测试要点 3）。

为什么先测纯函数：续跑逻辑一旦写错，用户看到的可能是"重跑一遍 = 白烧一次模型调用"
（AI 类阶段重复计费），或者"该跑的阶段被跳过 = 数据缺失"。这两种错误都不能靠肉眼发现。
"""
from __future__ import annotations

from app.contracts.jobs import STAGE_ORDER
from app.modules.pipeline.resume import plan_resume


class TestDefaultSafePath:
    def test_empty_history_starts_from_first_stage(self):
        plan = plan_resume(set())
        assert plan.start_stage == "acquire"
        assert plan.skipped == []

    def test_starts_from_first_unsucceeded(self):
        """模拟"worker 在 index 之后崩了"：重跑必须从 claims 起，前面四个跳过。"""
        done = {"acquire", "parse", "normalize", "media", "index"}
        plan = plan_resume(done)
        assert plan.start_stage == "claims", plan
        assert plan.skipped == ["acquire", "parse", "normalize", "media", "index"]

    def test_gap_in_middle_is_respected(self):
        """中间缺一个阶段（例如 verify 失败）→ 从那个阶段起，而不是从最后成功之后。"""
        done = {"acquire", "parse", "normalize", "media", "index", "claims"}
        plan = plan_resume(done)
        assert plan.start_stage == "verify"

    def test_all_done_means_nothing_to_run(self):
        plan = plan_resume(set(STAGE_ORDER))
        assert plan.start_stage is None
        assert plan.skipped == list(STAGE_ORDER)
        assert "全部阶段已完成" in plan.reason

    def test_unknown_stage_names_are_ignored(self):
        """历史里的脏数据（阶段名不在 STAGE_ORDER）不得影响决策。"""
        plan = plan_resume({"acquire", "totally-unknown"})
        assert plan.start_stage == "parse"
        assert plan.skipped == ["acquire"]
        assert "totally-unknown" not in plan.skipped


class TestExplicitFromStage:
    def test_explicit_start_wins_even_if_earlier_stages_succeeded(self):
        plan = plan_resume(set(STAGE_ORDER), from_stage="evaluate")
        assert plan.start_stage == "evaluate"
        assert plan.skipped == list(STAGE_ORDER)[: STAGE_ORDER.index("evaluate")]

    def test_explicit_start_marks_unsucceeded_earlier_stages_as_skipped_too(self):
        """显式指定 evaluate：即使 claims 没成功过，也不再跑它（用户说了从这儿起）。"""
        plan = plan_resume({"acquire", "parse"}, from_stage="evaluate")
        assert plan.start_stage == "evaluate"
        assert "claims" not in plan.skipped  # 它没成功过，不算"跳过"，只是不在本次范围内
        assert set(plan.skipped) == {"acquire", "parse"}

    def test_invalid_from_stage_falls_back_to_default_safe_path(self):
        plan = plan_resume({"acquire", "parse"}, from_stage="not-a-stage")
        assert plan.start_stage == "normalize"
        assert "已忽略" in plan.reason

    def test_from_stage_equals_first_stage(self):
        plan = plan_resume({"acquire"}, from_stage="acquire")
        assert plan.start_stage == "acquire"
        assert plan.skipped == []


class TestEnqueueStartStage:
    """接线的关键一环：起点必须落到 `job.stage`（那就是 runner 的"当前阶段"）。

    若这条断了，`/process?from_stage=evaluate` 会静默地从 acquire 重跑 ——
    白烧一遍 AI 阶段（claims 起草 / 题库作答 / evaluate 裁判）。
    """

    def _scope_and_spec(self):
        from uuid import uuid4

        from app.contracts.documents import PaperCreate, SourceMetadata
        from app.contracts.jobs import JobSpec
        from app.modules import papers as papers_mod

        paper = papers_mod.create_paper(
            PaperCreate(title=f"续跑接线-{uuid4().hex[:8]}", source_mode="upload",
                        provenance_class="source_document")
        )
        source = papers_mod.store_source(
            paper.id, b"%PDF-1.4\n%%EOF\n", SourceMetadata(original_filename="r.pdf")
        )
        revision = papers_mod.create_revision(paper.id, source.id, "source")
        spec = JobSpec(paper_id=paper.id, revision_id=revision.id, kind="ingest",
                       idempotency_key=f"k-{uuid4().hex[:8]}")
        return paper.id, revision.id, spec

    def test_start_stage_is_written_to_job(self):
        from app.core.db import session_scope
        from app.models.jobs import JobORM
        from app.modules.pipeline import service as svc

        paper_id, revision_id, spec = self._scope_and_spec()
        job = svc.enqueue(spec, None, start_stage="evaluate")
        with session_scope() as db:
            row = db.get(JobORM, job.id)
            assert row is not None
            assert row.stage == "evaluate", f"起点没落到 job.stage：{row.stage}"

    def test_default_start_stage_is_acquire(self):
        from app.core.db import session_scope
        from app.models.jobs import JobORM
        from app.modules.pipeline import service as svc

        paper_id, revision_id, spec = self._scope_and_spec()
        job = svc.enqueue(spec, None)
        with session_scope() as db:
            assert db.get(JobORM, job.id).stage == "acquire"
