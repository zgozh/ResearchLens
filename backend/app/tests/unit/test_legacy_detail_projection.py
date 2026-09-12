"""旧详情投影（路线 A）：把 canonical 产物补进旧 DTO，让前端"有内容"。

背景（2026-09-12 实测 ``/api/papers/1``）：
- ``map_summary = {}`` → MapView 六个六维卡片全渲染成 "—"（论文地图空白）
- ``abstract`` 长度 0、``authors``/``tags`` 为空 → 地图页头部信息全空
- ``figures[0].image_b64 = ""`` 且 ``glyph_svg = ""``、只有 ``media_id``
  → 前端 ``FigureImage`` 只认内联 b64/svg，于是"有摘要没图"

根因：这些字段取自 **legacy ``papers`` 表列**（真实论文没有这些列值），
而 canonical 侧的 ``structure.map`` / 首页正文 / ``media.original_asset_ids``
**没有被投影**。本文件锁定"canonical → 旧 DTO"的补充规则。
"""
from __future__ import annotations

import os
from types import SimpleNamespace

os.environ.setdefault("LLM_API_KEY", "")


def _item(kind: str, text: str):
    return SimpleNamespace(kind=kind, text=SimpleNamespace(text=text, spans=[]))


def _section(heading: str, kind: str, summary: str = "", blocks=()):
    return SimpleNamespace(
        heading=heading, kind=kind,
        summary=SimpleNamespace(text=summary, spans=[]),
        source_block_ids=list(blocks), anchor_ids=[],
    )


class TestMapSummaryFromCanonical:
    def test_canonical_map_items_fill_the_six_boxes(self):
        """``structure.map.items`` 的 problem/method/result/limitation 必须进 map_summary。"""
        from app.modules.papers.legacy import map_summary_from_structure

        structure = SimpleNamespace(map=SimpleNamespace(items=[
            _item("problem", "现有指标只建模局部线性关系"),
            _item("method", "提出 Haar 小波域高阶范数指标"),
            _item("result", "隐蔽性提高约 7.7%"),
            _item("limitation", "未覆盖空域隐写"),
        ]))

        out = map_summary_from_structure(structure, [])

        assert out["problem"].startswith("现有指标")
        assert out["method"].startswith("提出 Haar")
        assert out["result"].startswith("隐蔽性")
        assert out["limitation"].startswith("未覆盖")

    def test_experiment_box_comes_from_section_kind(self):
        """``experiment``/``dataset`` 两个键 canonical map 里没有，
        用**章节 kind/summary** 兜底（仍然只取已验证内容，不编造）。"""
        from app.modules.papers.legacy import map_summary_from_structure

        sections = [
            _section("5 实验", "experiment", "在 BOSS 数据集上比较五种指标"),
            _section("2 数据集", "experiment", "使用 BOSS v0.92/v1.01 图像库"),
        ]

        out = map_summary_from_structure(None, sections)

        assert "BOSS 数据集" in out["experiment"] or "BOSS" in out["experiment"]

    def test_missing_sources_leave_keys_absent_not_fabricated(self):
        """没有任何 canonical 来源时**不得编造**——键缺失，前端自然显示 "—"。"""
        from app.modules.papers.legacy import map_summary_from_structure

        out = map_summary_from_structure(None, [])
        assert out == {}


class TestAbstractFromPages:
    def test_abstract_extracted_from_first_page_markers(self):
        """真实论文首页含 "摘 要:" … "关键词"，要切出摘要而不是整页。"""
        from app.modules.papers.legacy import abstract_from_page_text

        page = (
            "基于 Haar 小波域指标自适应选择载体的 JPEG 隐写\\*\n"
            "黄炜 $^{1}$ ，赵险峰 $^{2}$\n"
            "摘 要: 为了解决现有指标难以有效刻画纹理复杂度的问题，本文提出一种新的指标。\n"
            "关键词: JPEG 隐写；载体选择；Haar 小波\n"
            "中图法分类号: TP309\n"
        )

        out = abstract_from_page_text(page)

        assert out.startswith("为了解决现有指标")
        assert "关键词" not in out
        assert "黄炜" not in out

    def test_english_abstract_marker_supported(self):
        from app.modules.papers.legacy import abstract_from_page_text

        page = "Title Here\nAbstract: We propose a new metric for JPEG steganography.\nKeywords: steganography\n"
        out = abstract_from_page_text(page)

        assert out.startswith("We propose")
        assert "Keywords" not in out

    def test_no_marker_falls_back_to_empty_not_garbage(self):
        """没有可识别标记 → 返回空串（宁缺勿造），不要把整页当摘要。"""
        from app.modules.papers.legacy import abstract_from_page_text

        assert abstract_from_page_text("只有正文，没有任何摘要标记。") == ""
        assert abstract_from_page_text("") == ""


