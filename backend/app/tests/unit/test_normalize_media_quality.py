"""M02 媒体候选质量：caption 归属切分 + 装饰性空图过滤（ADR-0018）。

真实缺陷（3 篇真实论文实测，D 项）：

1. **相邻对象的 caption 被粘成一条**：MinerU 的 ``image_caption``/``table_caption``
   是数组，``mineru_adapter._as_text()`` 用 ``" ".join`` 整串拼接。实测
   ``图 9 预测 8 种特定类型缺陷的 F1-score 值对比箱线图 图 10 缺陷数量预测模型性能比较箱线图``
   把两幅图的 caption 连成一条；paper 1 更粘了 3 个对象标记。
2. **装饰性空图混入**：paper 1/2/3 共 16 行 caption 为空，其中 15 行渲染确认是
   二维码/作者证件照，面积只占页面 0.60%–0.68%；而**真图**面积为 4.8%+，
   带 caption 的子图面板为 0.82%–0.85%。

过滤判据必须是**交集**（caption 为空 **且** 面积过小）：只按"caption 空"会误删
paper 3 里丢了 caption 的真图（``677e3596…``，面积 4.8%）；只按"面积小"会误删
paper 1 图 1 的 6 个并排面板（0.82%–0.85%，都有 caption）。
"""
from __future__ import annotations

import os

import pytest

os.environ.setdefault("LLM_API_KEY", "")

from app.contracts.common import Scope  # noqa: E402
from app.contracts.documents import PaperCreate, SourceMetadata  # noqa: E402


def _uniq(prefix: str) -> str:
    import uuid

    return f"{prefix}-{uuid.uuid4().hex[:12]}"


@pytest.fixture
def world():
    from app.modules import papers as papers_mod

    paper = papers_mod.create_paper(
        PaperCreate(title="媒体候选质量", source_mode="upload",
                    provenance_class="source_document")
    )
    source = papers_mod.store_source(
        paper.id, b"%PDF-1.4\n", SourceMetadata(original_filename="m.pdf")
    )
    revision = papers_mod.create_revision(paper.id, source.id, "source")
    return {"paper": paper, "scope": Scope(paper_id=paper.id, revision_id=revision.id)}


def _page(scope, *, width=595.23, height=841.89, text=""):
    from app.contracts.documents import Page

    return Page(
        scope=scope, id=_uniq("pg"), pdf_page_index=0, pdf_page_no=1,
        width_pt=width, height_pt=height, text=text,
    )


def _raw_document(blocks, *, page_text=""):
    from app.modules.parse.pymupdf_adapter import RawDocument, RawPage

    return RawDocument(
        pages=[RawPage(pdf_page_index=0, width_pt=595.23, height_pt=841.89,
                       text=page_text, blocks=list(blocks))],
        page_count=1,
    )


def _image_block(text, bbox=None, *, kind="image", units="normalized", ordinal=0):
    from app.modules.parse.pymupdf_adapter import RawBlock

    return RawBlock(kind=kind, text=text, bbox=bbox, bbox_units=units, ordinal=ordinal)


def _candidates(scope, blocks, *, page_text=""):
    from app.modules.parse import normalize

    return normalize.build_media_candidates(
        scope, _raw_document(blocks, page_text=page_text),
        pages=[_page(scope, text=page_text)], blocks=[], page_index_by_id={},
        raw_asset_id="asset-1",
    )


