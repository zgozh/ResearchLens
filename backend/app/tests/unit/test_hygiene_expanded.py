"""M3 卫生门禁**扩面**（REFACTOR_PLAN_R3）：把扫描面从"章节/表格/媒体题注"
扩到 **证据引文 / 问答回答 / 评测文案** 这三类此前没被扫过的文本。

为什么必须扩：R3 的用户问题的根因就是**漏面** —— 渲染内核统一了，但证据卡、证据抽屉、
讲解引文这些地方仍是裸插值（M1 一次就查出 8 处）。卫生门禁当时只扫章节/表格/题注，
**恰好扫不到出问题的那几类文本**。

本文件的语料是**实测文本**（paper 7 / paper 10 的解析产物与真实问答回答），
不是编的；断言口径与既有 `test_text_hygiene_gate.py` 一致。
"""
from __future__ import annotations

import re

import pytest

from app.contracts.textnorm import IssueCode
from app.modules.textnorm import normalize, scan

#: 证据引文切片（实测：paper 7 的 evidence.source_text）
EVIDENCE_SAMPLES = [
    "Table 2 summarizes our results and compares our translation quality and training costs "
    "to other model architectures from the literature.",
    "$$ l r a t e = d _ {\\mathrm{model}} ^ {- 0. 5} \\cdot \\min (s t e p \\_ n u m ^ {- 0. 5}, "
    "s t e p \\_ n u m \\cdot w a r m u p \\_ s t e p s ^ {- 1. 5})\\tag{3} $$",
    "For the base model, we use a rate of $P _ { d r o p } = 0 . 1$",
    "Ashish Vaswani<sup>∗</sup> Google Brain avaswani@google.com",
    "We propose a new simple network architecture, the Transformer, based solely on attention "
    "mechanisms, dispensing with recurrence and convolutions entirely.",
]

#: 问答落库回答（实测：paper 7 的真实回答 + 拒答模板）
QA_ANSWER_SAMPLES = [
    "提出仅基于注意力机制的Transformer模型，摒弃RNN/CNN结构，在机器翻译任务上实现更优性能与更低训练成本。",
    "论文中没有提到「量子计算」。我只依据这篇论文的原文作答，不会拿别的相关内容顶替。",
    "我在这篇论文里没有找到能支撑这个问题的原文证据，所以不能给出结论"
    "（本产品只依据论文原文作答，不编造）。可以换一种更具体的问法试试。\n\n"
    "与问题最接近的原文片段（第 4 页，仅供参考、未通过证据校验）："
    "$$ \\operatorname{Attention} (Q, K, V) = \\operatorname{softmax} (\\frac {Q K ^ {T}}"
    "{\\sqrt {d _ {k}}}) V\\tag{1} $$",
]

#: 评测 reason 文案（M10/R3-M9 会直接显示给用户的那些）
EVAL_REASON_SAMPLES = [
    "source_pdf_has_no_coordinate_rects：原文 PDF 未提供坐标矩形，该指标设计上不可测（拒绝编造 IoU）",
    "usage_missing_in_answer_rows：作答记录里没有 token / 时延用量",
    "no_golden_truth：缺少人工确认的参考断言（AI 起草的只能算 proxy）",
    "模型语义判定：原文明确指出 Adam 优化器的 β₁ = 0.9，而陈述声称 β₁ = 0，二者数值直接矛盾。",
]

ALL_SAMPLES = EVIDENCE_SAMPLES + QA_ANSWER_SAMPLES + EVAL_REASON_SAMPLES
_UNPAIRED_DOLLAR = re.compile(r"(?<!\\)\$")


class TestExpandedHygiene:
    @pytest.mark.parametrize("sample", ALL_SAMPLES)
    def test_plain_has_no_unpaired_dollar_or_block_residue(self, sample):
        plain = normalize(sample, kind="body").plain
        assert not _UNPAIRED_DOLLAR.search(plain), f"落单 $：{plain!r}"
        assert "$$" not in plain, f"残留 $$：{plain!r}"

    @pytest.mark.parametrize("sample", ALL_SAMPLES)
    def test_rich_leaves_have_no_delimiters(self, sample):
        result = normalize(sample, kind="body")

        def leaves(nodes):
            for node in nodes:
                if getattr(node, "children", None):
                    yield from leaves(node.children)
                elif getattr(node, "text", None) is not None:
                    yield node.text

        for leaf in leaves(result.rich):
            assert "$$" not in leaf and "\\tag" not in leaf, leaf

    @pytest.mark.parametrize("sample", ALL_SAMPLES)
    def test_issue_codes_within_enum(self, sample):
        allowed = set(IssueCode.__args__)  # type: ignore[attr-defined]
        for issue in scan(sample):
            assert issue.code in allowed, issue.code

    @pytest.mark.parametrize("sample", ALL_SAMPLES)
    def test_second_pass_is_stable(self, sample):
        once = normalize(sample, kind="body")
        twice = normalize(once.plain, kind="body")
        assert twice.plain == once.plain
        added = {i.code for i in twice.issues} - {i.code for i in once.issues}
        assert not added, added


class TestGateCanActuallyFailOnThesePaths:
    """门禁必须能红：这三类文本里塞入未归类脏模式时，必须被报出来。"""

    def test_unknown_tag_in_evidence_quote_is_reported(self):
        result = normalize("见 <mark>高亮</mark> 片段", kind="body")
        assert any(i.code == "UNKNOWN_TAG" for i in result.issues), result.issues

    def test_unpaired_dollar_in_qa_answer_is_reported(self):
        result = normalize("答案是 $10 左右", kind="body")
        assert any(i.code == "UNPAIRED_DOLLAR" for i in result.issues), result.issues

    def test_control_char_in_eval_reason_is_reported(self):
        result = normalize("原因\x07未记录", kind="body")
        assert any(i.code == "CONTROL_CHAR" for i in result.issues), result.issues
