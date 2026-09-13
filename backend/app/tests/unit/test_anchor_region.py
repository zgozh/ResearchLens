"""R4-M6 — `anchor_region_hit_rate` 实证定案（ADR D-107）。

## 实测覆盖率（真实库，2026-09-13）

块 bbox **100% 覆盖**（七篇论文全部命中，单位全是 MinerU 的 `normalized` 0–1000）：

| paper | blocks | with_bbox | units |
|---|---|---|---|
| 1 | 156 | 156 | normalized |
| 2 | 267 | 267 | normalized |
| 3 | 400 | 400 | normalized |
| 7 | 180 | 180 | normalized |
| 9/10 | 122 | 122 | normalized |
| 11 | 258 | 258 | normalized |

锚点 `segments[0].rect` 非空率 **0/N**（1:0/258、2:0/100、3:0/144、7:0/15、9/10:0/9、11:0/16）。
原因不是"原文没有坐标"，而是 **`CandidateEvidence` 的两个构造点都硬写 `rect=None`**
（`gate.py` 引用定位与 `page_only_candidate`）——**生产链缺一环**。

## 结论（本文件锁住）

1. **补上生产链**：块 bbox 可用时，候选与锚点带真实 rect（让阅读器能画区域高亮）；
2. **但不许据此算 IoU**：锚点 rect 与"期望区域"是**同一个块的同一个矩形**，
   算出来恒为 1.0 —— 那是**自证指标**，比"未评测"更糟（等于编造一个满分）；
3. 因此 `anchor_region_hit_rate` 仍为 `not_evaluated`，但**原因码必须更正**：
   原文不是"PDF 没有坐标矩形"（那是假的），而是"缺少独立区域真值来源"。
"""
from __future__ import annotations

import os
from types import SimpleNamespace

import pytest

os.environ["LLM_API_KEY"] = ""
os.environ["LLM_BASE_URL"] = ""
os.environ["LLM_FALLBACKS"] = ""


# ------------------------------------------------------------------ 1


class TestRectProductionChain:
    """块 bbox → 候选 rect → 锚点 segment.rect（把缺的那一环补上）。"""

    def test_block_bbox_becomes_segment_rect(self):
        """有 bbox 的块 → `candidate_to_segment` 产出带 rect 的 region 锚点。

        旧行为：候选 rect 恒为 None → 锚点永远是 page-only → 阅读器**永远画不出区域**。
        """
        from app.modules.evidence.gate import CandidateEvidence, candidate_to_segment

        cand = CandidateEvidence(
            block_id="b1", quote_span=None, locator_status="exact", match_kind="exact",
            page_id="p1", pdf_page_index=0, page_label="1",
            source_text="证据原文", anchor_id="a1",
            rect=[0.1, 0.2, 0.3, 0.24],
            quads=[],
        )
        seg = candidate_to_segment(cand)
        assert seg.rect == [0.1, 0.2, 0.3, 0.24], "region 候选必须把矩形带到锚点"

    def test_page_only_still_has_no_rect(self):
        """契约硬约束不变：page-only 必须 `rect=None / quads=[]`。"""
        from app.modules.evidence import locator
        from app.modules.evidence.gate import candidate_to_segment, page_only_candidate

        page_ref = locator.PageRef(block_id="b1", page_id="p1", pdf_page_index=0,
                                   page_label="1")
        seg = candidate_to_segment(page_only_candidate(page_ref, anchor_id="a1"))
        assert seg.rect is None
        assert seg.quads == []

    def test_bbox_extraction_refuses_unknown_units(self):
        """单位未知 / 缺失 / 退化 / 越界 → **不给矩形**（宁缺勿造）。"""
        from app.modules.evidence.gate import block_rect

        def blk(values, units, present=True):
            if not present:
                return SimpleNamespace(raw_ref=None)
            return SimpleNamespace(raw_ref=SimpleNamespace(
                bbox_values=values, bbox_units=units))

        assert block_rect(blk(None, None, present=False)) is None
        assert block_rect(blk([1, 2, 3, 4], "unknown")) is None
        assert block_rect(blk([1, 2], "normalized")) is None, "少于 4 个数不算矩形"
        assert block_rect(blk([5, 5, 5, 9], "normalized")) is None, "零宽不算矩形"
        # 越界（说明单位理解错了）→ 不裁剪、不猜
        assert block_rect(blk([0, 0, 2000, 2000], "normalized")) is None

    def test_normalized_units_are_rescaled_to_0_1(self):
        """**单位对齐**：MinerU 的 0–1000 必须换算成契约要求的 0..1。"""
        from app.modules.evidence.gate import block_rect

        # 实测被契约当场拦下过：不换算会抛"rect 必须归一化到 0..1"
        block = SimpleNamespace(raw_ref=SimpleNamespace(
            bbox_values=[100.0, 200.0, 300.0, 240.0], bbox_units="normalized"))
        assert block_rect(block) == [0.1, 0.2, 0.3, 0.24]

    def test_point_units_refused_without_page_size(self):
        """point 单位缺页尺寸 → 不给（gate 层拿不到页宽高，拍脑袋换算必错）。"""
        from app.modules.evidence.gate import block_rect

        block = SimpleNamespace(raw_ref=SimpleNamespace(
            bbox_values=[10.0, 20.0, 30.0, 40.0], bbox_units="point"))
        assert block_rect(block) is None


