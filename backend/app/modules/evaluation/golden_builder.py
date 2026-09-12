"""Golden Set 的**非循环**构造（ADR-0046）。

问题：``golden_sets`` 表 0 行 → ``overall_score`` 的 4 个核心指标里
``support_precision`` / ``unanswerable_refusal_rate`` 永远算不出来，
``overall_score_available=false``（前端只能诚实显示"未评测"）。

**为什么不能随手让模型生成 golden**：那等于让模型给自己出卷子——
precision/recall 会变成自我确认，指标失去意义。本模块的纪律是
**真值只能来自原文本身**：

- ``GoldenClaim``：文本是**从原文块逐字复制的句子**，``acceptable_block_ids`` 就是它所在的块。
  于是 precision/recall 衡量的是"抽取是否覆盖了原文中真实存在的句子"，
  真值由 parser 产出，与模型判定无关。
- ``GoldenAnchor``：``expected_page_index`` 取自块所在的物理页（parser 事实），
  不是模型自报。
- ``GoldenQuestion``：可答题由**章节标题**模板化成"这一部分讲了什么"；
  **不可答题要求所用术语经程序检查在全文任何块中都不出现**——"不可答"是被**验证**的，
  不是猜的。
"""
from __future__ import annotations

import re
from typing import List, Optional, Sequence, Tuple

from pydantic import BaseModel, Field

from app.contracts.common import Scope
from app.contracts.evaluation import GoldenAnchor, GoldenClaim, GoldenQuestion, GoldenSet
from app.core.db import session_scope

#: 构造规则版本：取句/过滤规则一变必须 bump（`(golden_id, version)` 决定覆盖写哪个集合）
#: ``/2``：按章节排除参考文献/致谢 + 文献条目形态兜底；
#: ``/3``：块内取**最像断言的句子**而不是首句（ADR-0056）
GOLDEN_VERSION = "rl.golden/3"

#: 不可答题的候选术语。**不硬编码"哪些论文没有它"**——运行时逐个检查是否真的不在全文里，
#: 通过检查才用（"不可答"必须被验证，不能是猜测）。
#: 池子要足够大：实测 paper 3 是区块链论文，"区块链""知识图谱"都在全文里，
#: 候选太少会导致该篇构造不出不可答题、拒答率没有分母。
_UNANSWERABLE_TERMS = (
    "Kubernetes", "Transformer", "联邦学习", "量子计算", "区块链", "GPU 训练时长",
    "知识图谱", "数字孪生", "强化学习", "卷积神经网络", "边缘计算", "同态加密",
    "ImageNet", "CIFAR", "BERT", "LSTM", "图神经网络", "差分隐私", "零知识证明",
    "容器编排", "微服务", "自动驾驶", "蛋白质结构", "气象预报",
)

#: 可承载"原文事实句"的块类型与长度门槛
_SENTENCE_BLOCK_KINDS = ("paragraph", "abstract", "body")
_MIN_SENTENCE_CHARS = 30
_MAX_SENTENCE_CHARS = 160
_MAX_CLAIMS = 12
_MAX_QUESTIONS = 8

#: 首页杂项：邮箱/上标/单位/引用格式/参考文献——**不能当 golden claim**。
#: 实测教训：不排除这些时，paper 1 取到的 12 条全是题名/作者/单位/邮箱，
#: 与真实断言零重合（最高相似度 0.13），`support_precision` 直接算成 0——
#: 那是**构造器取句取错了**，不是产品指标不行。
_FRONT_MATTER_RE = re.compile(
    r"@|\$\s*\^|E-?mail|通讯作者|作者简介|http|www\.|References|参考文献|"
    r"中图法|ISSN|DOI|收稿|基金项目",
    re.I,
)
_AFFILIATION_HINT = ("大学", "学院", "研究所", "实验室", "University", "Institute",
                     "School", "Laboratory", "College")

