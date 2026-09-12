"""M06 语料分配：断言抽取必须**覆盖全文**而不是只读头部（ADR-0022）。

真实缺陷（fresh seed 后实测）：
``_build_corpus`` 按文档顺序累加块，到 ``TOTAL_CHAR_BUDGET`` 就 ``break``，
于是送进模型的语料只是论文**前面一小截**：

    paper 1: 156 块 / 23511 字 → 语料 15443 字 = 66%，只到第 0..6 页 / 共 10 页
    paper 2: 267 块 / 37319 字 → 语料 15988 字 = 43%，只到第 0..7 页 / 共 16 页
    paper 3: 400 块 / 54667 字 → 语料 15973 字 = 29%，只到第 0..6 页 / 共 25 页

后果是直接可观测的：paper 3 的**方法章与实验章（约第 8–20 页）从未进入模型**
→ ``method_steps=0``、只有 1 个场景、断言全部来自页 0–2。

而代码自己的意图是「预算内的原文块读取（**按章节分配，不只读头尾**）」
（``claims/repository.py`` 模块注释），``prompts.PER_SECTION_CHAR_BUDGET = 6000``
也早就定义好——但 grep 全仓它**从未被使用**，且 6 节 × 6000 = 36000
与 ``TOTAL_CHAR_BUDGET = 16000`` 自相矛盾。

本文件锁死修复后的契约：**每个章节都要有内容进入语料**；总量不超预算；
超份额的章节被截断时必须**点名**（否则缺陷再次不可见）。
"""
from __future__ import annotations

import os

import pytest

os.environ["LLM_API_KEY"] = ""
os.environ["LLM_BASE_URL"] = ""
os.environ["LLM_FALLBACKS"] = ""


def _row(idx: int, text: str, kind: str = "paragraph"):
    from app.modules.claims.repository import BlockRow

    return BlockRow(
        id=f"blk-{idx}", page_id=f"pg-{idx // 20}", ordinal=idx,
        kind=kind, text=text, anchor_id=None, origin="source_extraction",
    )