class TestCaptionOwnership:
    def test_concatenated_captions_are_cut_to_first_object(self, world):
        """两幅图的 caption 粘连时必须只保留本对象那一段。"""
        scope = world["scope"]
        glued = ("图 9 预测 8 种特定类型缺陷的 F1-score 值对比箱线图 "
                 "图 10 缺陷数量预测模型性能比较箱线图 (MAE)")
        (cand,) = _candidates(scope, [_image_block(glued, [154, 321, 465, 488])])

        assert cand.kind == "figure"
        assert cand.caption == "图 9 预测 8 种特定类型缺陷的 F1-score 值对比箱线图", \
            f"caption 仍与相邻对象粘连：{cand.caption!r}"

    def test_three_way_glue_keeps_only_first(self, world):
        scope = world["scope"]
        glued = ("Table 2 Spearman correlation of each component (BOSSv1.01 image database) "
                 "Table 1 Spearman correlation coefficients of each component "
                 "表 1 在不同 JPEG 隐写算法下,本文指标各组成成分的 Spearman 相关系数")
        (cand,) = _candidates(scope, [_image_block(glued, [100, 100, 500, 400], kind="table")])

        assert "Table 2" in cand.caption
        assert "Table 1" not in cand.caption, f"仍粘连了相邻表：{cand.caption!r}"

    def test_bilingual_same_object_caption_is_preserved(self, world):
        """同一对象的中英双语 caption：编号相同故**不按"不同对象"切断**，
        但按语言拆成 caption + caption_alt，**两种语言都不得丢**。"""
        scope = world["scope"]
        bilingual = ("(f) HH 分量 Fig.1 Comparison of the original image and stego images "
                     "图 1 原图像、各种隐写算法(0.05 bpac)隐写后的图像对比")
        (cand,) = _candidates(scope, [_image_block(bilingual, [100, 100, 500, 400])])

        combined = f"{cand.caption} {cand.caption_alt}"
        assert "Comparison of the original image" in combined, \
            f"英文段丢失：caption={cand.caption!r} alt={cand.caption_alt!r}"
        assert "图 1 原图像" in combined, \
            f"中文段丢失：caption={cand.caption!r} alt={cand.caption_alt!r}"
        assert cand.original_label == "1", "双语不得影响编号抽取"

    def test_subfigure_parent_caption_is_preserved(self, world):
        """``图 8(a)`` 与父图 ``图 8`` 属同一对象，不得被切。"""
        scope = world["scope"]
        text = "图 8(a) F1-score 图 8 使用不同采样方法的模型性能对比箱线图"
        (cand,) = _candidates(scope, [_image_block(text, [100, 100, 500, 400])])

        assert "图 8 使用不同采样方法" in cand.caption, f"父图 caption 被误切：{cand.caption!r}"

    def test_single_caption_unchanged(self, world):
        scope = world["scope"]
        text = "图 5 实验框架"
        (cand,) = _candidates(scope, [_image_block(text, [100, 100, 500, 400])])

        assert cand.caption == text


class TestDecorativeFigureFilter:
    def test_empty_tiny_figure_is_excluded(self, world):
        """无 caption 且面积过小（二维码/作者头像）→ excluded 且给出原因。"""
        scope = world["scope"]
        # 60×60 / (1000×1000) = 0.36%，与实测 0.60%–0.68% 同量级
        (cand,) = _candidates(scope, [_image_block("", [10, 10, 70, 70])])

        assert cand.excluded is True, "装饰性空图未被过滤"
        assert cand.exclusion_reason, "过滤必须给出可追溯原因"

    def test_empty_but_large_figure_is_kept(self, world):
        """真图可能丢了 caption（paper 3 ``677e3596…``，面积 4.8%）→ **不得**误删。"""
        scope = world["scope"]
        # 600×600 / 1e6 = 36%
        (cand,) = _candidates(scope, [_image_block("", [100, 100, 700, 700])])

        assert cand.excluded is False, "大图即使 caption 为空也必须保留"

    def test_captioned_small_panel_is_kept(self, world):
        """带 caption 的子图面板（0.82%–0.85%）→ **不得**误删。"""
        scope = world["scope"]
        # 90×90 / 1e6 = 0.81%
        (cand,) = _candidates(
            scope, [_image_block("(a) 原图", [142, 293, 232, 383])]
        )

        assert cand.excluded is False, "带 caption 的面板不得被当作装饰图删除"

    def test_figure_without_bbox_is_kept(self, world):
        """没有 bbox 就无法判定面积 → 不删（宁可保留，不凭猜删）。"""
        scope = world["scope"]
        (cand,) = _candidates(scope, [_image_block("")])

        assert cand.excluded is False

    def test_table_is_not_subject_to_figure_filter(self, world):
        """表格不参与装饰性图片过滤（表格无 caption 是另一种情况）。"""
        scope = world["scope"]
        (cand,) = _candidates(
            scope, [_image_block("", [10, 10, 70, 70], kind="table")]
        )

        assert cand.kind == "table"
        assert cand.excluded is False