# ------------------------------------------------------------------ 2


class TestNoSelfConfirmingIou:
    """**纪律**：不许用同一个块的同一个矩形算 IoU（那恒为 1.0）。"""

    def test_same_source_rects_produce_no_iou(self):
        from app.modules.evaluation.region import region_iou_or_none

        rect = [0.1, 0.2, 0.3, 0.24]
        # expected 与 actual 是**同一个矩形**（同一来源）→ 拒绝产出 IoU
        assert region_iou_or_none(expected=rect, actual=rect, independent=False) is None
        # 明确声明来源独立时才计算
        assert region_iou_or_none(expected=rect, actual=rect, independent=True) == 1.0

    def test_real_iou_is_computed_when_independent(self):
        from app.modules.evaluation.region import region_iou_or_none

        a = [0.0, 0.0, 0.1, 0.1]
        b = [0.05, 0.0, 0.15, 0.1]        # 交 0.05×0.1，并 0.15×0.1 → 1/3
        iou = region_iou_or_none(expected=a, actual=b, independent=True)
        assert iou is not None and abs(iou - (5000 / 15000)) < 1e-6

    def test_no_intersection_is_zero_not_none(self):
        from app.modules.evaluation.region import region_iou_or_none

        a = [0.0, 0.0, 10.0, 10.0]
        b = [100.0, 100.0, 110.0, 110.0]
        assert region_iou_or_none(expected=a, actual=b, independent=True) == 0.0

    def test_missing_rect_returns_none(self):
        from app.modules.evaluation.region import region_iou_or_none

        assert region_iou_or_none(expected=None, actual=[0.1, 0.2, 0.3, 0.4], independent=True) is None
        assert region_iou_or_none(expected=[0.1, 0.2, 0.3, 0.4], actual=None, independent=True) is None

    def test_unit_alignment_normalizes_point_to_1000_grid(self):
        """单位对齐：point → normalized(0–1000) 需要页尺寸；缺页尺寸就**不算**。"""
        from app.modules.evaluation.region import normalize_rect

        # 页 612×792 pt；矩形左上 (61.2, 79.2) → (600, 800)/1000
        out = normalize_rect([61.2, 79.2, 306.0, 396.0], "point", page_size=(612.0, 792.0))
        assert out is not None
        assert abs(out[0] - 0.1) < 1e-9 and abs(out[1] - 0.1) < 1e-9
        assert abs(out[2] - 0.5) < 1e-9 and abs(out[3] - 0.5) < 1e-9
        # MinerU 的 0–1000 网格 → 契约 0..1
        assert normalize_rect([100.0, 200.0, 300.0, 240.0], "normalized", page_size=None) == [0.1, 0.2, 0.3, 0.24]
        # 契约空间原样通过
        assert normalize_rect([0.1, 0.2, 0.3, 0.4], "unit_0_1", page_size=None) == [0.1, 0.2, 0.3, 0.4]
        # 缺页尺寸的 point → 不算（不许拍脑袋换算）
        assert normalize_rect([1, 2, 3, 4], "point", page_size=None) is None
        # 未知单位 → 不算
        assert normalize_rect([1, 2, 3, 4], "unknown", page_size=(1.0, 1.0)) is None

    def test_cross_unit_iou_requires_alignment(self):
        """一个 point、一个 normalized：必须**先对齐**再算，否则直接相减必错。"""
        from app.modules.evaluation.region import region_iou_or_none

        # 未对齐（把 point 当 normalized 直接比）会得出一个"看起来正常"的错误值；
        # 本函数要求调用方先对齐，未对齐时以 independent=False 拒绝。
        pt = [61.2, 79.2, 306.0, 396.0]
        norm = [0.1, 0.1, 0.5, 0.5]
        assert region_iou_or_none(expected=norm, actual=pt, independent=True) != 1.0, (
            "跨单位直接相减必然得到错误值 —— 这正是必须在对齐层做换算的原因"
        )


