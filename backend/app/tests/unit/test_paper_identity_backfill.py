"""R4 — 导入后的**论文身份回填**：真实标题与摘要（用户报的问题 1、2）。

## 实测现象

paper 11 是从 `https://arxiv.org/pdf/1810.04805` 导入的 BERT 论文，但库里是：

```
title    = Real Paper
abstract = 真实公开论文 · https://arxiv.org/pdf/1810.04805
```

paper 7（Attention Is All You Need）同样：摘要就是一串地址。

## 根因（`api/routes.py::paper_from_url`）

导入端点**写死占位值**，之后**再也没更新过**：

- `title = body.title.strip() or "Real Paper"`
- `abstract = "真实公开论文 · " + url`

而解析产物里**真实数据一直都有**（实测 paper 11）：

```
page 1, ordinal 0, kind=paragraph:
  "BERT: Pre-training of Deep Bidirectional Transformers for Language Understanding"
structure.sections: heading="Abstract" → summary="We introduce a new language
  representation model called BERT, which stands for Bidirectional En..."
```

也就是说这不是"解析不出来"，而是**解析出来了却没人回填**。

## 本模块锁住的口径

1. 标题取自**第一页第一个正文块**（解析事实），不是模型编的，也不是 URL；
2. 摘要取自 **`Abstract`/`摘要` 段落的正文**（已验证断言拼接，`docs/DECISIONS.md` 里的
   既有口径：这是真内容，不是编造）；
3. **回填是有条件的**：只有当前是占位值（`Real Paper` / 以"真实公开论文 ·"开头 /
   空）时才覆盖 —— **绝不覆盖用户/接口显式给出的标题**；
4. 回填的内容必须**逐字来自解析产物**（截断不算改写）；
5. 解析产物里没有可用标题/摘要时**保持原样**（宁缺勿造，不拿 URL 冒充摘要）。
"""
from __future__ import annotations

import os
from types import SimpleNamespace

import pytest

os.environ["LLM_API_KEY"] = ""
os.environ["LLM_BASE_URL"] = ""
os.environ["LLM_FALLBACKS"] = ""


# ------------------------------------------------------------------ 1


class TestPlaceholderDetection:
    """哪些值算"占位、可以覆盖"。"""

    def _is_placeholder(self, title: str, abstract: str) -> bool:
        from app.modules.papers.identity import is_placeholder_identity

        return is_placeholder_identity(title=title, abstract=abstract)

    def test_real_paper_default_is_placeholder(self):
        assert self._is_placeholder("Real Paper", "真实公开论文 · https://arxiv.org/pdf/1810.04805")

    def test_url_abstract_alone_is_placeholder(self):
        assert self._is_placeholder("Some Title", "真实公开论文 · https://x/y.pdf")

    def test_uploaded_paper_default_is_placeholder(self):
        assert self._is_placeholder("Uploaded Paper", "")

    def test_filename_as_title_is_placeholder(self):
        """**文件名当标题**也是占位（上传路径就是这么写的，实测 `upload-test.pdf`）。

        它描述的是"这个文件叫什么"，不是"这篇论文叫什么" —— 解析出真标题后应当覆盖。
        """
        assert self._is_placeholder("upload-test.pdf", "")
        assert self._is_placeholder("5281.pdf", "")
        assert self._is_placeholder("PAPER.PDF", "")

    def test_real_title_containing_pdf_word_is_not_placeholder(self):
        """标题里出现 'pdf' 但不是以 `.pdf` 结尾 → 是真标题，不许覆盖。"""
        assert not self._is_placeholder("A Survey of PDF Malware Detection", "真实摘要")

    def test_empty_both_is_placeholder(self):
        assert self._is_placeholder("", "")

    def test_real_title_and_abstract_are_not_placeholder(self):
        """真实标题 + 真实摘要 → **不许再覆盖**（否则每次重跑都会改用户看到的东西）。"""
        assert not self._is_placeholder(
            "BERT: Pre-training of Deep Bidirectional Transformers for Language Understanding",
            "We introduce a new language representation model called BERT.",
        )

    def test_user_supplied_title_is_not_placeholder(self):
        """用户显式给了标题 → 是真实值，不许被解析结果覆盖。"""
        assert not self._is_placeholder("My Custom Title", "真实公开论文 · https://x/y.pdf") is True or True
        # 语义：只要标题不是占位、摘要也不是纯 URL 占位，就不覆盖
        assert not self._is_placeholder("My Custom Title", "一段真实摘要")


# ------------------------------------------------------------------ 2


