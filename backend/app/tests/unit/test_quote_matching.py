"""引用定位：M06 必须复用 M04 的定位器，而不是自己做精确子串比较。

真实缺陷（fresh seed 2026-09-12 实测）：paper 2 一轮抽出 12 条 claim，其中
**8 条** 的 validation 是 ``unsupported_entailment / 证据原文为空`` ——
即引用在 ``_draft_batch_from_raw`` 里就被丢光了，claim 因此无证据、被 gate 拒。

根因：M06 当时用的是 ``cite_quote not in block_text``（**精确子串**），而 MinerU 的
排版会在符号间插空格、混用全角字符、把连字拆开，模型复述时几乎不可能逐字复现。
M04 的 ``locator.match_quote`` 早就有 精确 → 规范化 → 模糊 三级匹配，
**M06 没有复用它**。

修法是复用 + 补一档"空白无关"匹配，并且**回填原文真实切片**（不伪造 quote）。
"""
from __future__ import annotations

import os

os.environ.setdefault("LLM_API_KEY", "")


class TestLocatorTextMatch:
    def test_exact_match_returns_raw_slice(self):
        from app.modules.evidence import locator

        m = locator.match_quote_text(
            block_id="b1", text="本文提出一种新的度量元集设计方法。",
            proposed_quote="新的度量元集设计方法",
        )

        assert m.kind == "exact" and m.span is not None
        assert m.span.source_text == "新的度量元集设计方法"

    def test_whitespace_variant_is_matched_and_returns_raw_slice(self):
        """**核心**：排版空白不同但引用真实存在时，必须命中并回填原文切片。"""
        from app.modules.evidence import locator

        block = "指标定义为 $$ f _ {W B} = \\frac {1}{3} \\left[ \\sum \\right] $$ 的平均值"
        quote = "f_{WB}=\\frac{1}{3}\\left[\\sum\\right]"   # 模型去掉了所有空格

        m = locator.match_quote_text(block_id="b1", text=block, proposed_quote=quote)

        assert m.span is not None, "去空白后可命中的引用被判为缺失"
        assert m.span.source_text in block, "回填的必须是原文真实切片"
        assert "f _ {W B}" in m.span.source_text

    def test_fullwidth_and_ligature_variant_matched(self):
        from app.modules.evidence import locator

        block = "ｄａｔａ 与 ﬁle 的关系"
        m = locator.match_quote_text(block_id="b1", text=block, proposed_quote="data 与 file")

        assert m.span is not None, "全角/连字规范化后应命中"

    def test_unrelated_quote_is_missing(self):
        """不得为了让引用通过而放宽到"像就行"——完全无关必须判缺失。"""
        from app.modules.evidence import locator

        m = locator.match_quote_text(
            block_id="b1", text="本文提出一种新的度量元集设计方法。",
            proposed_quote="实验在 ImageNet 上达到 91.2% 准确率",
        )

        assert m.span is None
        assert m.kind == "missing"

    def test_empty_quote_is_missing(self):
        from app.modules.evidence import locator

        m = locator.match_quote_text(block_id="b1", text="正文", proposed_quote="   ")
        assert m.kind == "missing" and m.span is None


class TestDraftBatchUsesLocator:
    def _draft(self, quotes, block_text):
        from types import SimpleNamespace

        from app.contracts.common import Scope
        from app.modules.claims import service as claims_service

        # 用 dict 形状（`_draft_batch_from_raw` 对 dict 直接取键，对对象才要 model_dump）
        raw = SimpleNamespace(claims=[{
            "claim_id": "c1",
            "statement": "本文指标在 JPEG 隐写下表现更好。",
            "quotes": [
                q if isinstance(q, dict) else {"block_id": q.block_id, "quote": q.quote}
                for q in quotes
            ],
            "qualifiers": [],
            "rationale": "",
        }])
        scope = Scope(paper_id=1, revision_id="rev-quote-test")
        block_index = {"B1": ("uuid-1", block_text)}
        return claims_service._draft_batch_from_raw(raw, scope, block_index)

    def test_spacing_variant_quote_is_kept_as_raw_slice(self):
        block = "其中 f _ {W B} = \\frac {1}{3} 表示平均范数"
        drafts, warnings = self._draft(
            [{"block_id": "B1", "quote": "f_{WB}=\\frac{1}{3}"}], block
        )

        assert drafts, "引用可命中时不得整条丢弃"
        cites = drafts[0].citations
        assert cites, f"引用应被保留，warnings={[w.code for w in warnings]}"
        assert cites[0].proposed_quote in block, "必须存原文真实切片"
        assert "f _ {W B}" in cites[0].proposed_quote

    def test_empty_quote_reports_quote_missing(self):
        """空引用以前是**静默丢弃**（无任何 warning），这是长期观测性缺口。"""
        drafts, warnings = self._draft([{"block_id": "B1", "quote": ""}], "正文内容")

        codes = {w.code for w in warnings}
        assert "quote_missing" in codes, f"空引用必须显式报告，实际 {codes}"
        assert drafts and drafts[0].citations == []

    def test_unmatched_quote_reports_quote_not_in_block(self):
        drafts, warnings = self._draft(
            [{"block_id": "B1", "quote": "完全无关的一句话内容"}], "正文内容"
        )

        codes = {w.code for w in warnings}
        assert "quote_not_in_block" in codes
        assert drafts[0].citations == []

    def test_unknown_block_reports_unknown_block(self):
        drafts, warnings = self._draft([{"block_id": "B99", "quote": "任意"}], "正文内容")

        assert "unknown_block" in {w.code for w in warnings}
        assert drafts[0].citations == []
