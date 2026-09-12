"""M1 textnorm 单测 —— 真实 MinerU 粗产物风格的中英混合 fixture。

覆盖（与任务书「测试要点」一一对应）：
1. header 作者行 ``<sup>`` + 无字符丢失
2. 行内公式 ``$P _ { d r o p } = 0 . 1$`` → ``P_{drop}=0.1``
3. 跨行 ``$$…\\tag{1}$$`` → math_block + ``tag_no="1"``
4. 未配对 ``$``（奇数个）→ 无 math 节点 + UNPAIRED_DOLLAR
5. 转义 ``\\$`` → 字面美元、无 issue
6. 非白名单标签 → UNKNOWN_TAG + 字面量保留
7. 控制符剥离
8. 幂等 + plain/rich 一致性
9. ``scan()`` 的 issue code 是 IssueCode Literal 的子集（枚举漂移检查）
"""
from __future__ import annotations

from typing import Iterable, List, Set, get_args

import pytest

from app.contracts.textnorm import IssueCode, RichNode
from app.modules.textnorm import normalize, scan

D = "$"
B = "$$"
SUP_MARK = "\u2217"  # ∗

#: 真实 MinerU 风格的脏样本（中英混合）
FIXTURES = [
    ("header", "Ashish Vaswani<sup>\u2217</sup> Google Brain avaswani@google.com"),
    ("caption", "Table 1: \u6a21\u578b\u5728 WMT 2014 \u4e0a\u7684 BLEU \u5206\u6570\u3002"),
    ("inline_math", "For the base model, we use a rate of $P _ { d r o p } = 0 . 1$"),
    ("block_math", B + "\n \\operatorname{Attention}(Q, K, V) \\tag{1}\n" + B),
    ("unk_tag", "the token <unk> and <table> both appear"),
    ("control", "abc\x00def\x07ghi"),
    ("unpaired", "costs $10 only."),
    ("escaped_dollar", "the rf\\$importance is high"),
    ("residue", "a $$ b"),
    ("mixed", "\u4e2d\u6587\u6b63\u6587\u3002$E = m c ^ { 2 }$\u540e\u7eed\u5185\u5bb9\u3002"),
    ("paren_math", "see \\(a^{2} + b^{2}\\) here"),
]


def leaves(nodes: Iterable[RichNode]) -> str:
    """按规格第 11 条拼接叶子文本。

    ``br`` 的 ``text`` 按契约恒为 ``None``，它贡献一个换行（否则 ``<br>`` 语义丢失）。
    """
    out: List[str] = []
    for node in nodes:
        if node.children is not None:
            out.append(leaves(node.children))
        elif node.type == "br":
            out.append("\n")
        else:
            out.append(node.text or "")
    return "".join(out)


def codes(issues) -> Set[str]:
    return {issue.code for issue in issues}


def of_type(nodes: Iterable[RichNode], node_type: str) -> List[RichNode]:
    return [node for node in nodes if node.type == node_type]


# --------------------------------------------------------------- 1. header 作者行


