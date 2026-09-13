"""论文身份回填：把解析产物里的**真实标题与摘要**写回 paper 行。

## 为什么需要（用户报的问题 1、2）

导入端点 `api/routes.py::paper_from_url` 写死占位值：

```python
title = body.title.strip() or "Real Paper"
abstract = "真实公开论文 · " + body.url
```

之后**再也没更新过**。于是实测 paper 11（arXiv 1810.04805 = BERT）在界面上是
「Real Paper」，摘要是「真实公开论文 · https://arxiv.org/pdf/1810.04805」。

而**真实数据一直在解析产物里**（实测）：

- 标题 = 第一页 `ordinal=0` 的 `paragraph` 块
  （`BERT: Pre-training of Deep Bidirectional Transformers for Language Understanding`）；
- 摘要 = `structure.sections` 里 `heading="Abstract"` 那一节的正文。

所以这不是"解析不出来"，而是"解析出来了没人回填"。

## 纪律

- **只覆盖占位值**：`Real Paper` / `Uploaded Paper` / 空 / 以「真实公开论文 ·」开头的摘要。
  用户或接口显式给的标题**绝不覆盖**（否则每次重跑都改用户看到的东西）；
- **逐字来自解析产物**（只截断，不改写）：标题不编、摘要不编；
- **取不到就保持原样**：绝不用 URL 去"补"一个摘要（那是拿占位换占位）。
"""
from __future__ import annotations

import logging
import re
from typing import Any, Iterable, Optional, Sequence

log = logging.getLogger("researchlens.papers.identity")

#: 已知的占位标题（导入端点在没有真标题时写的）
PLACEHOLDER_TITLES = frozenset({"real paper", "uploaded paper", "untitled", "paper"})

#: 占位摘要的前缀（导入端点写的是「真实公开论文 · {url}」）
PLACEHOLDER_ABSTRACT_PREFIX = "真实公开论文"

#: 摘要截断上限（不改写内容，只截）
MAX_ABSTRACT_CHARS = 1200

#: 标题的合理长度区间（过短像标签、过长是段落——第一块就过长说明该 PDF 没有独立标题行）
MIN_TITLE_CHARS = 8
MAX_TITLE_CHARS = 300

#: 明显不是标题的行（作者 / 机构 / 邮箱 / 页眉）
_NOT_TITLE_RE = re.compile(
    r"@|https?://|^\s*\{|arxiv:|doi:|"
    r"^(abstract|摘要|introduction|引言|keywords|关键词|references|参考文献)\b|"
    r"(university|institute|laboratory|google|microsoft|openai|facebook|deepmind)\b",
    re.I,
)


def is_placeholder_title(title: Optional[str]) -> bool:
    """当前标题是不是**占位值**（可以安全覆盖）。"""
    text = (title or "").strip()
    if not text:
        return True
    return text.lower() in PLACEHOLDER_TITLES


def is_placeholder_abstract(abstract: Optional[str]) -> bool:
    """当前摘要是不是**占位值**（可以安全覆盖）。"""
    text = (abstract or "").strip()
    if not text:
        return True
    if text.startswith(PLACEHOLDER_ABSTRACT_PREFIX):
        return True
    # 纯链接也算占位（旧数据里出现过摘要就是一串地址）
    return bool(re.fullmatch(r"https?://\S+", text))


def is_placeholder_identity(*, title: Optional[str], abstract: Optional[str]) -> bool:
    """标题或摘要是占位 → 身份待回填。"""
    return is_placeholder_title(title) or is_placeholder_abstract(abstract)


def title_from_blocks(blocks: Iterable[Any]) -> Optional[str]:
    """从**第一页的块**里取标题：第一个像标题的正文块。

    判据（确定性，不猜）：
    - 只取 ``kind == "paragraph"``（``heading`` 可能是 "Abstract"）；
    - 长度落在 ``[MIN_TITLE_CHARS, MAX_TITLE_CHARS]``；
    - 不匹配作者/机构/邮箱/页眉模式（``_NOT_TITLE_RE``）。

    全部不满足 → ``None``（宁缺勿造：这个 PDF 大概率没有独立标题行）。
    """
    ordered = sorted(
        (b for b in (blocks or [])),
        key=lambda b: int(getattr(b, "ordinal", 0) or 0),
    )
    for block in ordered:
        if (getattr(block, "kind", "") or "") != "paragraph":
            continue
        text = " ".join((getattr(block, "text", "") or "").split())
        if not (MIN_TITLE_CHARS <= len(text) <= MAX_TITLE_CHARS):
            continue
        if _NOT_TITLE_RE.search(text):
            continue
        return text
    return None