#: **非正文**章节：整章都不能当参考断言（ADR-0056 实测）。为什么不能只靠句子里的
#: ``References`` 关键词：参考文献**条目本身**不含 "References" 字样，而是
#: ``[12] Lim SL, Bentley PJ, …`` 这种形态 —— 实测 paper 2 的 12 条参考断言里
#: 有 3 条是文献条目，AI 语义裁判因此判"0 命中"（分母脏，不是指标不行）。
_NON_BODY_SECTION_RE = re.compile(
    r"reference|bibliograph|works\s+cited|致谢|acknowledg|附录|appendix|"
    r"作者简介|基金项目|作者贡献",
    re.I,
)

#: 参考文献条目形态：以 ``[12]`` / ``［12］`` / ``12.`` 开头，且后面跟着作者式拉丁文
_BIB_ENTRY_RE = re.compile(r"^\s*[\[［]\s*\d{1,3}\s*[\]］]")
_BIB_AUTHOR_RE = re.compile(r"[A-Z][a-z]+\s+[A-Z]{1,3}\b")

#: "像断言"的信号：数字/百分比/结论性动词。用来在全文里挑**事实句**，
#: 让 golden 覆盖到断言真正出现的位置（方法/实验/结论），而不是首页杂项。
_CLAIM_SIGNAL_RE = re.compile(
    r"\d|%|表明|说明|提出|提高|降低|优于|相比|结果|结论|显著|平均|准确率|错误率|"
    r"性能|实验|方法|模型|指标",
    re.I,
)
#: 更强的"量化结论"信号：**有数字**或**有结论动词**。实测（ADR-0050）：
#: 只用泛化的 `_CLAIM_SIGNAL_RE` 取句时，paper 1 的 golden 与预测断言最高相似度仅
#: **0.21**（远低于阈值 0.42）——两批句子根本不是同一类内容：golden 取的是
#: "每块首个实质句"，而抽取产出的是**实验/结论句**。要让该指标有意义，golden 必须
#: 瞄准同一类内容：**原文里的量化结论句**（真值仍只来自原文，不是模型自证）。
_QUANT_SIGNAL_RE = re.compile(r"\d|%|提高|降低|优于|低于|达到|平均|显著|相比|提升", re.I)

#: 这些章节 kind 里出现"结论句"的概率最高，取句时加权。
_RESULT_SECTION_KINDS = ("method", "experiment", "result", "conclusion", "limitation")
#: 句子边界。**小数点不能当边界**（真实缺陷：``8.5%`` 被切成 ``8.`` 与 ``5%``，
#: 于是"最优句"取到半截数字、参考断言变成残句）。所以 ``.`` 只在后面跟空白/结尾时才算边界。
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[。；;!?！？])\s*|\.(?=\s|$)")


def _norm(text: str) -> str:
    return re.sub(r"\s+", "", text or "")


def _first_sentence(text: str) -> str:
    body = " ".join((text or "").split())
    if len(body) < _MIN_SENTENCE_CHARS:
        return ""
    for piece in _SENTENCE_SPLIT_RE.split(body):
        piece = piece.strip()
        if _MIN_SENTENCE_CHARS <= len(piece) <= _MAX_SENTENCE_CHARS:
            return piece
    return body[:_MAX_SENTENCE_CHARS] if len(body) >= _MIN_SENTENCE_CHARS else ""


def _candidate_sentences(text: str) -> List[str]:
    """块内所有可用长度的句子（用于挑**最优句**，而不是无脑拿首句）。"""
    body = " ".join((text or "").split())
    if len(body) < _MIN_SENTENCE_CHARS:
        return []
    out: List[str] = []
    for piece in _SENTENCE_SPLIT_RE.split(body):
        piece = piece.strip()
        if _MIN_SENTENCE_CHARS <= len(piece) <= _MAX_SENTENCE_CHARS:
            out.append(piece)
    if not out and len(body) >= _MIN_SENTENCE_CHARS:
        out.append(body[:_MAX_SENTENCE_CHARS])
    return out


def _best_sentence(text: str, section_kind: str) -> str:
    """块内**最像断言**的句子（量化结论优先）。

    为什么不能只取首句（实测，ADR-0056）：paper 2 的参考集全是"每块首句"——
    数据集规模、算法对比之类的铺垫句，而抽取产出的是**定义/量化断言**
    （评分趋势、下载比例、卸载率…），两批内容**根本不重合**，AI 语义裁判只能判 0 命中。
    模块自己的注释早就写着"要瞄准量化结论句"，实现却只拿首句；这里补上。
    仍**只从原文取句**，真值来源不变（不引入模型生成的内容）。
    """
    sentences = _candidate_sentences(text)
    if not sentences:
        return ""
    return max(sentences, key=lambda s: _sentence_score(s, section_kind))