class TestHeaderLine:
    def test_sup_container_holds_mark(self):
        src = "Ashish Vaswani<sup>\u2217</sup> Google Brain avaswani@google.com"
        result = normalize(src, kind="header")

        sups = of_type(result.rich, "sup")
        assert len(sups) == 1
        assert sups[0].children is not None
        assert leaves(sups[0].children) == "\u2217"
        assert sups[0].text is None

    def test_plain_has_no_tag_literals_and_no_char_loss(self):
        src = "Ashish Vaswani<sup>\u2217</sup> Google Brain avaswani@google.com"
        result = normalize(src, kind="header")

        assert "<sup>" not in result.plain
        assert "</sup>" not in result.plain
        # 去标签后逐字比对：一个字符都不能丢
        stripped = src.replace("<sup>", "").replace("</sup>", "")
        assert result.plain == stripped
        assert "avaswani@google.com" in result.plain

    def test_bare_mark_run_becomes_sup_only_for_header_kind(self):
        src = f"Ashish Vaswani{SUP_MARK} Google Brain avaswani@google.com"

        header = normalize(src, kind="header")
        sups = of_type(header.rich, "sup")
        assert len(sups) == 1
        assert leaves(sups[0].children) == SUP_MARK
        assert header.plain == src  # 不删任何字符（含机构与邮箱）

        # body / caption 不做这项特判
        for kind in ("body", "caption"):
            other = normalize(src, kind=kind)
            assert of_type(other.rich, "sup") == []
            assert other.plain == src

    def test_whitelist_tags_still_work_for_body(self):
        src = "x<sup>1</sup>y<sub>2</sub>z<i>a</i> <b>b</b>"
        result = normalize(src, kind="body")
        assert [node.type for node in result.rich] == [
            "text", "sup", "text", "sub", "text", "i", "text", "b",
        ]
        assert result.plain == "x1y2za b"
        assert leaves(result.rich) == result.plain

    def test_attributes_ignored_and_case_insensitive(self):
        src = 'A<SUP CLASS="fn" data-x="1">\u2020</SUP>B'
        result = normalize(src, kind="header")
        sups = of_type(result.rich, "sup")
        assert len(sups) == 1
        assert result.plain == "A\u2020B"
        assert "CLASS" not in result.plain


# --------------------------------------------------------------- 2/3. 公式


class TestInlineMath:
    def test_pdrop_compacted(self):
        src = "For the base model, we use a rate of $P _ { d r o p } = 0 . 1$"
        result = normalize(src)

        maths = of_type(result.rich, "math_inline")
        assert len(maths) == 1
        body = maths[0].text or ""
        assert body == "P_{drop}=0.1"
        assert " " not in body
        assert D not in body
        # 同一句正文原样保留（一个空格都不许动）
        assert result.plain.startswith("For the base model, we use a rate of ")
        assert result.plain == "For the base model, we use a rate of P_{drop}=0.1"

    def test_paren_delimiter_inline(self):
        result = normalize("see \\(d _ { k }\\) here")
        maths = of_type(result.rich, "math_inline")
        assert len(maths) == 1
        assert maths[0].text == "d_{k}"
        assert result.plain == "see d_{k} here"

    def test_delimiters_never_leak_into_node(self):
        for src in ("$a$", "\\(a\\)"):
            result = normalize(src)
            maths = of_type(result.rich, "math_inline")
            assert maths and "\\(" not in (maths[0].text or "")
            assert D not in (maths[0].text or "")

    def test_inline_tag_is_not_stripped_but_flagged(self):
        result = normalize("$a\\tag{9}$")
        maths = of_type(result.rich, "math_inline")
        assert maths[0].text == "a\\tag{9}"       # 行内不剥离
        assert maths[0].tag_no is None
        suspects = [i for i in result.issues if i.code == "LATEX_SUSPECT"]
        assert suspects and suspects[0].severity == "warn"


class TestBlockMath:
    SRC = (
        B + "\n \\operatorname{Attention}(Q, K, V) = \\operatorname{softmax}"
        "(\\frac{QK^{T}}{\\sqrt{d_{k}}})V \\tag{1}\n" + B
    )

    def test_cross_line_block_with_tag(self):
        result = normalize(self.SRC)
        blocks = of_type(result.rich, "math_block")
        assert len(blocks) == 1
        body = blocks[0].text or ""
        assert blocks[0].tag_no == "1"
        assert B not in body
        assert "\\tag" not in body
        assert "\\sqrt{d_{k}}" in body          # 空格已压缩
        assert result.plain == body

    def test_bracket_block_delimiter(self):
        result = normalize("before \\[E = m c ^ { 2 }\\] after")
        blocks = of_type(result.rich, "math_block")
        assert len(blocks) == 1
        assert blocks[0].text == "E=mc^{2}"
        assert result.plain == "before E=mc^{2} after"

    def test_tag_number_extracted_not_defaulted(self):
        result = normalize(B + "x \\tag{2.7}" + B)
        assert of_type(result.rich, "math_block")[0].tag_no == "2.7"

    def test_empty_math_yields_no_node_and_no_literal(self):
        result = normalize("a " + B + B + " b")
        assert of_type(result.rich, "math_block") == []
        assert result.plain == "a  b"
        assert B not in result.plain


