"""首页元信息派生：作者 / 关键词 / 年份 / 领域（ADR-0030）。

真实缺陷（3 篇真实论文 Postgres 实测）：``papers.authors = []``、``tags = []``、
``year`` 恒为入库年份 ``2026``、``domain`` 恒为 ``'general'``。

后果：前端"论文地图"的署名行永远空着、标签行永远空着、领域行恒显示 "general"，
而首页正文里这些信息**本来就有**（中文期刊首页第 2 行就是作者行，
摘要下方就是"关键词"行，页脚就是年份与卷期）。

修复方向：从**首页原文**派生这四项，并且**只认整行都是姓名**的作者行——
宁可返回空，也不要把单位行/页眉当作者（错误元信息比缺失元信息更糟）。
"""
from __future__ import annotations

import os

os.environ["LLM_API_KEY"] = ""
os.environ["LLM_BASE_URL"] = ""
os.environ["LLM_FALLBACKS"] = ""
os.environ["EMBEDDING_MODEL"] = ""


# 3 篇真实论文的首页片段（原样取自库中 pages[0].text）
PAGE1_HAAR = (
    "基于 Haar 小波域指标自适应选择载体的 JPEG 隐写\n"
    "黄炜 $^{1}$ ，赵险峰 $^{2}$\n"
    "$^{1}$ (厦门大学 软件学院, 福建 厦门 361005)\n"
    "$^{2}$ (信息安全国家重点实验室(中国科学院 信息工程研究所),北京 100093)\n"
    "通讯作者：黄炜, E-mail: whuang@xmu.edu.cn\n"
    "摘  要  为了解决目前图像纹理复杂度建模的隐写载体选择指标难以有效适用于 JPEG 隐写的问题,"
    "提出一种基于 Haar 小波域指标自适应选择载体的 JPEG 隐写方法.\n"
    "关键词  隐写;载体选择;Haar 小波;范数\n"
    "中图法分类号:TP309\n"
    "JPEG Steganography Based on Adaptive Cover Selection Using Haar Wavelet Domain Indicators\n"
    "HUANG Wei $^{1}$ , ZHAO Xian-Feng $^{2}$\n"
    "Abstract: The existing steganographic cover selection indicators ...\n"
    "Key words: steganography; cover selection; Haar wavelet; norm\n"
    "软件学报 Vol.29, No.8, August 2018\n"
)

PAGE1_SOLIDITY = (
    "基于软件度量的Solidity智能合约缺陷预测方法\n"
    "杨慧文 $^{1}$ ，崔展齐 $^{1,4}$ ，陈翔 $^{2}$ ，贾明华 $^{3}$ ，郑丽伟 $^{1}$\n"
    "$^{1}$ (北京信息科技大学 计算机学院, 北京 100101)\n"
    "摘  要  随着区块链技术的兴起, 智能合约安全问题被越来越多的研究者和企业重视.\n"
    "关键词  区块链;智能合约;软件缺陷预测;软件度量\n"
    "软件学报 Vol.34, No.2, February 2023\n"
)

PAGE1_NO_AUTHORS = (
    "Some Anonymous Preprint\n"
    "Abstract: This preprint has no author line at all.\n"
    "软件学报 Vol.29, No.8, August 2018\n"
)


class TestAuthorsFromPageText:
    def test_chinese_journal_author_line(self):
        from app.modules.papers.legacy import authors_from_page_text

        got = authors_from_page_text(PAGE1_HAAR, title="基于Haar小波域指标自适应选择载体的JPEG隐写")
        assert got == ["黄炜", "赵险峰"], f"实际 {got!r}"

    def test_multi_author_with_shared_superscripts(self):
        from app.modules.papers.legacy import authors_from_page_text

        got = authors_from_page_text(PAGE1_SOLIDITY, title="基于软件度量的Solidity智能合约缺陷预测方法")
        assert got == ["杨慧文", "崔展齐", "陈翔", "贾明华", "郑丽伟"], f"实际 {got!r}"

    def test_never_returns_affiliation_or_header_as_author(self):
        """单位行（含数字/括号）与页眉（Vol./No.）绝不能被当作者。"""
        from app.modules.papers.legacy import authors_from_page_text

        got = authors_from_page_text(PAGE1_HAAR, title="")
        for bad in ("厦门大学", "信息安全国家重点实验室", "软件学报", "August"):
            assert bad not in got, f"把 {bad!r} 当成了作者：{got!r}"
        assert not any(any(ch.isdigit() for ch in name) for name in got), f"作者名不应含数字：{got!r}"

    def test_missing_author_line_returns_empty(self):
        """没有作者行时返回空列表——不猜、不伪造。"""
        from app.modules.papers.legacy import authors_from_page_text

        assert authors_from_page_text(PAGE1_NO_AUTHORS, title="Some Anonymous Preprint") == []

    def test_english_author_line(self):
        from app.modules.papers.legacy import authors_from_page_text

        text = (
            "SlimSeg-Net: An Efficient Cross-Stage Attention Network\n"
            "Wenhao Chen $^{1}$ , Yue Li $^{2}$ , Kai Zhou $^{1}$\n"
            "$^{1}$ (Some University, Beijing 100000)\n"
            "Abstract: We propose ...\n"
        )
        got = authors_from_page_text(text, title="SlimSeg-Net: An Efficient Cross-Stage Attention Network")
        assert got == ["Wenhao Chen", "Yue Li", "Kai Zhou"], f"实际 {got!r}"