def _section_doc(sections, *, body_blocks=3, body_size=900):
    """造一篇 (标题, 正文前缀) 序列构成的正文，返回 BlockRow 列表。

    每节 = 1 个标题块 + ``body_blocks`` 个正文块（每块 ``body_size`` 字），
    正文块文本以 ``prefix-B{n}`` 开头，便于断言"哪一节进了语料"。
    """
    rows = []
    idx = 0
    for heading, prefix in sections:
        rows.append(_row(idx, heading))
        idx += 1
        for n in range(body_blocks):
            rows.append(_row(idx, f"{prefix}-B{n} " + "内容" * (body_size // 2)))
            idx += 1
    return rows


def _renumber(rows, *, offset):
    """把一批 BlockRow 的 id/ordinal 整体平移，便于拼接多段合成的正文。"""
    from app.modules.claims.repository import BlockRow

    return [
        BlockRow(id=f"blk-{offset + i}", page_id=r.page_id, ordinal=offset + i,
                 kind=r.kind, text=r.text, anchor_id=None, origin=r.origin)
        for i, r in enumerate(rows)
    ]


def _corpus(rows):
    from app.modules.claims import service as claims_service

    warnings = []
    corpus, block_index = claims_service._build_corpus(rows, warnings)
    return corpus, block_index, warnings


CORNERS = [
    ("1 引言", "SEC1"),
    ("2 相关工作", "SEC2"),
    ("3 方法", "SEC3"),
    ("4 实验", "SEC4"),
    ("5 结论", "SEC5"),
]


class TestSectionCoverage:
    def test_every_section_reaches_the_corpus(self):
        """**核心不变式**：最后一节的内容也必须进语料（不能只读头部）。"""
        rows = _section_doc(CORNERS, body_blocks=4, body_size=1400)
        corpus, _, _ = _corpus(rows)

        for _, prefix in CORNERS:
            assert f"{prefix}-B0" in corpus, (
                f"章节 {prefix} 完全没有进入语料——说明仍是「只读头部」。"
                f"语料里出现的节：{sorted({p for _, p in CORNERS if p in corpus})}"
            )

    def test_total_stays_within_budget(self):
        rows = _section_doc(CORNERS, body_blocks=6, body_size=1400)
        corpus, block_index, _ = _corpus(rows)

        from app.modules.claims import prompts

        entries = [line for line in corpus.split("\n") if line.strip()]
        assert sum(len(e) + 1 for e in entries) <= prompts.TOTAL_CHAR_BUDGET + 1

    def test_block_index_covers_every_cited_entry(self):
        """语料里出现的每个短编号都必须在 block_index 里有对应 uuid（否则引用无法回填）。"""
        rows = _section_doc(CORNERS, body_blocks=4, body_size=1200)
        corpus, block_index, _ = _corpus(rows)

        cited = {
            line.split("]")[0].lstrip("[")
            for line in corpus.split("\n") if line.startswith("[B")
        }
        assert cited, "语料里应至少有块编号"
        assert cited <= set(block_index), f"缺失编号：{sorted(cited - set(block_index))}"


class TestTruncationReporting:
    def test_oversized_section_is_truncated_and_named(self):
        """超份额的章节被截断时必须点名（这次缺陷不可见就是因为没有这个信号）。"""
        rows = []
        idx = 0
        # 第 1 节很小
        rows.append(_row(idx, "1 引言")); idx += 1
        rows.append(_row(idx, "SEC1-B0 " + "内容" * 200)); idx += 1
        # 第 2 节巨大（远超每节份额）
        rows.append(_row(idx, "2 方法")); idx += 1
        for n in range(80):
            rows.append(_row(idx, f"SEC2-B{n} " + "内容" * 800)); idx += 1
        # 第 3 节很小
        rows.append(_row(idx, "3 结论")); idx += 1
        rows.append(_row(idx, "SEC3-B0 " + "内容" * 200)); idx += 1

        corpus, _, warnings = _corpus(rows)
        codes = {w.code for w in warnings}

        assert "section_truncated" in codes, f"缺少截断点名警告，实际 {codes}"
        named = " ".join(w.message for w in warnings if w.code == "section_truncated")
        assert "2 方法" in named, f"警告必须点名被截章节，实际：{named}"
        # 被截的是第 2 节，但第 3 节仍然要进语料
        assert "SEC3-B0" in corpus, "一节超长不得挤掉后面的章节"

    def test_small_document_has_no_truncation_warning(self):
        rows = _section_doc([("1 引言", "SEC1")], body_blocks=2, body_size=200)
        _, _, warnings = _corpus(rows)

        assert not [w for w in warnings if w.code in ("budget_truncated", "section_truncated")]


class TestNoHeadingFallback:
    def test_document_without_headings_still_covers_tail(self):
        """没有可识别标题时不得退化成"只读头部"。"""
        rows = [_row(i, f"PLAIN-B{i} " + "内容" * 700) for i in range(40)]
        corpus, _, _ = _corpus(rows)

        assert "PLAIN-B0" in corpus, "开头必须在"
        assert "PLAIN-B39" in corpus, "结尾也必须在（否则就是只读头部）"

    def test_empty_rows_is_safe(self):
        corpus, block_index, warnings = _corpus([])
        assert corpus == ""
        assert block_index == {}
        assert not warnings

    def test_blank_blocks_are_skipped(self):
        rows = [_row(0, "1 引言"), _row(1, "   "), _row(2, "SEC1-B0 有内容")]
        corpus, block_index, _ = _corpus(rows)

        assert "SEC1-B0" in corpus
        assert all(v[1].strip() for v in block_index.values()), "空白块不得进入索引"


class TestNonEvidenceFurniture:
    """页眉/页脚/页码**永远不可能成为断言的一级依据**，不应占用语料预算。

    实测（fresh seed，2026-09-12）它们占掉 paper 1/2/3 语料的
    22%（header 6 + footer 6 + page_number 5 = 17/77）、24%、21%；
    更糟的是模型会**引用页码/标题当证据**，被 gate 以
    ``semantic_status=insufficient`` 拒绝（paper 1 的 6 条 claim 全部因此被拒）。
    """

    def test_furniture_blocks_are_excluded(self):
        rows = [
            _row(0, "1 引言"),
            _row(1, "SEC1-B0 " + "内容" * 300),
            _row(2, "第 3 页", kind="page_number"),
            _row(3, "软件学报 ISSN 1000-9825", kind="header"),
            _row(4, "2024 年 1 月 软件学报", kind="footer"),
            _row(5, "SEC1-B1 " + "内容" * 300),
        ]
        corpus, block_index, _ = _corpus(rows)

        assert "第 3 页" not in corpus, "页码不得进入语料"
        assert "ISSN 1000-9825" not in corpus, "页眉不得进入语料"
        assert "2024 年 1 月" not in corpus, "页脚不得进入语料"
        assert "SEC1-B0" in corpus and "SEC1-B1" in corpus, "正文必须仍在"

    def test_headings_stay_for_context(self):
        """标题要保留（给模型章节上下文），只清页码/页眉/页脚。"""
        rows = [_row(0, "2 方法"), _row(1, "SEC1-B0 " + "内容" * 300)]
        corpus, _, _ = _corpus(rows)

        assert "2 方法" in corpus

    def test_furniture_does_not_starve_later_sections(self):
        """大量页眉页脚不得把后面章节挤出去。"""
        rows = []
        idx = 0
        for _ in range(3):
            rows.append(_row(idx, "1 引言")); idx += 1
            rows.append(_row(idx, "SEC1-B0 " + "内容" * 400)); idx += 1
            for n in range(30):   # 大量"页脚污水"
                rows.append(_row(idx, f"软件学报 第 {n} 页", kind="footer")); idx += 1
        rows.append(_row(idx, "3 方法")); idx += 1
        rows.append(_row(idx, "SEC3-B0 " + "内容" * 400)); idx += 1

        corpus, _, _ = _corpus(rows)

        assert "SEC1-B0" in corpus
        assert "SEC3-B0" in corpus, "页脚污水不得挤掉后续章节"


class TestReferenceSections:
    """参考文献/致谢产生不了断言，占份额纯属浪费预算（实测 paper 1/2/3 各被分走
    12/16/9 块），还会诱发模型去引用文献而非正文。"""

    def test_english_reference_section_does_not_consume_budget(self):
        rows = _section_doc(
            [("1 引言", "SEC1"), ("2 方法", "SEC2"), ("References:", "REF")],
            body_blocks=3, body_size=1200,
        )
        corpus, _, _ = _corpus(rows)

        assert "REF-B0" not in corpus, "参考文献不得进入语料"
        assert "SEC1-B0" in corpus and "SEC2-B0" in corpus, "正文章节仍必须在"

    def test_chinese_reference_heading_also_skipped(self):
        rows = _section_doc(
            [("1 引言", "SEC1"), ("参考文献", "REF")],
            body_blocks=3, body_size=1200,
        )
        corpus, _, _ = _corpus(rows)

        assert "REF-B0" not in corpus
        assert "SEC1-B0" in corpus

    def test_huge_reference_section_does_not_starve_body_sections(self):
        """巨大的参考文献节不得把正文的份额吃光。"""
        body = _section_doc([("1 引言", "SEC1"), ("3 方法", "SEC3")],
                            body_blocks=2, body_size=1200)
        refs = _renumber(
            _section_doc([("References:", "REF")], body_blocks=60, body_size=4000),
            offset=1000,
        )
        corpus, _, _ = _corpus(body + refs)

        assert "REF-B0" not in corpus
        assert "SEC1-B0" in corpus and "SEC3-B0" in corpus, "正文章节必须仍被覆盖"

    def test_document_with_only_references_is_not_empty(self):
        """异常输入（全文只有参考文献）不得产出空语料——空语料会静默零断言。"""
        rows = _section_doc([("References:", "REF")], body_blocks=3, body_size=500)
        corpus, block_index, _ = _corpus(rows)

        assert corpus, "全部被跳过时必须有兜底，不能给空语料"
        assert block_index