def _summary_text(section: Any) -> str:
    summary = getattr(section, "summary", None)
    if summary is None:
        return ""
    if isinstance(summary, str):
        return summary.strip()
    return (getattr(summary, "text", "") or "").strip()


def abstract_from_sections(sections: Sequence[Any]) -> Optional[str]:
    """从章节里取摘要：``heading`` 命中 ``abstract`` / ``摘要`` 的那一节正文。

    正文为空 → ``None``（不拿标题或相邻内容顶替）。
    """
    for section in (sections or []):
        heading = (getattr(section, "heading", "") or "").strip()
        # 用 lower() 做大小写无关匹配；中文"摘要"直接比
        if heading.lower().startswith(("abstract", "摘要")):
            body = _summary_text(section)
            if body:
                return body[:MAX_ABSTRACT_CHARS]
    return None


def plan_identity_backfill(
    *,
    current_title: Optional[str],
    current_abstract: Optional[str],
    parsed_title: Optional[str],
    parsed_abstract: Optional[str],
) -> dict:
    """算出**需要更新哪些字段**；返回空 dict 表示什么都不用动。

    这是整个回填的**唯一决策点**，与"I/O 怎么写"分开，便于单测。
    """
    plan: dict = {}
    if parsed_title and is_placeholder_title(current_title):
        plan["title"] = parsed_title
    if parsed_abstract and is_placeholder_abstract(current_abstract):
        plan["abstract"] = parsed_abstract
    return plan


def backfill_identity(scope) -> dict:
    """读解析产物 → 算出回填计划 → 写回 paper 行。返回实际更新的字段。

    失败不得影响主流程（解析已成功，身份只是展示信息），因此整体 try/except 并只记日志。
    """
    try:
        parsed_title, parsed_abstract = _read_parsed_identity(scope)
        if parsed_title is None and parsed_abstract is None:
            return {}
        from app.core.db import session_scope
        from app.models.models import Paper

        with session_scope() as db:
            paper = db.get(Paper, scope.paper_id)
            if paper is None:
                return {}
            plan = plan_identity_backfill(
                current_title=paper.title,
                current_abstract=getattr(paper, "abstract", "") or "",
                parsed_title=parsed_title,
                parsed_abstract=parsed_abstract,
            )
            if not plan:
                return {}
            for key, value in plan.items():
                setattr(paper, key, value)
            db.commit()
            log.info(
                "论文身份回填：paper=%s fields=%s title=%r",
                scope.paper_id, sorted(plan), (plan.get("title") or "")[:60],
            )
            return plan
    except Exception as exc:  # noqa: BLE001  展示信息回填失败不得影响主流程
        log.info("论文身份回填跳过（%s）：%s", scope.paper_id, exc)
        return {}


def _read_parsed_identity(scope):
    """从库里读解析产物：标题取第一页第一个正文块；摘要取 Abstract 段落正文。"""
    from sqlalchemy import select

    from app.core.db import session_scope
    from app.models.artifacts import BlockORM, PageORM

    parsed_title = None
    parsed_abstract = None
    with session_scope() as db:
        first_page = db.execute(
            select(PageORM)
            .where(PageORM.revision_id == scope.revision_id)
            .order_by(PageORM.pdf_page_index.asc())
            .limit(1)
        ).scalars().first()
        if first_page is not None:
            rows = db.execute(
                select(BlockORM.ordinal, BlockORM.kind, BlockORM.text)
                .where(
                    BlockORM.revision_id == scope.revision_id,
                    BlockORM.page_id == first_page.id,
                )
                .order_by(BlockORM.ordinal.asc())
                .limit(30)
            ).all()
            from types import SimpleNamespace

            parsed_title = title_from_blocks([
                SimpleNamespace(ordinal=r[0], kind=r[1], text=r[2]) for r in rows
            ])

    # 摘要走 structure 产物（章节正文由"已验证断言拼接"而来，是既有的口径）。
    # 读取入口与 `papers/legacy.py` 一致：`claims.get_structure(scope)`。
    try:
        from app.modules import claims as claims_mod

        structure = claims_mod.get_structure(scope)
        if structure is not None:
            parsed_abstract = abstract_from_sections(
                list(getattr(structure, "sections", []) or [])
            )
    except Exception as exc:  # noqa: BLE001  结构产物不可读时不回填摘要
        log.info("读取 structure 失败，跳过摘要回填：%s", exc)
    return parsed_title, parsed_abstract


__all__ = [
    "MAX_ABSTRACT_CHARS",
    "PLACEHOLDER_ABSTRACT_PREFIX",
    "PLACEHOLDER_TITLES",
    "abstract_from_sections",
    "backfill_identity",
    "is_placeholder_abstract",
    "is_placeholder_identity",
    "is_placeholder_title",
    "plan_identity_backfill",
    "title_from_blocks",
]