class TestSectionBodyAndPages:
    """章节必须给出**真实正文**与**真实页码**。

    实测缺陷：``sections[].body`` 与 ``summary`` 完全相同（都是断言拼接），
    且 ``page`` 恒为 1 —— 前端"阅读该章节正文"因此永远跳到第 1 页。
    canonical 的 ``SectionRecord.source_block_ids`` 本来就有真实块与页码。
    """

    def _block(self, bid, page_id, text):
        return SimpleNamespace(id=bid, page_id=page_id, text=text)

    def test_body_joins_real_blocks_not_summary(self):
        from app.modules.papers.legacy import section_body_and_pages

        section = SimpleNamespace(source_block_ids=["b1", "b2"],
                                  summary=SimpleNamespace(text="这是摘要，不是正文"))
        blocks = [
            self._block("b1", "pg1", "第一段真实正文。"),
            self._block("b2", "pg1", "第二段真实正文。"),
        ]

        body, start, end = section_body_and_pages(section, blocks, {"pg1": 3})

        assert "第一段真实正文" in body and "第二段真实正文" in body
        assert "这是摘要" not in body, "正文不得再拿 summary 充数"
        assert (start, end) == (3, 3)

    def test_pages_span_min_and_max_of_blocks(self):
        from app.modules.papers.legacy import section_body_and_pages

        section = SimpleNamespace(source_block_ids=["b1", "b2", "b3"], summary=None)
        blocks = [
            self._block("b1", "pg5", "起"),
            self._block("b2", "pg6", "中"),
            self._block("b3", "pg5", "末"),
        ]

        _, start, end = section_body_and_pages(section, blocks, {"pg5": 5, "pg6": 6})

        assert (start, end) == (5, 6), "应给出本节的**页范围**，前端据此定位"

    def test_empty_section_returns_zero_not_fabricated(self):
        from app.modules.papers.legacy import section_body_and_pages

        body, start, end = section_body_and_pages(
            SimpleNamespace(source_block_ids=[], summary=None), [], {}
        )
        assert (body, start, end) == ("", 0, 0)

    def test_unknown_page_mapping_keeps_body_without_pages(self):
        """块在库里但页码映射缺失 → 仍给正文，页码为 0（不猜）。"""
        from app.modules.papers.legacy import section_body_and_pages

        section = SimpleNamespace(source_block_ids=["b1"], summary=None)
        body, start, end = section_body_and_pages(
            section, [self._block("b1", "pgX", "正文仍在")], {}
        )
        assert body == "正文仍在"
        assert (start, end) == (0, 0)


class TestTextMarkupCleanup:
    """解析器留下的 markdown/LaTeX 转义符必须清掉。

    实测 ``pages[0].text`` 里是 ``…的 JPEG 隐写\\*``、``黄炜 $^{1}$ ，赵险峰`` ——
    反斜杠转义在页面上就是"一堆没转义的字符"。
    注意**不能动 ``$...$``**：前端 ``MathText`` 用 KaTeX 渲染它，清了反而丢公式。
    """

    def test_star_escape_is_removed(self):
        from app.modules.papers.legacy import clean_text_markup

        assert clean_text_markup("JPEG 隐写\\*") == "JPEG 隐写"

    def test_underscore_and_hash_escapes_unwrapped(self):
        from app.modules.papers.legacy import clean_text_markup

        assert clean_text_markup("a\\_b 与 c\\#d") == "a_b 与 c#d"

    def test_inline_math_is_preserved_for_katex(self):
        """``$...$`` 必须原样保留（前端 KaTeX 渲染），否则公式全丢。"""
        from app.modules.papers.legacy import clean_text_markup

        src = "其中 $8\\times8$ 分块与 $^{1}$ 表示单位阵"
        out = clean_text_markup(src)
        assert "$8\\times8$" in out
        assert "$^{1}$" in out

    def test_nbsp_and_whitespace_normalised(self):
        from app.modules.papers.legacy import clean_text_markup

        assert clean_text_markup("甲\u00a0\u00a0乙   丙") == "甲 乙 丙"

    def test_empty_is_safe(self):
        from app.modules.papers.legacy import clean_text_markup

        assert clean_text_markup("") == ""
        assert clean_text_markup(None) == ""


class TestFigureImageUrl:
    def test_figure_carries_asset_url_when_media_has_asset(self):
        """``figures[]`` 必须给出可访问的图片 URL —— 前端不再只认内联 b64。"""
        from app.modules.papers.legacy import figure_image_url

        url = figure_image_url(SimpleNamespace(original_asset_ids=["asset-1"]))
        assert url and "asset-1" in url

    def test_figure_without_asset_has_empty_url(self):
        """没有真图资产时给空串（**绝不**回退到 parser_raw JSON）。"""
        from app.modules.papers.legacy import figure_image_url

        assert figure_image_url(SimpleNamespace(original_asset_ids=[])) == ""
        assert figure_image_url(SimpleNamespace(original_asset_ids=None)) == ""
