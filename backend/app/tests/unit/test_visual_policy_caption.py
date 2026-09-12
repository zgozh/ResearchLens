"""M4 / D-80（后端侧）：公式本体只在 caption 里时，不许判"原件不可用"。

实测背景（paper 7 的 14 条 media，`.scratch/verify_media_policy.cjs`）：
5 条公式的 `extracted.latex` 是 `null`、也没有资产，但公式本体完整地写在 `caption`
（`$$…\\tag{1}$$`）。后端 `_has_extracted()` 只认 `table_html/latex/table_cells/
equation_label` → 判 `unavailable`，与前端策略分叉（前端已认 caption）。

本文件锁住后端这一侧的口径，与 `frontend/tests/sourcePolicy.spec.ts` 一一对应。
"""
from __future__ import annotations

from app.contracts.artifacts import Media, MediaProvenance
from app.contracts.common import Scope

SCOPE = Scope(paper_id=7, revision_id="rev-media")

FORMULA_CAPTION = (
    "$$\n\\operatorname{Attention} (Q, K, V) = \\operatorname{softmax} "
    "(\\frac {Q K ^ {T}}{\\sqrt {d _ {k}}}) V\\tag{1}\n$$"
)


def _media(**over) -> Media:
    base = dict(
        scope=SCOPE, id="m1", kind="equation", caption="",
        provenance=MediaProvenance(
            representation="extracted", verification="unverified",
            source_document_id="sd1",
        ),
    )
    base.update(over)
    return Media(**base)


class TestCaptionFormulaCountsAsExtracted:
    def test_equation_with_formula_only_in_caption_is_extracted(self):
        from app.modules import visual

        policy = visual.get_policy(_media(caption=FORMULA_CAPTION))
        assert policy.default_mode == "extracted", policy
        assert "不可用" not in policy.label

    def test_inline_dollar_formula_in_caption_also_counts(self):
        from app.modules import visual

        assert visual.get_policy(_media(caption="rate $P_{drop}=0.1$ used")).default_mode == "extracted"

    def test_plain_caption_does_not_make_it_displayable(self):
        """普通题注**不许**被当成公式表示（那是无中生有）。"""
        from app.modules import visual

        policy = visual.get_policy(_media(caption="Figure 1: The Transformer architecture."))
        assert policy.default_mode == "unavailable", policy

    def test_empty_caption_still_unavailable(self):
        from app.modules import visual

        assert visual.get_policy(_media(caption="")).default_mode == "unavailable"

    def test_latex_field_still_wins(self):
        """回归：`extracted.latex` 有值时行为不变。"""
        from app.contracts.artifacts import ExtractedMedia
        from app.modules import visual

        media = _media(caption="", extracted=ExtractedMedia(latex="E = mc^2"))
        assert visual.get_policy(media).default_mode == "extracted"