# ------------------------------------------------------------------ 3


class TestAssemblyRefusesSelfConfirmingIou:
    """装配点（`evaluation.legacy._navigation_checks`）必须显式声明来源不独立。"""

    def test_union_rect_is_real_union_or_none(self):
        from app.modules.evaluation.legacy import _union_rect

        assert _union_rect([]) is None, "空输入不造矩形"
        assert _union_rect([[0.1, 0.1, 0.2, 0.2]]) == [0.1, 0.1, 0.2, 0.2]
        u = _union_rect([[0.1, 0.1, 0.2, 0.2], [0.3, 0.0, 0.4, 0.5]])
        assert u == [0.1, 0.0, 0.4, 0.5], u
        assert _union_rect([[0.2, 0.2, 0.2, 0.3]]) is None, "退化矩形不算"

    def test_assembly_declares_not_independent(self):
        import pathlib

        src = (pathlib.Path(__file__).resolve().parents[2]
               / "modules/evaluation/legacy.py")
        text = src.read_text(encoding="utf-8")
        assert "independent=False" in text, (
            "证据锚点与期望区域同源（都由引用块 bbox 派生），装配点必须声明不独立，"
            "否则会算出恒为 1.0 的自证 IoU"
        )
        assert "expected_rect" in text and "actual_rect" in text, (
            "两个矩形要留存，排查时才能区分'没有矩形'与'两个矩形同源'"
        )

    def test_block_dict_and_object_conversion_agree(self):
        """对象形态与 dict 形态的换算必须一致（否则区域指标一边一个单位）。"""
        from app.modules.evidence.gate import block_rect
        from app.modules.evaluation.region import normalize_rect_from_block

        values = [100.0, 200.0, 300.0, 240.0]
        obj = SimpleNamespace(raw_ref=SimpleNamespace(
            bbox_values=values, bbox_units="normalized"))
        dct = {"bbox_values": values, "bbox_units": "normalized"}
        assert block_rect(obj) == normalize_rect_from_block(dct) == [0.1, 0.2, 0.3, 0.24]
        assert normalize_rect_from_block(None) is None
        assert normalize_rect_from_block("not-a-dict") is None


class TestReasonCodeIsCorrected:
    """原因码更正：不许再说"原文 PDF 未提供坐标矩形"（实测 100% 覆盖，那是假话）。"""

    def test_new_reason_code_exists(self):
        from app.modules.evaluation import metrics as M

        entry = M.anchor_region_hit_rate([])
        assert entry.value.status == "not_evaluated"
        assert entry.value.reason == "no_independent_region_truth", entry.value.reason

    def test_old_wrong_reason_is_not_produced(self):
        from app.modules.evaluation import metrics as M

        entry = M.anchor_region_hit_rate([])
        assert entry.value.reason != "source_pdf_has_no_coordinate_rects", (
            "该码声称'PDF 没有坐标矩形'，但实测块 bbox 覆盖率 100% —— 是假原因"
        )

    def test_frontend_reason_text_is_updated(self):
        import pathlib

        root = pathlib.Path(__file__).resolve().parents[4] / "frontend"
        text = (root / "lib/evalMetrics.ts").read_text(encoding="utf-8")
        assert "no_independent_region_truth" in text, "前端原因码表要同步"
        assert "拒绝编造 IoU" not in text or "独立" in text, (
            "旧的'原文无坐标矩形/拒绝编造 IoU'文案是错误归因，必须更正"
        )
