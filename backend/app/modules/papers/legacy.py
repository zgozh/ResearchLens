"""M01/M13 — 旧论文详情兼容投影（REFACTOR_SPEC §5.11）。

``api/routes.py`` 的 ``GET /papers/{paper_id}`` 仍返回旧 ``PaperDetail``
形状（sections / figures / tables / method_steps / pages）。此前该路由**直接读
legacy ORM**（``p.figures`` / ``p.tables`` / ``p.sections`` / ``p.pages`` /
``p.method_steps``），而那些表只被 **demo seed** 填充：

- demo/synthetic 论文：有内容；
- **真实论文：全空** —— 即使 canonical 里已有 17 张 media、17 条 statements、
  7 个 section。前端「原图 / 原表 / 章节 / 方法步骤 / 原文页」几处因此空白。

``schemas/adapters.to_legacy_detail`` 早已实现该投影，但**零调用**。
本模块补齐数据装配：canonical 优先，无 canonical 数据时返回 ``None``，
由路由回退到旧表读取（保住 demo 论文的行为）。

纪律：不编造。没有 anchor 的 media 页码记 0；没有 canonical 数据的论文
一律返回 ``None`` 交给旧路径，绝不返回半真半假的结构。
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.contracts.common import Scope


# =============================================================== 路线 A：canonical → 旧 DTO
#
# 为什么需要这些函数（ADR-0027）：``/api/papers/{id}`` 仍返回旧 ``PaperDetail``，
# 其中 map_summary/abstract/authors 取自 **legacy ``papers`` 表列**，而真实论文
# 这些列是空的（实测 map_summary={}、abstract 长度 0、authors=[]）→ 地图页六维卡片
# 全渲染成 "—"、摘要与作者行全空；figures 也只给空 ``image_b64``/``glyph_svg``
# （图其实在 canonical 的 asset 里）→ "有摘要没图"。
# 这里把 canonical 产物补进旧 DTO；**没有来源就不给键**，绝不编造。

#: 摘要起止标记（中英双语论文都要支持）。
#: 起始标记**必须带冒号**：否则正文里的普通词（"没有任何摘要标记"）会被误判成摘要头。
_ABSTRACT_START_RE = re.compile(r"(?:摘\s*要|abstract)\s*[:：]", re.I)
_ABSTRACT_END_RE = re.compile(
    r"(?:关\s*键\s*词|key\s*words?|中图法分类号|中图分类号|CCS\s*Concepts)\s*[:：]?", re.I
)


def map_summary_from_structure(structure: Any, sections: Any) -> Dict[str, str]:
    """canonical 结构 → 旧 ``map_summary``（MapView 的六维卡片）。

    - ``problem/method/result/limitation`` 取自 ``structure.map.items``（已验证内容）；
    - ``experiment``/``dataset`` 在 canonical map 里没有对应 kind，用**章节**兜底
      （kind=experiment 的章节摘要 / 标题含"数据"的章节摘要）；
    - 没有来源的键**不出现**——前端自然显示 "—"，而不是被占位文本充数。
    """
    out: Dict[str, str] = {}
    items = list(getattr(getattr(structure, "map", None), "items", None) or [])
    for item in items:
        kind = (getattr(item, "kind", "") or "").strip()
        text = _text(getattr(item, "text", None)).strip()
        if kind and text and kind not in out:
            out[kind] = text

    secs = list(sections or [])
    if "experiment" not in out:
        for s in secs:
            if (getattr(s, "kind", "") or "").lower() == "experiment":
                text = _text(getattr(s, "summary", None)).strip()
                if text:
                    out["experiment"] = text
                    break
    if "dataset" not in out:
        for s in secs:
            heading = (getattr(s, "heading", "") or "")
            if "数据" in heading or "dataset" in heading.lower():
                text = _text(getattr(s, "summary", None)).strip()
                if text:
                    out["dataset"] = text
                    break
    return out


def abstract_from_page_text(text: str, *, limit: int = 1200) -> str:
    """从首页正文切出摘要；**没有可识别标记就返回空串**（宁缺勿造，不把整页当摘要）。"""
    raw = text or ""
    start = _ABSTRACT_START_RE.search(raw)
    if not start:
        return ""
    tail = raw[start.end():]
    end = _ABSTRACT_END_RE.search(tail)
    body = (tail[: end.start()] if end else tail).strip()
    return re.sub(r"\s+", " ", body)[:limit]


#: markdown/LaTeX **转义符**：解析器会把 `*` `_` `#` 等转义成 `\*` `\_` `\#`，
#: 直接渲染就是"一堆没转义的字符"。只解转义，**不碰 `$...$`**（前端 KaTeX 要它）。
_MARKDOWN_ESCAPE_RE = re.compile(r"\\([*_#`\[\]()~>+\-.!])")


def clean_text_markup(text: Any) -> str:
    """清掉解析器留下的 markdown 转义与 NBSP；``$...$`` 公式**原样保留**。

    策略分两种（实测中文期刊 PDF 的表现）：
    - ``\\*`` **整段去掉**：它几乎总是标题/术语上的强调或脚注星号（如
      "…的 JPEG 隐写\\*"），留成 ``*`` 反而像乱码；
    - 其余转义 ``\\_ \\# \\&`` 等**解转义**（下划线在 ``W_{u,v}`` 这类标识里是有义的）。
    """
    raw = text if isinstance(text, str) else ("" if text is None else str(text))
    if not raw:
        return ""
    out = raw.replace("\\*", "")
    out = _MARKDOWN_ESCAPE_RE.sub(r"\1", out).replace("\u00a0", " ")
    return re.sub(r"[ \t]{2,}", " ", out).strip()


# --------------------------------------------------------------- 首页元信息派生
# 真实论文实测：``papers.authors/tags/year/domain`` 对 3 篇真实论文分别是
# ``[] / [] / 2026(入库年份) / 'general'`` —— 全是空壳。而这些信息**首页正文里本来就有**
# （中文期刊首页第 2 行是作者行，摘要下方是"关键词"行，页脚是年份与卷期）。
# 这里只做**保守派生**：认不出来就不给键，调用方保留原值。

#: 命中即否决整行（页眉/摘要/关键词/通讯作者/编号）
_FRONT_LINE_REJECT_RE = re.compile(
    r"摘要|摘\s*要|Abstract|关键词|Key\s*words?|通讯作者|Vol\.|No\.|ISSN|DOI|http|@|"
    r"软件学报|Journal|University|College|Institute|Laboratory",
    re.I,
)
#: 作者名后的上标标记：``$^{1}$`` / ``$^{1,2}$`` / ``${}^{a}$``
_AUTHOR_SUPERSCRIPT_RE = re.compile(r"\$?\s*[\^_]\s*\{[^{}]*\}\s*\$?|\$[^$]{0,24}\$")
_AUTHOR_SPLIT_RE = re.compile(r"[,，、;；]")
#: 姓名：≤24 字符，只允许汉字/字母/常见连字符，且以汉字或字母开头
_AUTHOR_NAME_RE = re.compile(r"^[\u4e00-\u9fffA-Za-z][\u4e00-\u9fffA-Za-z.\-' ]{0,23}$")
#: 单位行标志：括号或数字
_AFFILIATION_RE = re.compile(r"[()（）\[\]{}]|\d")

_KEYWORDS_RE = re.compile(
    r"^[ \t]*(?:关\s*键\s*词|Key\s*words?)\s*[:：]?[ \t]*(.+)$", re.I | re.M
)
_KEYWORD_SPLIT_RE = re.compile(r"[;；,，、]")
_YEAR_RE = re.compile(r"\b(19[89]\d|20[0-4]\d)\b")

#: 领域关键词表（按优先级，先命中先返回）。
#: 注意：**具体领域必须排在笼统领域之前**——Solidity 那篇的摘要里有"智能合约安全问题"，
#: 若 "security" 排在前面就会把区块链论文判成安全论文。同理不收录裸 "安全"，
#: 它太泛（几乎每篇系统论文都会出现"安全性"）。
_DOMAIN_KEYWORDS: tuple = (
    ("blockchain", ("智能合约", "solidity", "区块链", "blockchain", "以太坊", "合约")),
    ("security", (
        "隐写", "隐写分析", "steganalysis", "steganograph", "watermark", "水印",
        "漏洞", "加密", "密码", "隐私", "入侵检测", "恶意代码", "信息安全", "网络安全",
    )),
    ("software-engineering", (
        "软件工程", "缺陷预测", "软件度量", "代码", "重构", "软件测试", "需求",
        "应用市场", "用户接受", "开发", "app market", "defect prediction",
    )),
    ("machine-learning", (
        "神经网络", "深度学习", "机器学习", "模型", "预测", "分类", "表征学习",
        "neural", "learning", "prediction",
    )),
    ("systems", ("分布式", "操作系统", "编译", "运行时", "存储", "网络", "数据库", "调度")),
)


def authors_from_page_text(text: str, *, title: str = "", max_lines: int = 4) -> List[str]:
    """从首页正文抽取作者行；**认不出来就返回空列表**。

    首页第一个非空行是题名（跳过），作者行紧随其后。判定"整行都是姓名"的
    充要条件：按 ``, ，、;`` 切分后**每个**片段都像姓名（≤24 字符、只含汉字/字母/
    连字符、不含数字与括号）。任何一段像单位/页眉，整行否决——
    把"厦门大学"当作者比返回空列表更糟。
    """
    lines = [ln.strip() for ln in (text or "").splitlines()]
    title_line = (title or "").strip()
    seen_first_content = False
    checked = 0
    for line in lines:
        if not line:
            continue
        if not seen_first_content:
            seen_first_content = True  # 首页第一个非空行 = 题名（或英文题名），跳过
            continue
        if line == title_line:
            continue
        checked += 1
        if checked > max_lines:
            break
        if _FRONT_LINE_REJECT_RE.search(line):
            continue
        stripped = _AUTHOR_SUPERSCRIPT_RE.sub(" ", line).strip()
        if not stripped or _AFFILIATION_RE.search(stripped):
            continue
        tokens = [t.strip() for t in _AUTHOR_SPLIT_RE.split(stripped) if t.strip()]
        if not tokens:
            continue
        if all(_AUTHOR_NAME_RE.match(t) for t in tokens):
            return tokens
    return []


def keywords_from_page_text(text: str, *, limit: int = 8) -> List[str]:
    """从首页"关键词 / Key words"行抽取标签；没有该行就返回空列表。"""
    match = _KEYWORDS_RE.search(text or "")
    if not match:
        return []
    raw = match.group(1).strip()
    # 关键词行后面常紧跟"中图法分类号"等同段内容，按首个强分隔符截断
    raw = re.split(r"中图法|中图分类|CLC|DOI|收稿", raw)[0]
    out: List[str] = []
    for token in _KEYWORD_SPLIT_RE.split(raw):
        tag = token.strip().strip(".。")
        if not tag or len(tag) > 40:
            continue
        if tag not in out:
            out.append(tag)
        if len(out) >= limit:
            break
    return out


def year_from_page_text(text: str) -> Optional[int]:
    """首页出现次数最多的年份（页脚卷期/版权会重复出现）；没有则 ``None``。"""
    years = _YEAR_RE.findall(text or "")
    if not years:
        return None
    counts: Dict[str, int] = {}
    for year in years:
        counts[year] = counts.get(year, 0) + 1
    # 次数相同取更晚的年份（引用年份通常早于发表年）
    best = sorted(counts.items(), key=lambda kv: (-kv[1], -int(kv[0])))[0][0]
    return int(best)


def domain_from_page_text(text: str) -> str:
    """按关键词表判定领域；判不出来返回 ``'general'``（不猜）。"""
    haystack = (text or "").lower()
    for domain, needles in _DOMAIN_KEYWORDS:
        if any(n.lower() in haystack for n in needles):
            return domain
    return "general"


def front_matter_from_page_text(text: str, *, title: str = "") -> Dict[str, Any]:
    """首页 → ``{authors?, tags?, year?, domain?}``。

    **派生不到的键一律不出现**，调用方据此决定是否覆盖 legacy 默认值
    （例如 ``domain`` 只有真的判出来才覆盖 ``'general'``）。
    """
    bundle: Dict[str, Any] = {}
    authors = authors_from_page_text(text, title=title)
    if authors:
        bundle["authors"] = authors
    tags = keywords_from_page_text(text)
    if tags:
        bundle["tags"] = tags
    year = year_from_page_text(text)
    if year:
        bundle["year"] = year
    domain = domain_from_page_text(f"{title}\n{text}")
    if domain and domain != "general":
        bundle["domain"] = domain
    return bundle


def merge_front_matter(existing: Dict[str, Any], front: Dict[str, Any]) -> Dict[str, Any]:
    """首页派生值 → 允许覆盖 legacy 字段的子集。

    覆盖策略（保守优先，宁可少改）：
    - ``authors`` / ``tags``：只在 legacy **为空**时补（已有的真实值更可信）；
    - ``year``：派生到就覆盖——legacy 的 ``year`` 是**入库年份**（实测 3 篇真实论文
      全是 2026），不是发表年份，留着比没有更误导；
    - ``domain``：派生到就覆盖——legacy 恒为 ``'general'``（等于没判）。
    """
    updates: Dict[str, Any] = {}
    if front.get("authors") and not (existing.get("authors") or []):
        updates["authors"] = front["authors"]
    if front.get("tags") and not (existing.get("tags") or []):
        updates["tags"] = front["tags"]
    if front.get("year"):
        updates["year"] = front["year"]
    if front.get("domain"):
        updates["domain"] = front["domain"]
    return updates


def section_body_and_pages(section: Any, blocks: Any, page_no_by_id: Dict[str, int]):
    """章节 → ``(正文, 起始页, 结束页)``。

    - **正文**取该节 ``source_block_ids`` 覆盖的原文块文本；此前直接复用 ``summary``，
      于是"章节正文"与"章节摘要"是同一段断言拼接，读者看不到真正的正文。
    - **页码**取这些块所在物理页的最小/最大，供前端"阅读该章节正文"跳转；
      此前恒为 ``1``，所以永远跳到第 1 页。
    - 没有块/没有页码映射时分别返回空串与 ``0``（**不猜**）。
    """
    wanted = {b for b in (getattr(section, "source_block_ids", None) or []) if b}
    texts: List[str] = []
    pages: List[int] = []
    for block in (blocks or []):
        if wanted and getattr(block, "id", None) not in wanted:
            continue
        text = (getattr(block, "text", "") or "").strip()
        if text:
            texts.append(text)
        page_no = (page_no_by_id or {}).get(getattr(block, "page_id", "") or "")
        if isinstance(page_no, int) and page_no > 0:
            pages.append(page_no)
    body = "\n".join(texts)
    return body, (min(pages) if pages else 0), (max(pages) if pages else 0)


def method_step_extras(
    step: Any, media_legacy_no: Dict[str, Any], statement_media: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """方法步骤 → 旧 DTO 的 ``text`` / ``figure_refs`` / ``table_refs``。

    - ``text``：canonical ``label`` 就是该步骤的**原文陈述**。前端 ``MethodView`` 在
      ``st.text`` 存在时走 ``RichText``（把"图 N/表 N"渲染成**可点击引用**）。
    - ``figure_refs`` / ``table_refs``：**该步骤自己的**图表编号（可能有多个），来源优先级：
      ① 该步骤断言的 ``statement→media`` 绑定（由 caption↔陈述词面重合建立，相关性最好）；
      ② 步骤自带的 ``media_ids``。
    ③ **绝不回退到"全篇第一张图"**：用户实测 5 个步骤都指向同一张 ``(a) 原图`` 子图面板，
      就是因为缺 binds 时前端落回 ``detail.figures[0]``（ADR-0048）。
    - 没有来源就不给键（前端据此不显示对应 UI），不编造编号。
    """
    out: Dict[str, Any] = {}
    label = _text(getattr(step, "label", None)).strip()
    if label:
        out["text"] = label

    figure_refs: List[int] = []
    table_refs: List[int] = []

    def _collect(media_ids) -> None:
        for media_id in media_ids or []:
            legacy_no = (media_legacy_no or {}).get(media_id)
            if not isinstance(legacy_no, int):
                continue
            kind = _media_kind_of(media_id, statement_media)
            if kind == "table":
                if legacy_no not in table_refs:
                    table_refs.append(legacy_no)
            elif kind == "figure":
                if legacy_no not in figure_refs:
                    figure_refs.append(legacy_no)

    # ① 该步骤断言的 statement→media 绑定
    # ``MethodStepRecord`` 只有 ``claim_ids``（没有 statement_id），所以这里按
    # statement_id **与** claim_id 双向查（调用方把同一份绑定同时挂到两个键上）。
    keys: List[str] = []
    statement_id = getattr(step, "statement_id", None)
    if statement_id:
        keys.append(str(statement_id))
    keys.extend(str(c) for c in (getattr(step, "claim_ids", None) or []))
    for key in keys:
        bound = (statement_media or {}).get(key, [])
        _collect([mid for mid, _kind in bound])
    # ② 步骤自带 media_ids（绑定缺失时的补充）
    _collect(getattr(step, "media_ids", None))

    if figure_refs:
        out["figure_refs"] = figure_refs
        out["figure_ref"] = figure_refs[0]      # 兼容旧字段
    if table_refs:
        out["table_refs"] = table_refs
    return out


def _media_kind_of(media_id: str, statement_media: Optional[Dict[str, Any]]) -> str:
    """从 ``statement→media`` 绑定里取该媒体的 kind；找不到返回 ``figure``（保守）。"""
    for entries in (statement_media or {}).values():
        for mid, kind in entries:
            if mid == media_id:
                return str(kind or "")
    return "figure"


def figure_image_url(media: Any) -> str:
    """媒体 → 可访问的图片 URL（第一个真实图资产）；**无资产则空串**。

    绝不回退到 ``raw_asset_id``：那是 ``parser_raw`` 的 JSON，前端会把它当图渲染
    （D-24 已把真图落成 ``kind="crop"`` 的 asset，这里只认它）。
    """
    asset_ids = [a for a in (getattr(media, "original_asset_ids", None) or []) if a]
    if not asset_ids:
        return ""
    try:
        from app.modules.papers import service as papers_service

        return papers_service.asset_url(asset_ids[0])
    except Exception:  # noqa: BLE001 - URL 拼装失败不得让详情 500
        return ""


def get_detail(db: Session, paper_id: int) -> Optional[Any]:
    """canonical 优先的旧详情投影；无 canonical 数据返回 ``None``。"""
    revision_id = _readable_revision(db, paper_id)
    if not revision_id:
        return None
    scope = Scope(paper_id=paper_id, revision_id=revision_id)

    # 惰性导入：papers ← parse/visual/claims 存在反向依赖，模块级导入会成环。
    from app.modules import claims as claims_mod
    from app.modules import parse as parse_mod
    from app.modules import papers as papers_mod
    from app.modules import visual as visual_mod
    from app.schemas.adapters import _legacy_step, to_legacy_detail

    try:
        structure = claims_mod.get_structure(scope)
    except Exception:  # noqa: BLE001 - 兼容层不得把异常泄漏成 500
        structure = None
    try:
        media_items = list(visual_mod.list_media(scope, limit=500).items)
    except Exception:  # noqa: BLE001
        media_items = []
    try:
        page_items = list(parse_mod.get_pages(scope, limit=500).items)
    except Exception:  # noqa: BLE001
        page_items = []

    sections = list(getattr(structure, "sections", None) or [])
    steps = list(getattr(structure, "method_steps", None) or [])
    if not (sections or media_items or page_items or steps):
        # 没有 canonical 产物：交给旧表路径（demo 论文）
        return None

    page_of_media = _media_pages(scope)

    figures: List[Dict[str, Any]] = []
    tables: List[Dict[str, Any]] = []
    for m in media_items:
        if m.kind == "figure":
            figures.append({
                "fig_no": m.legacy_no or (len(figures) + 1),
                "caption": clean_text_markup(m.caption or ""),
                "page": page_of_media.get(m.id, 0),
                "glyph_svg": "",
                "image_b64": "",
                "image_mime": "image/png",
                # 真实图资产的可访问 URL（D-24 落库的 crop asset）。
                # 前端 FigureImage 优先用它；此前只给空 b64/svg → "有摘要没图"。
                "image_url": figure_image_url(m),
                "importance": "medium",
                "description": "",
                # 前端用 media_id 打开真实原件（M03 的 policy 决定展示什么）
                "media_id": m.id,
            })
        elif m.kind == "table":
            extracted = m.extracted
            tables.append({
                "table_no": m.legacy_no or (len(tables) + 1),
                "caption": clean_text_markup(m.caption or ""),
                "page": page_of_media.get(m.id, 0),
                "content": [],
                "table_html": (getattr(extracted, "table_html", "") or ""),
                "key_finding": "",
                "media_id": m.id,
            })

    page_no_by_id = {
        getattr(p, "id", ""): int(getattr(p, "pdf_page_no", 0) or 0) for p in page_items
    }
    section_dicts: List[Dict[str, Any]] = []
    for s in sections:
        ids = [b for b in (getattr(s, "source_block_ids", None) or []) if b]
        try:
            blocks = parse_mod.get_blocks(scope, ids) if ids else []
        except Exception:  # noqa: BLE001 - 兼容层不得因取块失败而 500
            blocks = []
        body, page_start, page_end = section_body_and_pages(s, blocks, page_no_by_id)
        section_dicts.append({
            "heading": s.heading or "",
            "kind": s.kind or "body",
            # 兼容字段：前端章节在 badge 里显示它，并据此跳转
            "page": page_start or 1,
            "page_start": page_start,
            "page_end": page_end,
            "summary": clean_text_markup(_text(s.summary)),
            # 真实正文（该节 source_block_ids 覆盖的原文块）。
            # 没有块可取时退回 summary：那是**已验证断言拼接**，不是编造，
            # 且空正文会让章节看起来坏掉。
            "body": clean_text_markup(body) or clean_text_markup(_text(s.summary)),
            "key_points": [_text(k) for k in (s.key_points or [])],
        })
    page_dicts = [
        {"page_no": int(getattr(p, "pdf_page_no", 0) or 0), "text": _page_text(scope, p)}
        for p in page_items
    ]

    paper = papers_mod.get_paper(paper_id)
    metadata = papers_mod.get_metadata(paper_id)
    revision = papers_mod.get_revision(scope)

    detail = to_legacy_detail(
        paper, metadata, revision,
        sections=section_dicts, figures=figures, tables=tables, pages=page_dicts,
    )

    # 路线 A（ADR-0027）：legacy ``papers`` 表里这几列对真实论文是空的，
    # 用 canonical 产物补上——否则地图页六维卡片全是 "—"、摘要/作者行全空。
    derived: Dict[str, Any] = {}
    derived_map = map_summary_from_structure(structure, sections)
    if derived_map:
        derived["map_summary"] = derived_map
    if not (detail.abstract or "").strip() and page_dicts:
        derived_abstract = abstract_from_page_text(page_dicts[0].get("text") or "")
        if derived_abstract:
            derived["abstract"] = derived_abstract
    # 署名/关键词/年份/领域：legacy ``papers`` 列对真实论文恒为空壳
    # （``[]`` / ``[]`` / 入库年份 / ``'general'``），从首页正文保守派生。
    front = front_matter_from_page_text(
        page_dicts[0].get("text") if page_dicts else "",
        title=getattr(detail, "title", "") or "",
    )
    derived.update(merge_front_matter(
        {
            "authors": getattr(detail, "authors", None),
            "tags": getattr(detail, "tags", None),
            "year": getattr(detail, "year", None),
            "domain": getattr(detail, "domain", None),
        },
        front,
    ))
    if derived:
        detail = detail.model_copy(update=derived)

    # method_steps：真实论文的旧 ``papers.method_steps`` 列为空（canonical 把
    # 步骤写进 section_records/method_steps 产物），故用 canonical 结构覆盖。
    if steps:
        media_legacy_no = {m.id: m.legacy_no for m in media_items}
        # statement → [(media_id, kind)]：方法步骤的图表引用必须按**该步骤自己的**
        # 证据取（ADR-0048）。绑定由 ``bind_media_for_statements`` 依 caption↔陈述
        # 词面重合建立，所以相关性直接对应"这张图的题注在讲这件事"。
        statement_media: Dict[str, List[Any]] = {}
        media_kind = {m.id: (getattr(m, "kind", "") or "") for m in media_items}
        try:
            from app.modules.claims import repository as claims_repo
            from app.modules.evidence import repository as evidence_repo

            claim_of_statement: Dict[str, str] = {}
            with _session() as bdb:
                for row in claims_repo.list_claim_rows(bdb, revision_id):
                    if row.statement_id:
                        claim_of_statement[row.statement_id] = row.claim_id
                for row in evidence_repo.list_binding_rows(bdb, revision_id):
                    if (row.from_kind or "") != "statement" or (row.to_kind or "") != "media":
                        continue
                    entry = (row.to_id, media_kind.get(row.to_id, "figure"))
                    # 同时挂到 statement_id 与 claim_id：方法步骤只带 claim_ids
                    statement_media.setdefault(row.from_id, []).append(entry)
                    claim_id = claim_of_statement.get(row.from_id)
                    if claim_id:
                        statement_media.setdefault(claim_id, []).append(entry)
        except Exception:  # noqa: BLE001 - 绑定不可读不得让详情 500（只是少图表引用）
            statement_media = {}
        detail = detail.model_copy(update={
            "method_steps": [
                _legacy_step(
                    {
                        "id": st.id,
                        "label": _text(st.label),
                        "detail": _text(st.detail),
                        "phase": st.phase,
                        # text/figure_refs/table_refs：前端"方法动画"的 RichText
                        # 与"查看关联图/表"（每个步骤各自的图表）
                        **method_step_extras(st, media_legacy_no, statement_media),
                    },
                    i,
                )
                for i, st in enumerate(steps)
            ]
        })
    return detail


def _text(value: Any) -> str:
    """``ArtifactText | str | None`` → 纯文本。"""
    if value is None:
        return ""
    text = getattr(value, "text", None)
    if isinstance(text, str):
        return text
    return value if isinstance(value, str) else ""


def _page_text(scope: Scope, page: Any) -> str:
    """旧详情只给页级正文预览（截断由契约方决定，这里限量避免超大响应）。

    先清 markdown 转义再截断，避免截出半个转义符。
    """
    text = getattr(page, "text", None)
    if isinstance(text, str):
        return clean_text_markup(text)[:4000]
    return ""


def _media_pages(scope: Scope) -> Dict[str, int]:
    """media_id → 物理页码（1-based）；无 anchor 的不出现（调用方记 0）。"""
    from app.models.artifacts import AnchorORM, MediaORM

    out: Dict[str, int] = {}
    with _session() as db:
        rows = db.execute(
            select(MediaORM.id, MediaORM.anchor_ids).where(
                MediaORM.revision_id == scope.revision_id
            )
        ).all()
        anchor_ids = sorted({a for _mid, ids in rows for a in (ids or [])})
        if not anchor_ids:
            return {}
        anchors = db.execute(
            select(AnchorORM.id, AnchorORM.segments).where(AnchorORM.id.in_(anchor_ids))
        ).all()
        page_of_anchor: Dict[str, int] = {}
        for aid, segments in anchors:
            for seg in (segments or []):
                idx = seg.get("pdf_page_index")
                if idx is not None:
                    page_of_anchor[aid] = int(idx) + 1
                    break
        for mid, ids in rows:
            for aid in (ids or []):
                if aid in page_of_anchor:
                    out[mid] = page_of_anchor[aid]
                    break
    return out


def _session():
    from app.core.db import session_scope

    return session_scope()


def _readable_revision(db: Session, paper_id: int) -> Optional[str]:
    """解析该论文当前可读 revision（只读）。与其它 legacy 桥接保持一致。"""
    from app.models.models import Paper

    row = db.get(Paper, paper_id)
    if row is None:
        return None
    if row.readable_revision_id:
        return row.readable_revision_id
    from app.models.source import RevisionORM

    stmt = (
        select(RevisionORM.id)
        .where(RevisionORM.paper_id == paper_id)
        .order_by(RevisionORM.created_at.desc())
        .limit(1)
    )
    found = db.execute(stmt).first()
    return found[0] if found else None


__all__ = ["get_detail"]