def _load_blocks(scope: Scope) -> List[Tuple[str, str, int]]:
    """按文档顺序返回 ``(block_id, text, pdf_page_index)``。"""
    from sqlalchemy import select

    from app.models.artifacts import BlockORM, PageORM

    with session_scope() as db:
        rows = db.execute(
            select(BlockORM, PageORM.pdf_page_index, PageORM.id)
            .outerjoin(PageORM, PageORM.id == BlockORM.page_id)
            .where(BlockORM.revision_id == scope.revision_id)
            .order_by(PageORM.pdf_page_index.asc(), BlockORM.ordinal.asc())
        ).all()
        # **必须在 session 内投影成普通元组**：离开 session 后 ORM 实例会过期，
        # 再读 row.text 会 DetachedInstanceError（真实踩坑）。
        return [
            (row.id, row.text or "", int(page_index or 0))
            for row, page_index, _page_id in rows
        ]


def _block_kinds(scope: Scope) -> dict:
    """``block_id → kind``（在 session 内投影，避免 DetachedInstanceError）。"""
    from sqlalchemy import select

    from app.models.artifacts import BlockORM

    with session_scope() as db:
        return {
            row[0]: (row[1] or "")
            for row in db.execute(
                select(BlockORM.id, BlockORM.kind)
                .where(BlockORM.revision_id == scope.revision_id)
            ).all()
        }


def _section_headings(scope: Scope) -> List[str]:
    from app.modules import claims as claims_mod

    try:
        structure = claims_mod.get_structure(scope)
    except Exception:  # noqa: BLE001 - 结构不可用时退化为无标题
        return []
    return [
        (s.heading or "").strip()
        for s in (structure.sections or [])
        if (s.heading or "").strip()
    ]


def _is_front_matter(text: str, kind: str) -> bool:
    """首页杂项/非正文块：不能当 golden claim（否则 precision 会被算成 0）。"""
    body = (text or "").strip()
    if not body:
        return True
    if kind and kind not in _SENTENCE_BLOCK_KINDS and kind not in ("", "heading"):
        return True
    if kind == "heading":
        return True
    if _FRONT_MATTER_RE.search(body):
        return True
    # 参考文献条目形态（章节判不出来时的兜底）：``[12] Lim SL, …``
    if _BIB_ENTRY_RE.match(body) and _BIB_AUTHOR_RE.search(body[:120]):
        return True
    # 单位行：既是"某大学/学院/研究所"又带邮编数字
    if any(h in body for h in _AFFILIATION_HINT) and re.search(r"\d{5,6}", body):
        return True
    return False


def _is_non_body_section(heading: str) -> bool:
    """参考文献/致谢/附录等非正文章节：整章都不取句。"""
    return bool(_NON_BODY_SECTION_RE.search(heading or ""))


def _section_kind_of_blocks(scope: Scope) -> dict:
    """``block_id → 所属章节 kind``（用于取句时偏向方法/实验/结论章）。"""
    from app.modules import claims as claims_mod

    try:
        structure = claims_mod.get_structure(scope)
    except Exception:  # noqa: BLE001 - 结构不可用时退化为无权重
        return {}
    out: dict = {}
    for sec in (structure.sections or []):
        for bid in (sec.source_block_ids or []):
            out[bid] = (sec.kind or "")
    return out


def _sentence_score(sentence: str, section_kind: str) -> int:
    """给候选句打分：**量化结论句**得分最高（与产品抽取的目标内容一致）。"""
    score = 0
    if _QUANT_SIGNAL_RE.search(sentence):
        score += 3
    if _CLAIM_SIGNAL_RE.search(sentence):
        score += 1
    if section_kind in _RESULT_SECTION_KINDS:
        score += 2
    if 40 <= len(sentence) <= 140:
        score += 1
    return score


