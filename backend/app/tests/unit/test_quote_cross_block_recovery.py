"""跨块引文纠错：模型标错块号时，按**逐字存在**把引文救回来（ADR-0040）。

真实缺陷（Postgres 实测 paper 2）：一轮 12 条断言里 **8 条**报
``quote_not_in_block``。根因不是模型编造引文，而是
``_draft_batch_from_raw`` **只在模型自己报的那个块里找引文**：MinerU 会把一段话
拆进相邻块（跨页、表题与表体相邻），模型复述时块号极易错位，
于是**逐字正确的引文**也被丢弃 → citations 空 → gate 全拒 →
用户看到的"证据链少证据/图谱少连线"。

修法：主匹配失败后，在**本次语料覆盖的所有块**里再找一次，但只接受能产生
``QuoteSpan`` 的档位（exact / normalized / 空白无关），**绝不接受 fuzzy**——
纠错的前提是"这段引文确实逐字存在于某块原文"，否则就是给引文随便找个落点。
"""
from __future__ import annotations

import os
from types import SimpleNamespace

os.environ.setdefault("LLM_API_KEY", "")

from app.contracts.common import Scope  # noqa: E402

BLOCK_A = "本文提出了一种基于 Haar 小波域指标自适应选择载体的 JPEG 隐写方法。"
BLOCK_B = (
    "该指标通过计算图像在 Haar 小波域的高频成分分解图像的高阶范数,"
    "用以优选 JPEG 隐写的载体图像."
)
BLOCK_C = "实验在 BOSS v0.92 与 BOSS v1.01 图像库上进行, 每次随机选取 1000 张图像."

QUOTE_IN_B = "该指标通过计算图像在 Haar 小波域的高频成分分解图像的高阶范数"


def _index():
    """模拟 ``service._build_corpus`` 的 block_index：短编号 → (uuid, 原文)。"""
    return {
        "B1": ("uuid-a", BLOCK_A),
        "B2": ("uuid-b", BLOCK_B),
        "B3": ("uuid-c", BLOCK_C),
    }


class TestMatchAcrossBlocks:
    def test_finds_the_block_that_really_contains_the_quote(self):
        from app.modules.evidence import locator

        match = locator.match_quote_across_blocks(
            proposed_quote=QUOTE_IN_B,
            blocks=[("uuid-a", BLOCK_A), ("uuid-b", BLOCK_B), ("uuid-c", BLOCK_C)],
        )

        assert match is not None, "逐字存在的引文必须能在别的块里被找到"
        assert match.block_id == "uuid-b"
        assert match.span is not None and match.kind in ("exact", "normalized")
        # 回填的必须是**原文真实切片**
        assert match.span.source_text in BLOCK_B

    def test_prefers_exact_over_normalized(self):
        from app.modules.evidence import locator

        # 同一个引文在 A 块需要规范化才能匹配、在 B 块是精确子串
        a_text = "本文 提出了一种基于 Haar 小波域指标自适应选择载体的 JPEG 隐写方法。"
        b_text = f"（前言）{QUOTE_IN_B}（后记）"
        match = locator.match_quote_across_blocks(
            proposed_quote=QUOTE_IN_B, blocks=[("uuid-a", a_text), ("uuid-b", b_text)]
        )

        assert match is not None and match.kind == "exact", f"实际 kind={match.kind}"
        assert match.block_id == "uuid-b"

    def test_recovers_when_only_whitespace_differs(self):
        from app.modules.evidence import locator

        spaced = "该指标通过计算图像在 Haar 小波域的高频成分分解图像的高阶范数".replace("小波域", "小波 域")
        match = locator.match_quote_across_blocks(
            proposed_quote=spaced, blocks=[("uuid-b", BLOCK_B)]
        )

        assert match is not None and match.span is not None
        assert match.kind == "normalized"

    def test_never_returns_fuzzy_only_candidates(self):
        """**关键**：改写过的引文不得被"纠错"到某个块上（那就是伪造引用）。"""
        from app.modules.evidence import locator

        paraphrase = "作者认为隐写技术并不重要因此没有开展任何实验"
        match = locator.match_quote_across_blocks(
            proposed_quote=paraphrase,
            blocks=[("uuid-a", BLOCK_A), ("uuid-b", BLOCK_B), ("uuid-c", BLOCK_C)],
        )

        assert match is None, f"改写句不得被纠错命中，实际 {match!r}"

    def test_returns_none_for_empty_quote(self):
        from app.modules.evidence import locator

        assert locator.match_quote_across_blocks(proposed_quote="  ", blocks=[("u", BLOCK_A)]) is None

    def test_no_blocks_gives_none(self):
        from app.modules.evidence import locator

        assert locator.match_quote_across_blocks(proposed_quote=QUOTE_IN_B, blocks=[]) is None


