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