def _section_heading_of_blocks(scope: Scope) -> dict:
    """``block_id → 所属章节标题``（用于整章排除参考文献/致谢等）。"""
    from app.modules import claims as claims_mod

    try:
        structure = claims_mod.get_structure(scope)
    except Exception:  # noqa: BLE001 - 结构不可用时退化为不排除
        return {}
    out: dict = {}
    for sec in (structure.sections or []):
        heading = (sec.heading or "")
        for bid in (sec.source_block_ids or []):
            out[bid] = heading
    return out


def _golden_candidates(
    blocks: List[Tuple[str, str, int]], kind_of, heading_of=None, section_kind_of=None,
) -> List[Tuple[str, str, int, int]]:
    """选出「像断言」的原文句，并**按文档位置均匀铺开**。

    返回 ``(block_id, sentence, page_index, position_bucket)``。
    为什么要铺开：断言在真实论文里主要出现在方法/实验/结论章，而**只看前 12 个块**
    会全落在题名/作者/摘要上（实测 paper 1 的 golden 与预测断言最高相似度仅 0.13）。
    ``heading_of`` 给 ``block_id → 章节标题``，用于**整章排除**参考文献/致谢（ADR-0056）。
    """
    total = max(1, len(blocks))
    heading_of = heading_of or {}
    section_kind_of = section_kind_of or {}
    out: List[Tuple[str, str, int, int]] = []
    for idx, (block_id, text, page_index) in enumerate(blocks):
        if _is_non_body_section(heading_of.get(block_id, "")):
            continue
        if _is_front_matter(text, kind_of(block_id, text)):
            continue
        sentence = _best_sentence(text, section_kind_of.get(block_id, ""))
        if not sentence:
            continue
        # 位置分桶（4 段）：后续轮转取样，保证覆盖全文而不是只覆盖开头
        bucket = min(3, int(idx * 4 / total))
        out.append((block_id, sentence, page_index, bucket))
    return out


