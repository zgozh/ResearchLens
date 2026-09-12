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

from app.contracts.common import Scope
from app.contracts.evaluation import GoldenAnchor, GoldenClaim, GoldenQuestion, GoldenSet
from app.core.db import session_scope

GOLDEN_VERSION = "rl.golden/1"

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
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[。；;.!?！？])\s*")


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
    # 单位行：既是"某大学/学院/研究所"又带邮编数字
    if any(h in body for h in _AFFILIATION_HINT) and re.search(r"\d{5,6}", body):
        return True
    return False


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


def _golden_candidates(blocks: List[Tuple[str, str, int]], kind_of) -> List[Tuple[str, str, int, int]]:
    """选出「像断言」的原文句，并**按文档位置均匀铺开**。

    返回 ``(block_id, sentence, page_index, position_bucket)``。
    为什么要铺开：断言在真实论文里主要出现在方法/实验/结论章，而**只看前 12 个块**
    会全落在题名/作者/摘要上（实测 paper 1 的 golden 与预测断言最高相似度仅 0.13）。
    """
    total = max(1, len(blocks))
    out: List[Tuple[str, str, int, int]] = []
    for idx, (block_id, text, page_index) in enumerate(blocks):
        if _is_front_matter(text, kind_of(block_id, text)):
            continue
        sentence = _first_sentence(text)
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
    candidates = _golden_candidates(blocks, lambda bid, _t: kinds.get(bid, ""))
    section_kind = _section_kind_of_blocks(scope)

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


def find_for_scope_ex(db, scope: Scope) -> Tuple[Optional[GoldenSet], bool]:
    """找该 revision 的金标集，并返回 ``(golden, is_tuning)``。"""
    from sqlalchemy import select

    from app.models.audit import GoldenSetORM

    from . import golden as golden_mod

    rows = db.execute(
        select(GoldenSetORM).order_by(GoldenSetORM.created_at.desc()).limit(50)
    ).scalars().all()
    for row in rows:
        golden = golden_mod.load_golden_set(db, row.golden_id, row.version)
        if golden is None:
            continue
        if golden_mod.golden_scope_ok(golden, scope.paper_id, scope.revision_id):
            return golden, bool(row.is_tuning)
    return None, False


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