# --------------------------------------------------------------- 4/5. 美元符


class TestDollarHandling:
    def test_unpaired_dollar_odd_count(self):
        result = normalize("costs $10 only.")
        assert of_type(result.rich, "math_inline") == []
        assert of_type(result.rich, "math_block") == []
        assert D in result.plain                      # 字面美元被保留（转义形式）
        assert result.plain == "costs \\$10 only."
        issues = [i for i in result.issues if i.code == "UNPAIRED_DOLLAR"]
        assert len(issues) == 1
        assert issues[0].offset == 6                  # 指向原始输入中的那个 $

    def test_offset_points_into_raw_input(self):
        src = "abc $x def"
        issue = [i for i in scan(src) if i.code == "UNPAIRED_DOLLAR"][0]
        assert src[issue.offset] == D

    def test_escaped_dollar_is_literal(self):
        src = "the rf\\$importance is high"
        result = normalize(src)
        assert of_type(result.rich, "math_inline") == []
        assert D in result.plain
        assert "UNPAIRED_DOLLAR" not in codes(result.issues)
        assert result.plain == src

    def test_even_dollar_count_pairs_up(self):
        """规格明示：恰好 2 个 $ 会被配成公式（因此未配对样本要用奇数个）。"""
        result = normalize("The price is $10 and the other is $20 dollars.")
        assert len(of_type(result.rich, "math_inline")) == 1
        assert "UNPAIRED_DOLLAR" not in codes(result.issues)

    def test_unmatched_block_delimiter_residue(self):
        result = normalize("a $$ b")
        assert of_type(result.rich, "math_block") == []
        assert "BLOCK_DELIMITER_RESIDUE" in codes(result.issues)
        assert B not in result.plain

    def test_unmatched_paren_delimiter_is_plain_text(self):
        """未配对的 \\( 只是普通文本 —— 不报 issue，否则下一轮会重复报（破坏幂等）。"""
        result = normalize("a \\( b")
        assert of_type(result.rich, "math_inline") == []
        assert result.plain == "a \\( b"
        assert result.issues == []


# --------------------------------------------------------------- 6. 标签


class TestInlineTagsWhitelist:
    def test_unknown_tags_preserved_as_escaped_literal(self):
        result = normalize("<unk> and <table>")
        found = [i for i in result.issues if i.code == "UNKNOWN_TAG"]
        assert len(found) == 2
        assert found[0].offset == 0
        assert found[1].offset == 10
        # 「不丢字符」：转义实体解码后与原字面量逐字相同
        assert result.plain == "&lt;unk&gt; and &lt;table&gt;"
        assert result.plain.replace("&lt;", "<").replace("&gt;", ">") == "<unk> and <table>"

    def test_script_tag_is_escaped_not_executed(self):
        result = normalize('<script>alert(1)</script>')
        assert "<script>" not in result.plain
        assert "&lt;script&gt;" in result.plain
        assert result.issues and result.issues[0].code == "UNKNOWN_TAG"

    def test_br_becomes_br_node(self):
        result = normalize("a<br>b")
        assert of_type(result.rich, "br")
        assert result.plain == "a\nb"

    def test_stray_closing_tag_not_silently_dropped(self):
        result = normalize("x</sup>y")
        assert "UNKNOWN_TAG" in codes(result.issues)
        assert result.plain == "x&lt;/sup&gt;y"

    def test_empty_container_pruned(self):
        result = normalize("x<sup></sup>y")
        assert of_type(result.rich, "sup") == []
        assert result.plain == "xy"


# --------------------------------------------------------------- 7/8. 卫生