def build_golden_set(
    scope: Scope, *,
    claim_limit: int = _MAX_CLAIMS,
    question_limit: int = _MAX_QUESTIONS,
) -> GoldenSet:
    """从**原文**确定性构造 Golden Set（不调 LLM，真值不来自模型自证）。"""
    blocks = _load_blocks(scope)
    if not blocks:
        return GoldenSet(id=_golden_id(scope), version=GOLDEN_VERSION)

    kinds = _block_kinds(scope)
    section_kind = _section_kind_of_blocks(scope)
    candidates = _golden_candidates(
        blocks, lambda bid, _t: kinds.get(bid, ""),
        _section_heading_of_blocks(scope), section_kind,
    )

    # 轮转取样：先按"量化结论句"强度排序，再在 4 个位置桶之间轮流取，
    # 兼顾**内容相关性**（与产品抽取目标一致）与**覆盖面**（不只看开头）。
    by_bucket: List[List[Tuple[str, str, int, int]]] = [[], [], [], []]
    for item in candidates:
        by_bucket[item[3]].append(item)
    for group in by_bucket:
        group.sort(key=lambda it: -_sentence_score(it[1], section_kind.get(it[0], "")))

    picked: List[Tuple[str, str, int, int]] = []
    while len(picked) < claim_limit and any(by_bucket):
        for group in by_bucket:
            if not group or len(picked) >= claim_limit:
                continue
            picked.append(group.pop(0))

    claims: List[GoldenClaim] = []
    anchors: List[GoldenAnchor] = []
    for block_id, sentence, page_index, _bucket in picked:
        idx = len(claims)
        claims.append(GoldenClaim(
            id=f"gc-{idx + 1}",
            scope=scope,
            # 逐字来自原文块：真值来源是 parser 产出，与模型判定无关
            text=sentence,
            expected_support="supports",
            acceptable_block_ids=[block_id],
        ))
        anchors.append(GoldenAnchor(
            id=f"ga-{idx + 1}",
            scope=scope,
            expected_page_index=page_index,   # parser 事实，不是模型自报
            expected_rect=None,               # 块没有矩形就不给，宁缺勿造
            source_label=f"block:{block_id[:8]}",
        ))

    questions: List[GoldenQuestion] = []
    headings = _section_headings(scope)
    # **必须给不可答题留配额**：此前可答题先用满 question_limit，导致章节多的论文
    # （paper 3 有 9 章）构造出 0 条不可答题 → 拒答率没有分母（真实踩坑）。
    answerable_limit = max(1, question_limit // 2)
    for idx, heading in enumerate(headings):
        if len(questions) >= answerable_limit:
            break
        if len(heading) < 3:
            continue
        questions.append(GoldenQuestion(
            id=f"gq-ans-{idx + 1}",
            scope=scope,
            question=f"论文中「{heading}」这一部分主要讲了什么？",
            answerable=True,
            required_points=[],
            acceptable_block_ids=[],
        ))

    corpus = _norm(" ".join(t for _b, t, _p in blocks))
    for term in _UNANSWERABLE_TERMS:
        if len(questions) >= question_limit:
            break
        if _norm(term) and _norm(term) in corpus:
            continue  # 全文里出现过 → 不能当"不可答"（必须验证，不能猜）
        questions.append(GoldenQuestion(
            id=f"gq-unans-{len(questions) + 1}",
            scope=scope,
            question=f"本文是如何使用 {term} 完成实验与部署的？",
            answerable=False,
            required_points=[],
            acceptable_block_ids=[],
        ))

    return GoldenSet(
        id=_golden_id(scope), version=GOLDEN_VERSION,
        source_hashes=[], claims=claims, questions=questions, anchors=anchors,
    )


def _golden_id(scope: Scope) -> str:
    return f"golden-{scope.paper_id}-{scope.revision_id[:8]}"


#: AI 起草版本的参考集版本号（与句子挑选版**分开**，便于追溯用的是哪种来源）
AI_GOLDEN_VERSION = "rl.golden.ai/1"
#: 送给模型起草的原文上限与产出条数上限
AI_GOLDEN_MAX_CHARS = 12000
AI_GOLDEN_MAX_CLAIMS = 12


class _AiClaim(BaseModel):
    text: str = Field(description="一条关键断言（简洁陈述句，可改写原文但不得改变事实）")
    quote: str = Field(description="支持该断言的**原文连续片段**，必须逐字照抄原文")
    section: str = Field(default="", description="该断言所属章节标题（原文里的）")


class _AiClaims(BaseModel):
    claims: list[_AiClaim] = Field(default_factory=list)


AI_GOLDEN_PROMPT = (
    "你是论文评测的出题人。阅读给定的论文原文，挑出**最值得作为参考答案的关键断言**，"
    "覆盖：方法/指标的定义、实验设置（数据集、参数、对比对象）、主要结果（带数字）、"
    "以及局限/不足。\n"
    "每条断言必须满足：\n"
    "1. ``text``：一句简洁的陈述（可以改写原文表述，但**不得改变事实、数字、条件**）；\n"
    "2. ``quote``：**逐字照抄**原文中支持该断言的连续片段（≥15 字），"
    "标点与数字照抄、不要拼接不同位置、不要加前后缀说明；\n"
    "3. ``section``：该片段所属章节标题（原文里的）。\n"
    "**最多 {n} 条**；原文里没有的结论不要写。只输出 JSON：{{\"claims\": [...]}}。\n"
)


def build_golden_set_ai(scope: Scope, ctx=None) -> GoldenSet:
    """用**模型起草**参考断言，但每条的 ``quote`` 必须**逐字出现在原文块**里（ADR-0065）。

    为什么（真实问题）：句子挑选版参考集（``build_golden_set``）取的是"每块最像断言的一句"，
    与抽取产出的断言**内容不重合**（实测 paper 2 的 precision 只有 0.18），
    AI 语义裁判再准也没用 —— 分母没对准。这里让模型读原文起草关键断言，
    既有"出题人视角"的覆盖度，又靠**引文校验**保住"真值来自原文"这条纪律。

    **纪律**：没有模型 / 调用失败 → 返回**空集合**（不退回句子挑选冒充 AI 起草）；
    集合仍按调参集保存（AI 起草 ≠ 人工确认）。
    """
    from app.core.config import settings

    if ctx is None or not getattr(settings, "has_llm", False):
        return GoldenSet(id=_golden_id(scope), version=AI_GOLDEN_VERSION)

    blocks = _load_blocks(scope)
    if not blocks:
        return GoldenSet(id=_golden_id(scope), version=AI_GOLDEN_VERSION)

    # 逐块拼原文（带块标记，便于把 quote 定位回块）；总量封顶，避免超预算
    parts: List[str] = []
    used = 0
    for block_id, text, _page in blocks:
        piece = f"[block:{block_id}] {(text or '').strip()}"
        if not piece.strip():
            continue
        if used + len(piece) > AI_GOLDEN_MAX_CHARS:
            break
        parts.append(piece)
        used += len(piece)
    source = "\n".join(parts)
    if not source:
        return GoldenSet(id=_golden_id(scope), version=AI_GOLDEN_VERSION)

    try:
        from app.contracts.ai import ChatMessage, CompletionRequest
        from app.modules import ai as ai_module

        result = ai_module.complete(
            CompletionRequest(
                messages=[
                    ChatMessage(role="system", content=AI_GOLDEN_PROMPT.format(
                        n=AI_GOLDEN_MAX_CLAIMS)),
                    ChatMessage(role="user", content=f"论文原文：\n{source}"),
                ],
                output_schema=_AiClaims,
                max_output_tokens=3000,
            ),
            ctx,
        )
    except Exception:  # noqa: BLE001  起草失败不产出集合（不伪造）
        return GoldenSet(id=_golden_id(scope), version=AI_GOLDEN_VERSION)

    value = getattr(result, "value", None)
    drafted = list(getattr(value, "claims", None) or [])
    if not drafted:
        return GoldenSet(id=_golden_id(scope), version=AI_GOLDEN_VERSION)

    claims: List[GoldenClaim] = []
    anchors: List[GoldenAnchor] = []
    for item in drafted:
        text = (getattr(item, "text", "") or "").strip()
        quote = _norm(getattr(item, "quote", "") or "")
        if not text or len(quote) < 10:
            continue
        # **引文校验**：quote 必须逐字出现在某个原文块里（空白无关），否则丢弃
        hit = None
        for block_id, block_text, page in blocks:
            if quote and quote in _norm(block_text):
                hit = (block_id, page)
                break
        if hit is None:
            continue
        idx = len(claims)
        claims.append(GoldenClaim(
            id=f"gaic-{idx + 1}",
            scope=scope,
            text=text,
            expected_support="supports",
            acceptable_block_ids=[hit[0]],
        ))
        anchors.append(GoldenAnchor(
            id=f"gaia-{idx + 1}", scope=scope, expected_page_index=int(hit[1] or 0),
            expected_rect=None, source_label=f"block:{hit[0][:8]}",
        ))
        if len(claims) >= AI_GOLDEN_MAX_CLAIMS:
            break

    return GoldenSet(
        id=_golden_id(scope), version=AI_GOLDEN_VERSION,
        source_hashes=[], claims=claims, questions=[], anchors=anchors,
    )


def build_and_save_ai(scope: Scope, ctx=None) -> GoldenSet:
    """起草并持久化 AI 参考集（仍按**调参集**保存：AI 起草 ≠ 人工确认）。

    **题目与锚点仍用确定性构造**：AI 只负责 ``claims``（关键断言）。
    理由：拒答率指标需要"不可答题"的分母，而"不可答"必须是**程序验证术语全文不出现**
    （ADR-0046 的纪律），不能交给模型自由发挥。所以这里把 ``build_golden_set`` 的
    questions/anchors 合并进来，两类来源各司其职。
    """
    from . import golden as golden_mod

    golden = build_golden_set_ai(scope, ctx)
    if not golden.claims:
        return golden
    try:
        base = build_golden_set(scope)
        golden = golden.model_copy(update={
            "questions": base.questions,
            # AI 起草时已按引文定位出锚点；只有当它没给出时才用确定性锚点
            "anchors": golden.anchors or base.anchors,
            "source_hashes": base.source_hashes,
        })
    except Exception:  # noqa: BLE001  题目构造失败不该拖垮 claims 的保存
        pass
    with session_scope() as db:
        golden_mod.save_golden_set(
            db, golden, blob_id=f"{golden.id}:{golden.version}", is_tuning=True,
        )
    return golden


def build_and_save(scope: Scope, *, annotated: bool = False) -> GoldenSet:
    """构造并持久化（幂等：同 ``(golden_id, version)`` 覆盖写）。

    ``annotated=False``（默认）→ 记为**调参集**（``is_tuning=True``）：
    机器从原文自动构造、**未经人工确认**，因此按规格不参与对外报告
    （``golden.py`` 的既有约定），评测侧会把 precision/recall 降级为 not_evaluated。
    只有 ``annotated=True``（人工确认过）才算真值、才允许出综合评分。
    """
    from . import golden as golden_mod

    golden = build_golden_set(scope)
    with session_scope() as db:
        golden_mod.save_golden_set(
            db, golden, blob_id=f"{golden.id}:{golden.version}",
            is_tuning=not annotated,
        )
    return golden


def confirm_for_scope(scope: Scope) -> Optional[GoldenSet]:
    """把该 revision 的金标集**标记为人工确认**（``is_tuning=False``）。

    语义即"人工复核通过"：调用方（admin）承担确认责任。返回 ``None`` 表示没有可确认的集合。
    """
    from . import golden as golden_mod

    with session_scope() as db:
        golden, _is_tuning = find_for_scope_ex(db, scope)
        if golden is None:
            return None
        golden_mod.save_golden_set(
            db, golden, blob_id=f"{golden.id}:{golden.version}", is_tuning=False,
        )
    return golden


#: 参考集来源优先级（越小越优先）——**决定评测用哪一版**（ADR-0065）。
#: 此前只看 ``created_at`` 最新：同一篇建了 AI 版之后再重建句子版，评测会**悄悄换回旧版**，
#: 用户完全看不出来（实测 paper 7 的评测就用了句子版，precision 因此停在 0.0）。
#: 优先级：人工确认过的 > AI 起草的（与抽取断言更对齐、引文可溯源）> 句子挑选的。
_VERSION_PRIORITY = (
    ("rl.golden.ai", 0),   # AI 起草
    ("rl.golden/", 1),     # 句子挑选
)


def _source_rank(version: str, is_tuning: bool) -> int:
    """越小越优先；不是调参集（人工确认过）的一律最优先。"""
    if not is_tuning:
        return -1
    for prefix, rank in _VERSION_PRIORITY:
        if str(version or "").startswith(prefix):
            return rank
    return 2


def find_for_scope_ex(db, scope: Scope) -> Tuple[Optional[GoldenSet], bool]:
    """找该 revision 的参考集，并返回 ``(golden, is_tuning)``。

    **选择规则是确定性的**：先按来源优先级（人工确认 > AI 起草 > 句子挑选），
    同优先级再取 ``created_at`` 最新。这样"用哪一版"可预测、可解释，
    不会因为"谁最后被重建"而变。
    """
    from sqlalchemy import select

    from app.models.audit import GoldenSetORM

    from . import golden as golden_mod

    rows = db.execute(
        select(GoldenSetORM).order_by(GoldenSetORM.created_at.desc()).limit(50)
    ).scalars().all()
    candidates = []
    for row in rows:
        golden = golden_mod.load_golden_set(db, row.golden_id, row.version)
        if golden is None:
            continue
        if golden_mod.golden_scope_ok(golden, scope.paper_id, scope.revision_id):
            candidates.append((_source_rank(row.version, bool(row.is_tuning)),
                               -float(row.created_at.timestamp() if row.created_at else 0.0),
                               golden, bool(row.is_tuning)))
    if not candidates:
        return None, False
    candidates.sort(key=lambda c: (c[0], c[1]))
    _rank, _ts, golden, is_tuning = candidates[0]
    return golden, is_tuning


def find_for_scope(db, scope: Scope) -> Optional[GoldenSet]:
    """兼容入口：只要集合本身（不含 provenance）。"""
    return find_for_scope_ex(db, scope)[0]


__all__ = [
    "GOLDEN_VERSION",
    "build_golden_set",
    "build_and_save",
    "confirm_for_scope",
    "find_for_scope",
    "find_for_scope_ex",
]
