"""方法步骤的图表引用：精确匹配失败时用**同页/相邻页**兜底，并**标明来源**（ADR-0059）。

用户反馈："方法动画里有些步骤显示该步骤的断言尚未绑定图表 … 然后导致该步骤没有相关的引用。"

现状：`bind_media_for_statements` 只承认两类**可复核**关联（陈述里显式写"图 N"、
或与 caption 共享区分性 token）。两道关都过不了时**一条都不绑** → 前端如实显示
"该步骤的断言尚未绑定图表"，用户看到的就是"步骤没有引用"。

纪律：不能退回"全篇第一张图"（D-48 的教训：5 个步骤都指向同一张 `(a) 原图`）。
本模块锁住三条：

1. 兜底只在**精确方法都没结果**时启用；
2. 兜底判据是**位置**（同页或相邻页），且 `method="page_proximity"`、低分；
3. **来源必须一路传到前端**（``figure_ref_methods``），让 UI 显示"位置推断"，
   不能让位置推断冒充"题注匹配"。
"""
from __future__ import annotations

from types import SimpleNamespace

from app.contracts.common import Scope

SCOPE = Scope(paper_id=1, revision_id="rev-proximity")


def _media(mid: str, *, kind: str = "figure", no: int = 1, page: int | None = 3):
    return SimpleNamespace(
        id=mid, kind=kind, legacy_no=no, caption=f"{kind} {no}",
        anchor_ids=[f"a-{mid}"] if page is not None else [],
        original_asset_ids=[], original_label=None,
    )


class TestProximityFallback:
    def test_picks_same_page_media_when_no_exact_match(self):
        """无显式引用、无 caption 重合 → 取**同页**图表（不是全篇第一张）。"""
        from app.modules.evidence import service as es

        media = [_media("m-far", page=9), _media("m-near", page=4, no=2)]
        pick = es._proximity_media_for_statement(3, media, {"m-far": 8, "m-near": 3})
        assert pick is not None
        mid, method, score, reason = pick
        assert mid == "m-near", f"应取同页图表，实际 {mid}"
        assert method == "page_proximity"
        assert score < 1.0, "位置推断必须低分"
        assert "位置" in reason

    def test_returns_none_when_nothing_within_one_page(self):
        from app.modules.evidence import service as es

        media = [_media("m-far", page=20)]
        assert es._proximity_media_for_statement(None, media, {"m-far": 19}) is None
        assert es._proximity_media_for_statement(0, media, {"m-far": 19}) is None

    def test_media_without_page_is_skipped(self):
        from app.modules.evidence import service as es

        media = [_media("m-nopage", page=None)]
        assert es._proximity_media_for_statement(3, media, {}) is None

    def test_adjacent_page_is_allowed_but_ranked_below_same_page(self):
        from app.modules.evidence import service as es

        media = [_media("m-adj", page=5), _media("m-same", page=4)]
        pick = es._proximity_media_for_statement(3, media, {"m-adj": 4, "m-same": 3})
        assert pick is not None and pick[0] == "m-same"


class TestProjectionCarriesRefMethod:
    def test_position_refs_are_labelled_in_step_extras(self):
        """步骤的图表引用要带**来源方法**，前端据此标注"位置推断"。"""
        from app.modules.papers.legacy import method_step_extras

        step = SimpleNamespace(id="s1", label="步骤一", detail="", phase=None,
                               claim_ids=["c1"], media_ids=[], statement_id=None)
        statement_media = {"c1": [("m-fig", "figure", "page_proximity")]}
        out = method_step_extras(step, {"m-fig": 3}, statement_media=statement_media)
        assert out.get("figure_refs") == [3]
        assert out.get("figure_ref_methods", {}).get(3) == "page_proximity"

    def test_caption_refs_are_labelled_too(self):
        from app.modules.papers.legacy import method_step_extras

        step = SimpleNamespace(id="s1", label="步骤一", detail="", phase=None,
                               claim_ids=["c1"], media_ids=[], statement_id=None)
        statement_media = {"c1": [("m-fig", "figure", "caption_ref")]}
        out = method_step_extras(step, {"m-fig": 3}, statement_media=statement_media)
        assert out.get("figure_ref_methods", {}).get(3) == "caption_ref"

    def test_legacy_two_tuple_bindings_still_work(self):
        """旧的两元组（无 method）不能崩，视为精确匹配。"""
        from app.modules.papers.legacy import method_step_extras

        step = SimpleNamespace(id="s1", label="步骤一", detail="", phase=None,
                               claim_ids=["c1"], media_ids=[], statement_id=None)
        out = method_step_extras(step, {"m-fig": 3},
                                statement_media={"c1": [("m-fig", "figure")]})
        assert out.get("figure_refs") == [3]
        assert out.get("figure_ref_methods", {}).get(3) in ("", "explicit_block_ref", None)