class TestSanitize:
    def test_control_chars_stripped(self):
        result = normalize("abc\x00def\x07")
        assert result.plain == "abcdef"
        assert "CONTROL_CHAR" in codes(result.issues)

    def test_consecutive_control_run_merged_into_one_issue(self):
        result = normalize("a\x00\x01\x02b")
        control = [i for i in result.issues if i.code == "CONTROL_CHAR"]
        assert len(control) == 1
        assert control[0].offset == 1

    def test_newline_and_tab_are_kept(self):
        result = normalize("a\n\tb")
        assert result.plain == "a\n\tb"
        assert result.issues == []

    def test_fullwidth_normalized_only_inside_math(self):
        src = "\uff08\u6b63\u6587\uff09$P\uff08d\uff09\uff1d0.1$"
        result = normalize(src)
        assert result.plain == "\uff08\u6b63\u6587\uff09P(d)=0.1"   # 正文全角原样
        assert "MIXED_WIDTH" in codes(result.issues)

    def test_body_whitespace_untouched(self):
        src = "a  b\t c \u3000d"
        assert normalize(src).plain == src


# --------------------------------------------------------------- 9/11. 不变量


class TestInvariants:
    @pytest.mark.parametrize("name,src", FIXTURES, ids=[f[0] for f in FIXTURES])
    def test_plain_equals_rich_leaves(self, name, src):
        """规格第 11 条：rich 叶子按顺序拼接必须逐字等于 plain。"""
        result = normalize(src)
        assert leaves(result.rich) == result.plain

    @pytest.mark.parametrize("name,src", FIXTURES, ids=[f[0] for f in FIXTURES])
    def test_idempotent_and_clean_on_second_pass(self, name, src):
        """规格第 9 条：plain 是不动点，且第二轮不再产出三类结构性问题。"""
        first = normalize(src)
        second = normalize(first.plain)

        assert second.plain == first.plain
        assert leaves(second.rich) == second.plain
        assert not (codes(second.issues) & {
            "UNPAIRED_DOLLAR", "UNKNOWN_TAG", "BLOCK_DELIMITER_RESIDUE",
        })

    @pytest.mark.parametrize("name,src", FIXTURES, ids=[f[0] for f in FIXTURES])
    def test_scan_codes_are_subset_of_issue_code_literal(self, name, src):
        """枚举漂移检查：scan() 只允许返回 IssueCode Literal 内的 code。"""
        allowed = set(get_args(IssueCode))
        assert codes(scan(src)) <= allowed

    @pytest.mark.parametrize("name,src", FIXTURES, ids=[f[0] for f in FIXTURES])
    def test_excerpt_within_contract_limit(self, name, src):
        for issue in scan(src):
            assert 0 < len(issue.excerpt) <= 80

    def test_scan_works_on_raw_string_without_normalize(self):
        src = "mixed $P _ { d r o p }$ and <unk> and \x01"
        found = codes(scan(src))
        assert "UNKNOWN_TAG" in found
        assert "CONTROL_CHAR" in found

    @pytest.mark.parametrize("name,src", FIXTURES, ids=[f[0] for f in FIXTURES])
    def test_normalize_issues_match_scan(self, name, src):
        """normalize 的 issues 就是原始输入 scan 的结果（同一遍扫描，不允许分叉）。"""
        triples = lambda issues: [(i.code, i.severity, i.offset) for i in issues]
        assert triples(normalize(src).issues) == triples(scan(src))

    def test_severity_vocabulary(self):
        result = normalize("costs $10 only.")
        assert {i.severity for i in result.issues} <= {"info", "warn"}

    def test_compaction_emits_info_level_issue(self):
        """规格第 4 条：压缩改变了 body 必须产出一条 info 级 issue。"""
        result = normalize("$d _ { k }$")
        info = [i for i in result.issues if i.severity == "info"]
        assert [i.code for i in info] == ["LATEX_SUSPECT"]

    def test_clean_text_has_no_issues(self):
        result = normalize("A perfectly clean English sentence, no math at all.")
        assert result.issues == []
        assert result.plain == "A perfectly clean English sentence, no math at all."
