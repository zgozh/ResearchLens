"""方法步骤的图表引用必须**按步骤自己的证据**取，而不是全篇第一张图（ADR-0048）。

真实缺陷（用户实测）：paper 1 的 5 个步骤点开后**都引用同一张图**，而且那张图是
``(a) 原图`` 这种无意义的子图面板。根因：

- 确定性步骤（``_steps_from_sections``）构造 ``MethodStepRecord`` 时**没有 media_ids**；
- 于是 ``method_step_extras`` 解析不出 ``figure_ref``；
- 前端 ``MethodView`` 落回"方法原图"兜底 —— 而兜底取的是 ``detail.figures[0]``，
  对所有步骤都是同一张。

正确做法：步骤 → 其断言 → 该陈述的 ``statement→media`` 绑定 → 得出**该步骤自己的**
图/表编号（可能有多个）。绑定由 ``bind_media_for_statements`` 依 caption↔陈述的词面
重合建立，所以相关性与"是不是这张图的题注在讲这件事"直接对应。
"""
from __future__ import annotations

import os
from types import SimpleNamespace

os.environ.setdefault("LLM_API_KEY", "")


def _step(*, label="本文用 Haar 小波域指标选择载体。", media_ids=(), statement_id="stmt-1"):
    return SimpleNamespace(
        id="step-1", label=SimpleNamespace(text=label, spans=[]),
        detail=SimpleNamespace(text="", spans=[]), phase=None,
        claim_ids=["c1"], media_ids=list(media_ids), statement_id=statement_id,
    )


class TestMethodStepMediaRefs:
    def test_figures_come_from_the_steps_own_statement_bindings(self):
        from app.modules.papers.legacy import method_step_extras

        statement_media = {
            "stmt-1": [("m-fig", "figure"), ("m-table", "table")],
        }
        out = method_step_extras(
            _step(), {"m-fig": 3, "m-table": 7}, statement_media=statement_media,
        )

        assert out["figure_refs"] == [3], f"该步骤自己的图：{out}"
        assert out["table_refs"] == [7], f"该步骤自己的表：{out}"
        assert out["figure_ref"] == 3, "兼容字段保留第一个图"

    def test_does_not_fall_back_to_a_global_figure(self):
        """没有绑定就不给编号——**绝不**回退到"全篇第一张图"。"""
        from app.modules.papers.legacy import method_step_extras

        out = method_step_extras(_step(), {"m-fig": 3}, statement_media={})

        assert "figure_ref" not in out, f"不得编造/回退图表引用：{out}"
        assert out.get("figure_refs", []) == []

    def test_step_media_ids_are_used_when_bindings_are_absent(self):
        """绑定缺失时可用步骤自带的 media_ids（仍是该步骤自己的来源）。"""
        from app.modules.papers.legacy import method_step_extras

        out = method_step_extras(
            _step(media_ids=["m-x"]), {"m-x": 5}, statement_media={},
        )

        assert out["figure_refs"] == [5]

    def test_lookup_works_by_claim_id_too(self):
        """方法步骤只带 ``claim_ids``（没有 statement_id）→ 必须能按 claim_id 查到绑定。"""
        from app.modules.papers.legacy import method_step_extras

        out = method_step_extras(
            _step(statement_id=None), {"m-fig": 4},
            statement_media={"c1": [("m-fig", "figure")]},
        )

        assert out["figure_refs"] == [4], f"按 claim_id 也要能查到：{out}"

    def test_unknown_kind_is_ignored(self):
        from app.modules.papers.legacy import method_step_extras

        out = method_step_extras(
            _step(), {"m-eq": 9}, statement_media={"stmt-1": [("m-eq", "equation")]},
        )

        assert out.get("figure_refs", []) == []
        assert out.get("table_refs", []) == []
