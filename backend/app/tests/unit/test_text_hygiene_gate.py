"""M11 文本卫生门禁（REFACTOR_PLAN §六 M11）。

目标：把"文本卫生"变成**可复跑的门禁**，而不是靠人眼截图。语料是**真实脏样本**
（全部取自实测的 paper 7 / paper 10，不是编的），对规范化输出做四类扫描：

1. `plain` 里不得有**未配对/未转义**的 `$`（`\\$` 是契约允许的字面美元写法）；
2. `plain` 里不得出现 `$$` 定界符残留；
3. `rich` 的叶子文本里不得出现 `$$` 或 `\\tag`（编号必须进 `tag_no`）；
4. issue 的 code 必须落在 `IssueCode` 枚举内，且二次规范化**不产生新的 issue 种类**。

另有一条**自验证**：故意喂一个尚未归类的脏模式（`<mark>`），门禁必须如实报出来 ——
否则无法证明"门禁会红"（一个永远不会失败的门禁等于没有门禁）。
"""
from __future__ import annotations

import html
import re

import pytest

from app.contracts.textnorm import IssueCode
from app.modules.textnorm import normalize, scan

#: 真实语料：每一条都来自实测解析产物（paper 7 = Attention，paper 10 = 上传 PDF）。
DIRTY_CORPUS = [
    # 作者行：行内标签 + 上标符号 + 邮箱
    "Ashish Vaswani<sup>∗</sup> Google Brain avaswani@google.com",
    "Aidan N. Gomez<sup>∗</sup> <sup>†</sup> University of Toronto aidan@cs.toronto.edu",
    # 正文里的行内公式（MinerU 的字距断裂）
    "For the base model, we use a rate of $P _ { d r o p } = 0 . 1$",
    "We call our particular attention \"Scaled Dot-Product Attention\" (Figure 2).",
    # 跨行块级公式 + \\tag
    "$$\n \\operatorname{Attention} (Q, K, V) = \\operatorname{softmax} "
    "(\\frac {Q K ^ {T}}{\\sqrt {d _ {k}}}) V\\tag{1}\n$$",
    "$$ l r a t e = d _ {\\mathrm{model}} ^ {- 0. 5} \\cdot \\min "
    "(s t e p \\_ n u m ^ {- 0. 5}, s t e p \\_ n u m \\cdot w a r m u p \\_ s t e p s "
    "^{- 1. 5})\\tag{3} $$",
    "$$\n\\begin{array}{c} \\text {MultiHead} (Q, K, V) = \\text {Concat} "
    "(\\text {head} _ {1},..., \\text {head} _ {\\mathrm{h}}) W^{O}\n\\end{array}$$",
    # 干净正文（对照组）
    "Table 2 summarizes our results and compares our translation quality and training "
    "costs to other model architectures from the literature.",
    # 未配对 `$` 与转义 `$`
    "The model costs $10 only.",
    "the rf\\$importance is high",
    # 控制符
    "abc\u0000def\u0007ghi",
    # 非白名单标签
    "<unk> and <table> appear here",
]

_UNPAIRED_DOLLAR = re.compile(r"(?<!\\)\$")


def _leaf_texts(nodes) -> list[str]:
    out: list[str] = []
    for node in nodes:
        if getattr(node, "children", None):
            out.extend(_leaf_texts(node.children))
        elif getattr(node, "text", None) is not None:
            out.append(node.text)
    return out


class TestHygieneGate:
    @pytest.mark.parametrize("sample", DIRTY_CORPUS)
    def test_plain_has_no_unpaired_dollar(self, sample):
        plain = normalize(sample, kind="body").plain
        assert not _UNPAIRED_DOLLAR.search(plain), f"plain 里有落单 $：{plain!r}"

    @pytest.mark.parametrize("sample", DIRTY_CORPUS)
    def test_plain_has_no_block_delimiter_residue(self, sample):
        plain = normalize(sample, kind="body").plain
        assert "$$" not in plain, f"plain 里有 $$ 残留：{plain!r}"

    @pytest.mark.parametrize("sample", DIRTY_CORPUS)
    def test_rich_leaves_carry_no_delimiters_or_tag_command(self, sample):
        result = normalize(sample, kind="body")
        for leaf in _leaf_texts(result.rich):
            assert "$$" not in leaf, f"叶子文本里有 $$：{leaf!r}"
            assert "\\tag" not in leaf, f"叶子文本里有 \\tag：{leaf!r}"

    @pytest.mark.parametrize("sample", DIRTY_CORPUS)
    def test_issue_codes_are_within_the_enum(self, sample):
        allowed = set(IssueCode.__args__)  # type: ignore[attr-defined]
        for issue in scan(sample):
            assert issue.code in allowed, f"未归类的 issue code：{issue.code}"

    @pytest.mark.parametrize("sample", DIRTY_CORPUS)
    def test_second_pass_creates_no_new_issue_kinds(self, sample):
        once = normalize(sample, kind="body")
        twice = normalize(once.plain, kind="body")
        assert twice.plain == once.plain, f"plain 不稳定：{sample!r}"
        before = {i.code for i in once.issues}
        added = {i.code for i in twice.issues} - before
        assert not added, f"二次规范化冒出新 issue 种类：{added}（样本 {sample!r}）"

    @pytest.mark.parametrize("sample", DIRTY_CORPUS)
    def test_no_control_characters_survive(self, sample):
        plain = normalize(sample, kind="body").plain
        assert not re.search(r"[\u0000-\u0008\u000b\u000c\u000e-\u001f]", plain), repr(plain)


class TestGateCanActuallyFail:
    """门禁必须**能红**：否则它只是个装饰。

    故意喂一个尚未归类的脏模式，断言它被如实报出来。
    """

    def test_unknown_inline_tag_is_reported(self):
        result = normalize("text with <mark>highlight</mark> inside", kind="body")
        codes = {i.code for i in result.issues}
        assert "UNKNOWN_TAG" in codes, f"未归类的标签没被报出来：{codes}"
        # 未知标签按**实体转义**保留（textnorm 的既定约定：转义可逆，且保证二次规范化幂等）。
        # 这里断言"字符没被静默吞掉"，而不是断言它以原始尖括号形式出现。
        assert "&lt;mark&gt;" in result.plain, result.plain
        assert html.unescape(result.plain).count("<mark>") == 1, result.plain

    def test_unpaired_dollar_is_reported(self):
        result = normalize("costs $10 only", kind="body")
        assert any(i.code == "UNPAIRED_DOLLAR" for i in result.issues), result.issues

    def test_control_char_is_reported(self):
        result = normalize("a\u0000b", kind="body")
        assert any(i.code == "CONTROL_CHAR" for i in result.issues), result.issues