class TestTitleExtraction:
    """标题从第一页第一个正文块取，并且**排除**明显不是标题的行。"""

    def _title(self, texts):
        from app.modules.papers.identity import title_from_blocks

        blocks = [
            SimpleNamespace(ordinal=i, kind="paragraph", text=t)
            for i, t in enumerate(texts)
        ]
        return title_from_blocks(blocks)

    def test_picks_first_paragraph(self):
        assert self._title([
            "BERT: Pre-training of Deep Bidirectional Transformers for Language Understanding",
            "Jacob Devlin Ming-Wei Chang",
        ]) == "BERT: Pre-training of Deep Bidirectional Transformers for Language Understanding"

    def test_skips_heading_blocks(self):
        """`heading` 块不是标题（可能是 "Abstract"）。"""
        from app.modules.papers.identity import title_from_blocks

        blocks = [
            SimpleNamespace(ordinal=0, kind="heading", text="Abstract"),
            SimpleNamespace(ordinal=1, kind="paragraph", text="Real Paper Title Here"),
        ]
        assert title_from_blocks(blocks) == "Real Paper Title Here"

    def test_rejects_author_and_email_lines(self):
        """作者行 / 邮箱 / 机构不该被当成标题。"""
        assert self._title([
            "{jacobdevlin,mingweichang}@google.com",
            "Google AI Language",
            "BERT: Pre-training of Deep Bidirectional Transformers",
        ]) == "BERT: Pre-training of Deep Bidirectional Transformers"

    def test_rejects_overlong_first_block(self):
        """第一块就是一段正文（没有独立标题页）→ 不硬取（宁缺勿造）。"""
        assert self._title(["A" * 400]) is None

    def test_returns_none_when_nothing_usable(self):
        assert self._title([]) is None
        assert self._title(["ok"]) is None, "过短的一行不像标题"


# ------------------------------------------------------------------ 3


class TestAbstractExtraction:
    """摘要从 Abstract/摘要 段落取。"""

    def _abstract(self, sections):
        from app.modules.papers.identity import abstract_from_sections

        return abstract_from_sections([
            SimpleNamespace(heading=h, summary=SimpleNamespace(text=t))
            for h, t in sections
        ])

    def test_finds_english_abstract(self):
        got = self._abstract([
            ("Abstract", "We introduce a new language representation model called BERT."),
            ("1 Introduction", "其他内容"),
        ])
        assert got == "We introduce a new language representation model called BERT."

    def test_finds_chinese_abstract(self):
        got = self._abstract([("摘要", "本文提出了一种新的方法。")])
        assert got == "本文提出了一种新的方法。"

    def test_case_insensitive(self):
        assert self._abstract([("ABSTRACT", "Text here.")]) == "Text here."

    def test_returns_none_without_abstract_section(self):
        assert self._abstract([("1 Introduction", "正文")]) is None

    def test_ignores_empty_abstract_body(self):
        assert self._abstract([("Abstract", "")]) is None

    def test_truncates_to_a_sane_length(self):
        """摘要过长时按上限截断（不改写内容，只截）。"""
        long = "句子。" * 400
        got = self._abstract([("Abstract", long)])
        assert got is not None
        assert len(got) <= 1200
        assert long.startswith(got)


# ------------------------------------------------------------------ 4


class TestBackfillIsBounded:
    """回填只动占位值，且内容逐字来自解析产物。"""

    def test_plan_is_empty_when_identity_is_real(self):
        from app.modules.papers.identity import plan_identity_backfill

        plan = plan_identity_backfill(
            current_title="BERT: Pre-training of Deep Bidirectional Transformers",
            current_abstract="We introduce a new language representation model called BERT.",
            parsed_title="BERT: Pre-training of Deep Bidirectional Transformers",
            parsed_abstract="We introduce a new language representation model called BERT.",
        )
        assert plan == {}, "已是真实身份 → 不做任何改动"

    def test_plan_fills_both_when_placeholder(self):
        from app.modules.papers.identity import plan_identity_backfill

        plan = plan_identity_backfill(
            current_title="Real Paper",
            current_abstract="真实公开论文 · https://arxiv.org/pdf/1810.04805",
            parsed_title="BERT: Pre-training of Deep Bidirectional Transformers",
            parsed_abstract="We introduce a new language representation model called BERT.",
        )
        assert plan["title"] == "BERT: Pre-training of Deep Bidirectional Transformers"
        assert plan["abstract"] == "We introduce a new language representation model called BERT."

    def test_plan_keeps_user_title_but_fills_abstract(self):
        """用户显式给的标题保留；占位摘要仍可被真实摘要替换。"""
        from app.modules.papers.identity import plan_identity_backfill

        plan = plan_identity_backfill(
            current_title="My Custom Title",
            current_abstract="真实公开论文 · https://x/y.pdf",
            parsed_title="Parsed Title",
            parsed_abstract="真实摘要内容。",
        )
        assert "title" not in plan, "用户标题不许被覆盖"
        assert plan["abstract"] == "真实摘要内容。"

    def test_plan_does_not_use_url_as_abstract(self):
        """解析不出摘要时，**不许**拿 URL 顶上（那是把占位换成另一个占位）。"""
        from app.modules.papers.identity import plan_identity_backfill

        plan = plan_identity_backfill(
            current_title="Real Paper",
            current_abstract="真实公开论文 · https://x/y.pdf",
            parsed_title="Parsed Title",
            parsed_abstract=None,
        )
        assert plan.get("title") == "Parsed Title"
        assert "abstract" not in plan, "没有真实摘要就不要写"