class TestBilingualCaption:
    """同一对象的中英双语 caption：主语言进 ``caption``，另一种进 ``caption_alt``。

    实测 10 行是**行内拼接**（不是两条独立行），例如 paper 1 图 7：
    ``(f) HH 分量 Fig.1 Comparison of the original image … 图 1 原图像、各种隐写算法…``。
    丢弃另一种语言会丢信息，故用 ``caption_alt`` 无损保留。
    """

    def test_chinese_paper_prefers_chinese_caption(self, world):
        scope = world["scope"]
        bilingual = ("Fig.1 Comparison of the original image and stego images under "
                     "different embedding rates 图 1 原图像、各种隐写算法隐写后的图像对比")
        (cand,) = _candidates(
            scope, [_image_block(bilingual, [100, 100, 500, 400])],
            page_text="这是一篇中文论文的正文，用于确定文档主导语言。",
        )

        assert "图 1 原图像" in cand.caption, f"主语言应为中文：{cand.caption!r}"
        assert "Comparison of the original" not in cand.caption, \
            f"主 caption 不应再混入英文：{cand.caption!r}"
        assert "Comparison of the original" in cand.caption_alt, \
            f"英文段必须无损保留在 caption_alt：{cand.caption_alt!r}"

    def test_single_language_caption_untouched(self, world):
        scope = world["scope"]
        text = "图 5 实验框架"
        (cand,) = _candidates(scope, [_image_block(text, [100, 100, 500, 400])],
                              page_text="中文正文。")

        assert cand.caption == text
        assert cand.caption_alt == ""

    def test_short_latin_run_does_not_trigger_split(self, world):
        """短英文（图号/缩写）不算双语，不得被误切。"""
        scope = world["scope"]
        text = "图 3 存在重入漏洞的 Solidity 智能合约代码片段"
        (cand,) = _candidates(scope, [_image_block(text, [100, 100, 500, 400])],
                              page_text="中文正文。")

        assert cand.caption == text
        assert cand.caption_alt == ""


class TestSubfigureParent:
    """子图面板与父图**不合并行**（REFACTOR_SPEC §480 要求子图独立），
    但必须补上父图编号，否则面板在图谱/讲解里是无主的孤儿。"""

    def test_panel_without_label_inherits_parent_number(self, world):
        scope = world["scope"]
        # (a) 面板：自身没有 图 N；同一 y 带右侧是带完整父图号的 (b)
        cands = _candidates(scope, [
            _image_block("(a) F1-score", [142, 320, 300, 480], ordinal=0),
            _image_block("(b) g-mean 图 8 使用不同采样方法的模型性能对比箱线图",
                         [320, 320, 480, 480], ordinal=1),
        ])
        panel, parent = cands[0], cands[1]

        assert parent.original_label == "8"
        assert panel.original_label == "8", \
            f"子图面板应继承父图编号，实际 {panel.original_label!r}"
        assert "(a)" in panel.caption, "面板自身的 caption 不得被覆盖"

    def test_two_distinct_figures_side_by_side_are_not_merged(self, world):
        """paper 3 p14 的图 6/图 7 是**两个不同图并排**，不得互相认亲。"""
        scope = world["scope"]
        cands = _candidates(scope, [
            _image_block("图 6 缺陷倾向性预测模型性能比较箱线图 (F1-score)",
                         [142, 320, 300, 480], ordinal=0),
            _image_block("图 7 缺陷倾向性预测模型性能比较箱线图 (g-mean)",
                         [320, 320, 480, 480], ordinal=1),
        ])

        assert cands[0].original_label == "6"
        assert cands[1].original_label == "7"

    def test_panel_without_any_parent_keeps_none(self, world):
        scope = world["scope"]
        (cand,) = _candidates(scope, [
            _image_block("(a) 单独的图", [142, 320, 300, 480]),
        ])

        assert cand.original_label is None, "找不到父图时不得凭空编号"