class TestKeywordsFromPageText:
    def test_chinese_keywords_line(self):
        from app.modules.papers.legacy import keywords_from_page_text

        got = keywords_from_page_text(PAGE1_HAAR)
        assert got == ["隐写", "载体选择", "Haar 小波", "范数"], f"实际 {got!r}"

    def test_english_key_words_line(self):
        from app.modules.papers.legacy import keywords_from_page_text

        got = keywords_from_page_text(PAGE1_HAAR)
        assert "隐写" in got
        text = "Title\nAuthor\nKey words: steganography; cover selection; Haar wavelet\n"
        assert keywords_from_page_text(text) == ["steganography", "cover selection", "Haar wavelet"]

    def test_no_keywords_returns_empty(self):
        from app.modules.papers.legacy import keywords_from_page_text

        assert keywords_from_page_text(PAGE1_NO_AUTHORS) == []


class TestYearAndDomainFromPageText:
    def test_year_prefers_repeated_page_year(self):
        from app.modules.papers.legacy import year_from_page_text

        assert year_from_page_text(PAGE1_HAAR) == 2018
        assert year_from_page_text(PAGE1_SOLIDITY) == 2023

    def test_year_none_when_absent(self):
        from app.modules.papers.legacy import year_from_page_text

        assert year_from_page_text("no year here") is None

    def test_domain_from_keywords(self):
        from app.modules.papers.legacy import domain_from_page_text

        assert domain_from_page_text(PAGE1_HAAR) == "security"
        assert domain_from_page_text(PAGE1_SOLIDITY) == "blockchain"
        assert domain_from_page_text("数据驱动的移动应用用户接受度建模与预测\n应用市场(app market)") == \
            "software-engineering"

    def test_domain_general_when_unknown(self):
        from app.modules.papers.legacy import domain_from_page_text

        assert domain_from_page_text("完全无关的文本") == "general"


class TestFrontMatterBundle:
    def test_bundle_returns_only_derivable_keys(self):
        from app.modules.papers.legacy import front_matter_from_page_text

        bundle = front_matter_from_page_text(PAGE1_HAAR, title="基于Haar小波域指标自适应选择载体的JPEG隐写")
        assert bundle["authors"] == ["黄炜", "赵险峰"]
        assert bundle["tags"] == ["隐写", "载体选择", "Haar 小波", "范数"]
        assert bundle["year"] == 2018
        assert bundle["domain"] == "security"

    def test_bundle_omits_empty_values(self):
        """派生不到就不给键：调用方据此决定是否覆盖 legacy 默认值。"""
        from app.modules.papers.legacy import front_matter_from_page_text

        bundle = front_matter_from_page_text(PAGE1_NO_AUTHORS, title="Some Anonymous Preprint")
        assert "authors" not in bundle, f"没有作者行时不得给 authors：{bundle!r}"
        assert "tags" not in bundle


class TestMergePolicy:
    """覆盖策略：已有的真值保留，空壳/误导值被替换。"""

    def test_keeps_existing_authors_and_tags(self):
        from app.modules.papers.legacy import merge_front_matter

        updates = merge_front_matter(
            {"authors": ["真实作者"], "tags": ["真实标签"], "year": None, "domain": None},
            {"authors": ["派生的"], "tags": ["派生的"], "year": 2018, "domain": "security"},
        )
        assert "authors" not in updates, "legacy 已有作者时不得覆盖"
        assert "tags" not in updates, "legacy 已有标签时不得覆盖"
        assert updates["year"] == 2018
        assert updates["domain"] == "security"

    def test_year_and_domain_override_placeholder_values(self):
        """legacy 的 year=入库年份、domain='general' 都是空壳，派生到就覆盖。"""
        from app.modules.papers.legacy import merge_front_matter

        updates = merge_front_matter(
            {"authors": [], "tags": [], "year": 2026, "domain": "general"},
            {"authors": ["黄炜"], "tags": ["隐写"], "year": 2018, "domain": "security"},
        )
        assert updates == {
            "authors": ["黄炜"], "tags": ["隐写"], "year": 2018, "domain": "security",
        }

    def test_empty_front_changes_nothing(self):
        from app.modules.papers.legacy import merge_front_matter

        assert merge_front_matter({"authors": [], "tags": [], "year": 2026, "domain": "general"}, {}) == {}