class TestTrimmedQuoteRecovery:
    """引文**逐字存在**但模型多加了前缀/后缀时的恢复（ADR-0045）。

    实测（paper 2 诊断）：模型报的引文是
    ``Download Percentile (i) = \\frac {n - r a n k _ {i}}{n}.``，
    而原文块里只有后半段 —— 引文**本身逐字存在**，只是被套了一个不属于原文的前缀。
    同一批失配里另外 3 条是**改写/翻译**（原文是中文、引文是英文），必须继续拒绝。
    """

    def test_longest_verbatim_substring_is_recovered(self):
        from app.modules.evidence import locator

        original = "该方法通过计算图像在 Haar 小波域的高频成分分解图像的高阶范数,用以优选载体图像."
        with_prefix = "Download Percentile 公式如下：" + original

        match = locator.match_quote_trimmed(
            block_id="uuid-b", text=original, proposed_quote=with_prefix
        )

        assert match is not None and match.span is not None
        assert match.kind == "trimmed"
        assert match.span.source_text in original
        assert "Download" not in match.span.source_text, "回填的必须是原文切片"

    def test_suffix_noise_is_trimmed(self):
        from app.modules.evidence import locator

        original = "实验采用十折交叉验证并在两个数据集上重复三次."
        with_suffix = original + " 以上为译者补充说明,原文未出现。"

        match = locator.match_quote_trimmed(
            block_id="uuid-c", text=original, proposed_quote=with_suffix
        )

        assert match is not None and match.span is not None
        assert match.span.source_text in original

    def test_translation_is_still_rejected(self):
        """**关键**：译文不得被"最长子串"救回（中文原文 vs 英文引文）。"""
        from app.modules.evidence import locator

        original = "同理,当一个应用发布新的版本后,可以通过用户的更新率表示进行更新的用户比例."
        translation = "can use users' update ratio to represent the proportion of users who updated"

        assert locator.match_quote_trimmed(
            block_id="uuid-b", text=original, proposed_quote=translation
        ) is None

    def test_too_short_overlap_is_rejected(self):
        """重叠太短不算引用（否则任何句子里的"研究"二字都能挂上）。"""
        from app.modules.evidence import locator

        original = "本文提出了一种基于 Haar 小波域指标自适应选择载体的 JPEG 隐写方法。"
        unrelated = "相关工作部分讨论了隐写分析的研究进展与未来展望。"

        assert locator.match_quote_trimmed(
            block_id="uuid-a", text=original, proposed_quote=unrelated
        ) is None

    def test_exact_quote_is_not_labelled_trimmed(self):
        """本来就逐字命中的，不该被标成 trimmed（保留原档位语义）。"""
        from app.modules.evidence import locator

        original = "该指标通过计算图像在 Haar 小波域的高频成分分解图像的高阶范数"
        match = locator.match_quote_trimmed(
            block_id="uuid-b", text=original, proposed_quote=original
        )

        assert match is not None and match.kind in ("exact", "normalized")


class TestDraftBatchUsesCrossBlockRecovery:
    def _raw(self, *, block_id: str, quote: str):
        return SimpleNamespace(claims=[{
            "claim_id": "cross_block_claim",
            "statement": "该指标用高阶范数均值优选载体图像。",
            "type": "METHOD",
            "quotes": [{"block_id": block_id, "quote": quote}],
        }])

    def test_wrong_block_number_is_corrected_and_reported(self):
        """模型报 B1、引文其实在 B2 → 必须挂到 B2 并留可审计的纠错告警。"""
        from app.modules.claims import service as claims_svc

        raw = self._raw(block_id="B1", quote=QUOTE_IN_B)
        drafts, warnings = claims_svc._draft_batch_from_raw(
            raw, Scope(paper_id=1, revision_id="rev-cross"), _index()
        )

        codes = [w.code for w in warnings]
        assert "quote_not_in_block" not in codes, [(w.code, w.message) for w in warnings]
        assert "quote_block_corrected" in codes, codes
        assert len(drafts) == 1 and len(drafts[0].citations) == 1
        assert drafts[0].citations[0].block_id == "uuid-b", \
            f"引用必须挂到真正包含它的块，实际 {drafts[0].citations[0].block_id}"
        assert drafts[0].citations[0].proposed_quote in BLOCK_B

    def test_correct_block_number_is_untouched(self):
        """块号本来就对 → 不得产生纠错告警（避免噪声）。"""
        from app.modules.claims import service as claims_svc

        raw = self._raw(block_id="B2", quote=QUOTE_IN_B)
        drafts, warnings = claims_svc._draft_batch_from_raw(
            raw, Scope(paper_id=1, revision_id="rev-cross2"), _index()
        )

        codes = [w.code for w in warnings]
        assert "quote_block_corrected" not in codes, codes
        assert drafts[0].citations[0].block_id == "uuid-b"

    def test_quote_absent_everywhere_still_rejected(self):
        """**安全网不是放宽**：语料里根本没有的引文，照旧丢弃。"""
        from app.modules.claims import service as claims_svc

        raw = self._raw(block_id="B1", quote="这句话在整篇语料里都不存在")
        drafts, warnings = claims_svc._draft_batch_from_raw(
            raw, Scope(paper_id=1, revision_id="rev-cross3"), _index()
        )

        assert [w.code for w in warnings].count("quote_not_in_block") == 1
        assert drafts and drafts[0].citations == [], "不得为不存在的引文造假引用"

    def test_quote_with_spurious_prefix_is_trimmed_and_reported(self):
        """引文被套了非原文前缀 → 取最长逐字子串，并留 ``quote_trimmed`` 告警。"""
        from app.modules.claims import service as claims_svc

        raw = self._raw(
            block_id="B2", quote="Download Percentile 公式如下：" + QUOTE_IN_B,
        )
        drafts, warnings = claims_svc._draft_batch_from_raw(
            raw, Scope(paper_id=1, revision_id="rev-trim"), _index()
        )

        codes = [w.code for w in warnings]
        assert "quote_not_in_block" not in codes, [(w.code, w.message) for w in warnings]
        assert "quote_trimmed" in codes, codes
        cite = drafts[0].citations[0]
        assert cite.block_id == "uuid-b"
        assert "Download" not in cite.proposed_quote, f"引文必须是原文切片：{cite.proposed_quote!r}"
        assert cite.proposed_quote in BLOCK_B
