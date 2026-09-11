"""M04 Evidence Gate 单元测试（REFACTOR_SPEC §6.6「单元测试」要点）。

纪律：
- 全部使用**临时 sqlite**（tmp_path 下的文件库），**绝不触碰 data/researchlens.db**；
- 只 import 契约 DTO，不重定义；
- 断言的是"闸门行为"，不是实现细节。
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest

# 数据库/密钥隔离由 conftest.py 统一负责（它在本模块导入前生效）。
# 这里只确保"绝不打真实云调用"这一条，且**不覆盖** conftest 的库地址。
os.environ["LLM_API_KEY"] = ""
os.environ["LLM_BASE_URL"] = ""
os.environ["LLM_FALLBACKS"] = ""
os.environ["EMBEDDING_MODEL"] = ""

from app.contracts.common import Scope, new_ctx  # noqa: E402
from app.contracts.documents import PaperCreate, SourceMetadata  # noqa: E402
from app.contracts.evidence import (  # noqa: E402
    Binding,
    CitationCandidate,
    LegacyRef,
    ReviewRequest,
    StatementDraft,
)
from app.core.db import Base  # noqa: E402
from app.core.errors import DomainError, ErrorCode  # noqa: E402
from app.core.security import Actor  # noqa: E402


# 数据库隔离由 ``app/tests/unit/conftest.py`` 统一负责（共享 tmp 引擎 +
# 让 session_scope 指向测试 factory），本文件不再自建引擎，避免会话中途清表。


def _minimal_pdf(text: str = "Hello") -> bytes:
    content = f"BT /F1 18 Tf 72 720 Td ({text}) Tj ET".encode("latin-1", "replace")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        b"<< /Length " + str(len(content)).encode() + b" >>\nstream\n" + content + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for i, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + body + b"\nendobj\n"
    xref_pos = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode()
    out += b"0000000000 65535 f \n"
    for off in offsets[1:]:
        out += f"{off:010d} 00000 n \n".encode()
    out += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref_pos}\n%%EOF\n"
    ).encode()
    return bytes(out)


@pytest.fixture
def world():
    """构造一个"真实原文世界"：论文 + revision + 页 + 原文 block + anchor。

    原文块由测试**直接写入 canonical 表**（模拟 M02 persist 的产物），
    因为本测试只验证 M04 gate，不依赖 M02 的解析质量。
    """
    from app.models.artifacts import AnchorORM, BlockORM, PageORM
    from app.models.source import new_id
    from app.modules import papers as papers_mod

    paper = papers_mod.create_paper(
        PaperCreate(title="证据闸门测试论文", source_mode="upload",
                    provenance_class="source_document")
    )
    source = papers_mod.store_source(
        paper.id, _minimal_pdf("gate"), SourceMetadata(original_filename="g.pdf")
    )
    revision = papers_mod.create_revision(paper.id, source.id, "source")
    scope = Scope(paper_id=paper.id, revision_id=revision.id)

    # 原文文本（这就是"唯一真值来源"）
    p1_text = "本文提出的方法在 ImageNet 上达到 91.2% 的准确率，比基线高出 3.4 个百分点。"
    p1_extra = "实验仅在单卡 A100 环境下进行，未验证多卡扩展性。"
    p2_text = "如图 2 所示，模型在长文本任务上的 F1 为 88.5。"

    from sqlalchemy.orm import sessionmaker

    from app.core import db as db_mod

    factory = db_mod.SessionLocal
    with factory() as db:
        page1 = PageORM(id=new_id(), paper_id=paper.id, revision_id=revision.id,
                        pdf_page_index=0, page_label="1", label_status="verified",
                        width_pt=612.0, height_pt=792.0, text=p1_text)
        page2 = PageORM(id=new_id(), paper_id=paper.id, revision_id=revision.id,
                        pdf_page_index=1, page_label="2", label_status="verified",
                        width_pt=612.0, height_pt=792.0, text=p2_text)
        db.add_all([page1, page2])
        db.flush()

        anchor1 = AnchorORM(id=new_id(), paper_id=paper.id, revision_id=revision.id,
                            source_document_id=source.id, precision="region",
                            segments=[{"page_id": page1.id, "pdf_page_index": 0,
                                       "page_label": "1", "rect": [0.1, 0.2, 0.9, 0.35],
                                       "quads": [], "block_ids": [], "quote_spans": []}])
        db.add(anchor1)
        db.flush()

        blk1 = BlockORM(id=new_id(), paper_id=paper.id, revision_id=revision.id,
                        page_id=page1.id, ordinal=0, kind="paragraph", text=p1_text,
                        origin="source_extraction", anchor_id=anchor1.id)
        blk2 = BlockORM(id=new_id(), paper_id=paper.id, revision_id=revision.id,
                        page_id=page1.id, ordinal=1, kind="paragraph", text=p1_extra,
                        origin="source_extraction", anchor_id=anchor1.id)
        blk3 = BlockORM(id=new_id(), paper_id=paper.id, revision_id=revision.id,
                        page_id=page2.id, ordinal=0, kind="paragraph", text=p2_text,
                        origin="source_extraction")
        # 生成摘要块：**绝不能**被当成一级证据
        blk_gen = BlockORM(id=new_id(), paper_id=paper.id, revision_id=revision.id,
                           page_id=page2.id, ordinal=1, kind="paragraph",
                           text="（AI 摘要）本文提出了一个极佳的模型。",
                           origin="generated")
        db.add_all([blk1, blk2, blk3, blk_gen])
        db.commit()
        # commit 后对象属性会过期：必须在 session 仍存活时取出所有标量主键
        ids = {
            "blk1": blk1.id, "blk2": blk2.id, "blk3": blk3.id, "blk_gen": blk_gen.id,
            "page1": page1.id, "page2": page2.id, "anchor1": anchor1.id,
        }

    return {
        "paper": paper, "source": source, "revision": revision, "scope": scope,
        "p1_text": p1_text, "p1_extra": p1_extra, "p2_text": p2_text,
        **ids,
    }


def _register_statement(world, draft) -> None:
    """把 draft 写进 canonical statements 表（模拟 M06 register_statement）。

    save_report 只从**已持久化的陈述行**重建候选，因此每个测试在保存前
    必须先把当前 draft 注册进去（真实流程由 M06 完成这一步）。
    """
    from app.core import db as db_mod
    from app.models.evidence import StatementORM

    with db_mod.SessionLocal() as db:
        row = db.get(StatementORM, draft.id)
        payload = dict(
            paper_id=draft.scope.paper_id, revision_id=draft.scope.revision_id,
            claim_id=draft.claim_id, text=draft.text, kind=draft.kind,
            citations=[c.model_dump() for c in draft.citations],
            qualifiers=list(draft.qualifiers),
            origin="generated", display_class="unverified", ordinal=0,
        )
        if row is None:
            db.add(StatementORM(id=draft.id, **payload))
        else:
            for key, value in payload.items():
                setattr(row, key, value)
        db.commit()


def _draft(world, text, *, citations=(), claim_id="c1", kind="fact", qualifiers=(), stmt_id="stmt-1"):
    draft = StatementDraft(
        scope=world["scope"], id=stmt_id, claim_id=claim_id, text=text,
        kind=kind, citations=list(citations), qualifiers=list(qualifiers),
    )
    _register_statement(world, draft)
    return draft


def _cite(world, block_key, quote, media_id=None):
    return CitationCandidate(block_id=world[block_key], proposed_quote=quote, media_id=media_id)


# =============================================================== Gate 基础


class TestEvidenceGateBasics:
    def test_exact_quote_produces_verified_with_server_side_source_text(self, world):
        """精确引用 + 数字一致 → verified；source_text 必须来自原文切片。"""
        from app.modules import evidence

        quote = "在 ImageNet 上达到 91.2% 的准确率"
        draft = _draft(world, "本文方法在 ImageNet 上达到 91.2% 的准确率。",
                       citations=[_cite(world, "blk1", quote)])
        report = evidence.validate(draft, new_ctx(world["scope"]))

        assert report.scope_valid is True
        assert report.quote_valid is True
        assert report.locator_valid is True
        assert report.decision == "verified", report.reasons

    def test_save_report_persists_evidence_from_original_text(self, world):
        """保存后证据的 source_text/quote_spans 必须等于原文切片。"""
        from app.modules import evidence

        quote = "比基线高出 3.4 个百分点"
        draft = _draft(world, "该方法比基线高出 3.4 个百分点。",
                       citations=[_cite(world, "blk1", quote)])
        report = evidence.validate(draft, new_ctx(world["scope"]))
        saved = evidence.save_report(report, new_ctx(world["scope"]))

        assert saved.evidence, "verified 报告必须落库证据"
        ev = saved.evidence[0]
        assert ev.source_text == quote
        assert quote in world["p1_text"]
        assert ev.source_page == 1
        assert ev.locator_status == "exact"
        assert ev.support_status == "supports"
        assert ev.quote_spans[0].source_text == quote
        # 读回一致
        fetched = evidence.get_evidence(world["scope"], [ev.id])
        assert fetched and fetched[0].source_text == quote
        # anchor 可读
        anchor = evidence.get_anchor(world["scope"], ev.anchor_id)
        assert anchor.id == ev.anchor_id

    def test_save_report_is_idempotent(self, world):
        """重复保存同一报告不产生重复证据。"""
        from app.modules import evidence

        quote = "比基线高出 3.4 个百分点"
        draft = _draft(world, "该方法比基线高出 3.4 个百分点。",
                       citations=[_cite(world, "blk1", quote)])
        first = evidence.save_report(evidence.validate(draft, new_ctx(world["scope"])),
                                     new_ctx(world["scope"]))
        second = evidence.save_report(evidence.validate(draft, new_ctx(world["scope"])),
                                      new_ctx(world["scope"]))
        assert first.id == second.id
        assert len(first.evidence) == len(second.evidence)


# =============================================================== 伪造与越界


class TestForgedAndOutOfScope:
    def test_fake_quote_rejected(self, world):
        """伪造 quote（原文中不存在，且与原文不相似）→ 不得 verified。"""
        from app.modules import evidence

        draft = _draft(world, "本文方法在 ImageNet 上达到 99.9% 的准确率。",
                       citations=[_cite(world, "blk1", "本文方法在 ImageNet 上达到 99.9% 的准确率。")])
        report = evidence.validate(draft, new_ctx(world["scope"]))

        assert report.decision == "rejected"
        assert report.quote_valid is False
        assert any(r.code == "quote_mismatch" for r in report.reasons)
        assert report.evidence == []

    def test_ai_summary_block_cannot_be_used_as_evidence(self, world):
        """AI 摘要块（origin=generated）绝不能当一级证据。"""
        from app.modules import evidence

        draft = _draft(world, "本文提出了一个极佳的模型。",
                       citations=[_cite(world, "blk_gen", "本文提出了一个极佳的模型。")])
        report = evidence.validate(draft, new_ctx(world["scope"]))

        assert report.decision != "verified"
        assert report.evidence == []
        assert any(r.code == "missing_source" for r in report.reasons)

    def test_cross_paper_block_id_rejected(self, world):
        """跨论文 ID：引用别的 revision 的 block → 定位失败，不 verified。"""
        from app.contracts.common import Scope as _Scope
        from app.modules import evidence
        from app.modules import papers as papers_mod

        other = papers_mod.create_paper(PaperCreate(title="另一篇"))
        other_src = papers_mod.store_source(other.id, _minimal_pdf("other"),
                                           SourceMetadata(original_filename="o.pdf"))
        other_rev = papers_mod.create_revision(other.id, other_src.id, "source")

        draft = _draft(world, "本文方法在 ImageNet 上达到 91.2% 的准确率。",
                       citations=[_cite(world, "blk1", "在 ImageNet 上达到 91.2% 的准确率")])
        cross = draft.model_copy(update={
            "scope": _Scope(paper_id=other.id, revision_id=other_rev.id)
        })
        report = evidence.validate(cross, new_ctx(_Scope(paper_id=other.id,
                                                         revision_id=other_rev.id)))
        assert report.decision != "verified"
        assert report.evidence == []

    def test_wrong_revision_rejected(self, world):
        """错 revision：scope 指向不存在的 revision → NOT_FOUND。"""
        from app.contracts.common import Scope as _Scope
        from app.modules import evidence

        bad_scope = _Scope(paper_id=world["paper"].id, revision_id="does-not-exist")
        draft = _draft(world, "任意陈述", citations=[])
        draft = draft.model_copy(update={"scope": bad_scope})
        with pytest.raises(DomainError) as exc:
            evidence.validate(draft, new_ctx(bad_scope))
        assert exc.value.code == ErrorCode.NOT_FOUND

    def test_scope_mismatch_reports_wrong_scope(self, world):
        """陈述 scope 与请求 scope 不一致 → scope_valid=False，不 verified。"""
        from app.modules import evidence

        draft = _draft(world, "本文方法达到 91.2% 的准确率。",
                       citations=[_cite(world, "blk1", "在 ImageNet 上达到 91.2% 的准确率")])
        mismatched = draft.model_copy(update={"scope": draft.scope.model_copy(
            update={"revision_id": "another-revision"})})
        # revision 不存在 → NOT_FOUND（身份检查先于一切）
        with pytest.raises(DomainError):
            evidence.validate(mismatched, new_ctx(world["scope"]))


# =============================================================== 定位 vs 支持


class TestLocatorVersusSupport:
    def test_empty_evidence_high_confidence_not_supported(self, world):
        """空证据 + 模型自报高 confidence → 不得 verified。"""
        from app.modules import evidence

        draft = _draft(world, "本方法显著优于所有现有方法。", citations=[])
        ctx = new_ctx(world["scope"])
        report = evidence.validate(draft, ctx)

        assert report.decision in ("unverified", "rejected")
        assert report.locator_valid is False
        assert report.confidence is None
        assert report.evidence == []

    def test_same_page_unrelated_content_not_supported(self, world):
        """同页不相关内容：引用另一段的句子 → 定位失败，不构成支持。"""
        from app.modules import evidence

        # 拿 p2 的句子去引用 p1 的块 → 不匹配
        draft = _draft(world, "模型在长文本任务上的 F1 为 88.5。",
                       citations=[_cite(world, "blk1", "模型在长文本任务上的 F1 为 88.5")])
        report = evidence.validate(draft, new_ctx(world["scope"]))
        assert report.decision != "verified"
        assert report.quote_valid is False

    def test_locator_success_does_not_imply_support(self, world):
        """定位成功 ≠ 支持成立：引用正确但陈述与证据语义无关 → 不得 verified。"""
        from app.modules import evidence

        # 引用的是真实子串，但陈述讲的是完全不同的事，且数字不一致
        quote = "本文提出的方法在 ImageNet 上达到 91.2% 的准确率"
        draft = _draft(world, "该模型在长文本任务上 F1 达到 99.0，显存占用仅 2 GB。",
                       citations=[_cite(world, "blk1", quote)])
        report = evidence.validate(draft, new_ctx(world["scope"]))

        assert report.quote_valid is True, "引用本身确实在原文中"
        assert report.decision != "verified", "定位成功不能自动升级为支持"
        # 语义/数字至少有一项未通过
        assert report.semantic_status != "supports" or report.numeric_status == "fail"

    def test_no_llm_does_not_auto_pass_semantic_gate(self, world):
        """无 LLM 时语义 gate 不自动通过（重合度不足 → insufficient）。"""
        from app.modules import evidence

        quote = "实验仅在单卡 A100 环境下进行"
        draft = _draft(world, "该方案可无缝扩展到任意规模的集群。",
                       citations=[_cite(world, "blk2", quote)])
        report = evidence.validate(draft, new_ctx(world["scope"]))
        assert report.decision != "verified"
        assert report.semantic_status in ("insufficient", "unreviewed")


# =============================================================== 语义判定接线


class TestSemanticJudgeWiring:
    """锁定"语义判定真的有生产者"这一接线（曾经的系统性缺陷）。

    背景：``gate.semantic_verdict`` 的模型分支要求有人写入
    ``ctx._semantic_verdict`` / ``gate.semantic_model_verdict``，但全代码库
    **没有任何地方写过它** → 真实论文全部落 ``unreviewed`` → ``unverified``
    → 图谱/讲解/问答全空。本组测试确保 ``validate`` 会自己去调用判定器。
    """

    def test_validate_calls_judge_and_verdict_flips_to_verified(self, world, monkeypatch):
        """模型判 supports → 命中 gate 模型分支 → decision=verified。"""
        from app.modules import evidence
        from app.modules.evidence import semantic as semantic_mod

        calls = []

        def _fake_judge(statement, evidence_text, ctx):
            calls.append((statement, evidence_text))
            return "supports", 0.9, "模型语义判定"

        monkeypatch.setattr(semantic_mod, "judge", _fake_judge)

        quote = "本文提出的方法在 ImageNet 上达到 91.2% 的准确率"
        draft = _draft(world, quote + "，优于基线。",
                       citations=[_cite(world, "blk1", quote)])
        report = evidence.validate(draft, new_ctx(world["scope"]))

        assert calls, "validate 必须真的调用语义判定器"
        assert calls[0][1], "判定器必须收到非空的证据原文"
        assert report.semantic_status == "supports"
        assert report.decision == "verified"
        assert report.assessor == "rule"  # gate 自身仍是 rule 通道

    def test_judge_unavailable_keeps_unverified(self, world, monkeypatch):
        """判定器返回 None（无 LLM/失败）→ 不自动通过，保持未判定。"""
        from app.modules import evidence
        from app.modules.evidence import semantic as semantic_mod

        monkeypatch.setattr(
            semantic_mod, "judge", lambda s, e, c: (None, None, "调用失败")
        )

        quote = "本文提出的方法在 ImageNet 上达到 91.2% 的准确率"
        draft = _draft(world, quote + "，优于基线。",
                       citations=[_cite(world, "blk1", quote)])
        report = evidence.validate(draft, new_ctx(world["scope"]))

        assert report.decision != "verified"
        assert report.semantic_status in ("insufficient", "unreviewed")

    def test_judge_contradicts_yields_contested(self, world, monkeypatch):
        """模型判 contradicts → decision=contested（争议，不是事实）。"""
        from app.modules import evidence
        from app.modules.evidence import semantic as semantic_mod

        monkeypatch.setattr(
            semantic_mod, "judge", lambda s, e, c: ("contradicts", 0.8, "模型语义判定")
        )

        quote = "本文提出的方法在 ImageNet 上达到 91.2% 的准确率"
        draft = _draft(world, quote + "，但该方法完全无效。",
                       citations=[_cite(world, "blk1", quote)])
        report = evidence.validate(draft, new_ctx(world["scope"]))

        assert report.semantic_status == "contradicts"
        assert report.decision == "contested"

    def test_model_verdict_takes_priority_over_contradiction_marker(self, world, monkeypatch):
        """模型判定优先级高于规则否定词标记（中文误判防线）。

        证据里含"未验证"这类词，旧规则会直接判 contradict；模型说 supports
        时必须采用模型结论，否则正常中文陈述会被误判成争议。
        """
        from app.modules import evidence
        from app.modules.evidence import semantic as semantic_mod

        monkeypatch.setattr(
            semantic_mod, "judge", lambda s, e, c: ("supports", 0.9, "模型语义判定")
        )

        quote = "实验仅在单卡 A100 环境下进行，未验证多卡扩展性"
        draft = _draft(world, quote + "。",
                       citations=[_cite(world, "blk2", quote)])
        report = evidence.validate(draft, new_ctx(world["scope"]))

        assert report.semantic_status == "supports", "模型判定必须压制规则否定词"
        assert report.decision != "contested"


class TestContradictionMarkerNotOvereager:
    """规则否定词标记不得把正常中文陈述误判成"矛盾"。

    实测：旧标记表含 "并未/并非/无法/然而/但是/不支持" 等常用词，
    在真实中文论文上把 11/35 条正常陈述判成 contradicts（contested）。
    误判"矛盾"比"未判定"更有害——它主动断言了相反关系。
    """

    def test_common_chinese_words_are_not_contradiction_markers(self, world):
        from app.modules.evidence import gate

        # 这些是论文里极常见的正常措辞，绝不能被当成"相反结论"
        for text in (
            "但仅建模局部线性邻域关系",
            "统计不稳定，不利于隐写分析",
            "该指标与 LV 等线性指标不同",
            "然而实验表明该方法是有效的",
            "并未显著提高准确率",
            "无法处理超长文本",
        ):
            assert gate._has_contradiction_marker(text) is False, text

    def test_explicit_contradiction_still_detected(self):
        from app.modules.evidence import gate

        assert gate._has_contradiction_marker("该结论与上述结论相反") is True
        assert gate._has_contradiction_marker("结果相反，方法失效") is True
        assert gate._has_contradiction_marker("on the contrary, it fails") is True


# =============================================================== 数字/条件


class TestNumericQualifierGate:
    def test_deleted_number_fails(self, world):
        """陈述的数字被删/改（证据里没有）→ numeric fail，不 verified。"""
        from app.modules import evidence

        quote = "比基线高出 3.4 个百分点"
        draft = _draft(world, "该方法的准确率提升了 12.8 个百分点。",
                       citations=[_cite(world, "blk1", quote)])
        report = evidence.validate(draft, new_ctx(world["scope"]))
        assert report.numeric_status == "fail"
        assert report.decision == "rejected"
        assert any(r.code == "numeric_mismatch" for r in report.reasons)

    def test_dropped_qualifier_fails(self, world):
        """陈述省略"仅在…"条件 → qualifier fail。"""
        from app.modules import evidence

        # 证据是"仅在单卡 A100…"，陈述却把它当成普遍结论
        quote = "实验仅在单卡 A100 环境下进行，未验证多卡扩展性"
        draft = _draft(world, "该方法在所有硬件环境下均能稳定复现。",
                       citations=[_cite(world, "blk2", quote)])
        report = evidence.validate(draft, new_ctx(world["scope"]))
        assert report.decision != "verified"
        assert report.qualifier_status == "fail" or report.semantic_status != "supports"

    def test_qualifier_present_passes(self, world):
        """陈述保留"仅在…"条件且证据也有 → qualifier pass。"""
        from app.modules import evidence

        quote = "实验仅在单卡 A100 环境下进行"
        draft = _draft(world, "实验仅在单卡 A100 环境下进行，多卡扩展性未验证。",
                       citations=[_cite(world, "blk2", quote)])
        report = evidence.validate(draft, new_ctx(world["scope"]))
        assert report.qualifier_status == "pass"


# =============================================================== 规范化 offset


class TestNormalizedMatching:
    def test_normalized_match_maps_back_to_original_offsets(self):
        """规范化匹配必须带回**原始 offsets**（不是规范化后的下标）。"""
        from app.modules.evidence import locator

        raw = "A   B\u00a0C"          # 多空格 + NBSP
        norm = locator.normalize_with_map(raw)
        assert norm.norm == "A B C"
        # 原始切片必须能取回原字符串
        start, end = norm.to_raw_span(0, len(norm.norm))
        assert raw[start:end] == raw[start:end]
        assert norm.origin[0] == 0
        # 规范化后的 'C' 对应原串位置 5
        idx_c_norm = norm.norm.index("C")
        assert norm.origin[idx_c_norm] == raw.index("C")

    def test_normalized_quote_produces_normalized_span_with_real_offsets(self, world):
        """空白/连字差异用规范化匹配；span 切片必须等于原文真实片段。"""
        from app.modules import evidence
        from app.contracts.evidence import CitationCandidate

        # 在原文中插入连字/多空格差异的 pseudo-quote
        quote_variant = "本文提出的方法在  ImageNet 上达到 91.2% 的准确率"
        draft = _draft(world, "本文方法在 ImageNet 上达到 91.2% 的准确率。",
                       citations=[CitationCandidate(block_id=world["blk1"],
                                                    proposed_quote=quote_variant)])
        report = evidence.validate(draft, new_ctx(world["scope"]))
        assert report.quote_valid is True
        saved = evidence.save_report(report, new_ctx(world["scope"]))
        span = saved.evidence[0].quote_spans[0]
        assert span.match_method == "normalized"
        assert span.normalizer_version
        # 关键：source_text 是**原文真实切片**，不是 LLM 给的 quote
        assert span.source_text == world["p1_text"][span.start_cp:span.end_cp]
        assert span.source_text != quote_variant

    def test_fuzzy_similarity_only_yields_candidate(self, world):
        """模糊相似只产生候选，不伪造精确 quote → 不 verified。"""
        from app.modules import evidence

        quote = "本文提出的方法在 ImageNet 数据集上获得了 91.2% 的准确率"
        draft = _draft(world, "本文方法在 ImageNet 上达到 91.2% 的准确率。",
                       citations=[_cite(world, "blk1", quote)])
        report = evidence.validate(draft, new_ctx(world["scope"]))
        assert report.decision != "verified"
        assert report.evidence == []

    def test_llm_quote_never_becomes_source_text(self, world):
        """LLM 的 proposed_quote 绝不是 source_text（哪怕它真的存在）。"""
        from app.modules import evidence

        quote = "比基线高出 3.4 个百分点"
        draft = _draft(world, "该方法比基线高出 3.4 个百分点。",
                       citations=[_cite(world, "blk1", quote)])
        saved = evidence.save_report(evidence.validate(draft, new_ctx(world["scope"])),
                                     new_ctx(world["scope"]))
        ev = saved.evidence[0]
        # source_text 必须等于原文对应切片（这里恰好相等，但来源是原文）
        assert ev.source_text == world["p1_text"][
            ev.quote_spans[0].start_cp:ev.quote_spans[0].end_cp
        ]
        assert ev.quote_spans[0].start_cp > 0


# =============================================================== locator_status


class TestLocatorStatus:
    def test_page_only_has_null_rect_and_empty_quads(self):
        """page-only 必须 rect=null / quads=[]（契约硬约束）。"""
        from app.modules.evidence import gate as gate_mod
        from app.modules.evidence import locator

        cand = gate_mod.page_only_candidate(
            locator.PageRef(block_id="", page_id="p1", pdf_page_index=4,
                            page_label="1587")
        )
        assert cand.locator_status == "page_only"
        assert cand.rect is None
        assert cand.quads == []
        segment = gate_mod.candidate_to_segment(cand)
        assert segment.rect is None
        assert segment.quads == []

    def test_anchor_precision_page_when_no_rect(self):
        """无区域的候选 → anchor precision=page，绝不伪造矩形。"""
        from app.modules.evidence import gate as gate_mod
        from app.modules.evidence import locator

        cand = gate_mod.page_only_candidate(
            locator.PageRef(block_id="", page_id="p1", pdf_page_index=0)
        )
        anchor = gate_mod.build_anchor(Scope(paper_id=1, revision_id="r"), cand,
                                       anchor_id="a1", source_document_id="s1")
        assert anchor.precision == "page"
        assert anchor.segments[0].rect is None


# =============================================================== legacy refs


class TestLegacyResolution:
    def test_fig_1_does_not_match_fig_10(self):
        """fig_1 与 fig_10 必须整号相等，不得子串混淆（D14）。"""
        from app.contracts.artifacts import Media, MediaProvenance
        from app.modules.evidence import legacy_resolver

        scope = Scope(paper_id=1, revision_id="r1")
        media = [
            Media(scope=scope, id="m1", kind="figure", legacy_no=1,
                  provenance=MediaProvenance(representation="extracted")),
            Media(scope=scope, id="m10", kind="figure", legacy_no=10,
                  provenance=MediaProvenance(representation="extracted")),
        ]
        matched, cands, _ = legacy_resolver.match_media(LegacyRef(text="fig_1"), media)
        assert [m.id for m in matched] == ["m1"]
        assert len(cands) == 1

        matched10, _, _ = legacy_resolver.match_media(LegacyRef(text="fig_10"), media)
        assert [m.id for m in matched10] == ["m10"]

    def test_chinese_figure_labels(self):
        """中英图号：图 2(a) / Figure 2 / 表 S1 各归其位。"""
        from app.contracts.artifacts import Media, MediaProvenance
        from app.modules.evidence import legacy_resolver

        scope = Scope(paper_id=1, revision_id="r1")
        media = [
            Media(scope=scope, id="f2", kind="figure", original_label="图 2",
                  provenance=MediaProvenance(representation="extracted")),
            Media(scope=scope, id="tS1", kind="table", original_label="表 S1",
                  provenance=MediaProvenance(representation="extracted")),
        ]
        assert [m.id for m in legacy_resolver.match_media(LegacyRef(text="图 2(a)"), media)[0]] == ["f2"]
        assert [m.id for m in legacy_resolver.match_media(LegacyRef(text="Figure 2"), media)[0]] == ["f2"]
        assert [m.id for m in legacy_resolver.match_media(LegacyRef(text="表 S1"), media)[0]] == ["tS1"]

    def test_printed_page_ambiguity_not_guessed(self):
        """印刷页重号 → ambiguous，不猜全局偏移（p.1587 场景）。"""
        from app.contracts.documents import PageLabelMapping
        from app.modules.evidence import legacy_resolver

        scope = Scope(paper_id=1, revision_id="r1")
        mappings = [
            PageLabelMapping(scope=scope, id="m1", page_label="1587",
                             pdf_page_index=11, method="printed_ocr", status="candidate"),
            PageLabelMapping(scope=scope, id="m2", page_label="1587",
                             pdf_page_index=27, method="printed_ocr", status="candidate"),
        ]
        resolved, warnings, ambiguous = legacy_resolver.resolve_map(scope, mappings, ["1587"])
        assert resolved == {}
        assert "1587" in ambiguous
        assert any(w.code == "ambiguous_page_label" for w in warnings)

    def test_unique_verified_page_mapping_resolves(self):
        """唯一且 verified 的映射才可定位页面。"""
        from app.contracts.documents import PageLabelMapping
        from app.modules.evidence import legacy_resolver

        scope = Scope(paper_id=1, revision_id="r1")
        mappings = [
            PageLabelMapping(scope=scope, id="m3", page_label="1587",
                             pdf_page_index=26, method="manual", status="verified"),
        ]
        resolved, _, ambiguous = legacy_resolver.resolve_map(scope, mappings, ["1587"])
        assert resolved.get("1587") == 26
        assert ambiguous == []

    def test_same_page_only_yields_candidate(self, world):
        """同页只能产生候选，不能 certified。"""
        from app.modules import evidence

        report = evidence.resolve_legacy(
            world["scope"], [LegacyRef(text="p.1")]
        )
        # 即使解出页级候选，也不得声称支持
        for cand in report.candidates:
            assert cand.method == "same_page"
            assert cand.reason  # 必须说明"仅页级候选"

    def test_unresolvable_ref_kept_in_unresolved(self, world):
        from app.modules import evidence

        report = evidence.resolve_legacy(world["scope"], [LegacyRef(text="完全无法解析的东西")])
        assert len(report.unresolved) == 1


# =============================================================== binding


class TestBinding:
    def test_binding_to_missing_target_rejected(self, world):
        """悬空绑定（目标不存在）必须拒绝。"""
        from app.contracts.common import ArtifactRef, SourceRef
        from app.modules import evidence

        payload = Binding(
            scope=world["scope"], id=f"b1-{world['scope'].revision_id[:8]}",
            **{"from": ArtifactRef(kind="claim", id="no-such")},
            to=SourceRef(kind="evidence", id="no-such"),
            relation="illustrates", state="candidate",
        )
        with pytest.raises(DomainError) as exc:
            evidence.bind(payload, new_ctx(world["scope"]))
        assert exc.value.code == ErrorCode.NOT_FOUND

    def test_verified_support_binding_requires_validation(self, world):
        """verified 的 supports 绑定必须关联 validation，不能自报。"""
        from app.contracts.common import ArtifactRef, SourceRef
        from app.modules import evidence

        payload = Binding(
            scope=world["scope"], id=f"b2-{world['scope'].revision_id[:8]}",
            **{"from": ArtifactRef(kind="claim", id="c1")},
            to=SourceRef(kind="anchor", id=world["anchor1"]),
            relation="supports", state="verified",
        )
        with pytest.raises(DomainError) as exc:
            evidence.bind(payload, new_ctx(world["scope"]))
        assert exc.value.code == ErrorCode.INVALID_INPUT

    def test_verified_binding_needs_matching_validation(self, world):
        """validation 语义不支持 → CONFLICT，不能标 verified。"""
        from app.contracts.common import ArtifactRef, SourceRef
        from app.modules import evidence

        quote = "比基线高出 3.4 个百分点"
        draft = _draft(world, "该方法比基线高出 3.4 个百分点。",
                       citations=[_cite(world, "blk1", quote)])
        saved = evidence.save_report(evidence.validate(draft, new_ctx(world["scope"])),
                                     new_ctx(world["scope"]))

        payload = Binding(
            scope=world["scope"], id=f"b3-{world['scope'].revision_id[:8]}",
            **{"from": ArtifactRef(kind="claim", id="c1")},
            to=SourceRef(kind="evidence", id=saved.evidence[0].id),
            relation="supports", state="verified",
            validation_id=saved.id,
        )
        ok = evidence.bind(payload, new_ctx(world["scope"]))
        assert ok.state == "verified"
        fetched = evidence.get_bindings(world["scope"], ArtifactRef(kind="claim", id="c1"))
        assert [b.id for b in fetched] == [f"b3-{world['scope'].revision_id[:8]}"]


# =============================================================== review


class TestReview:
    def test_review_requires_admin(self, world):
        from app.contracts.common import ArtifactRef
        from app.modules import evidence

        request = ReviewRequest(
            scope=world["scope"], target=ArtifactRef(kind="claim", id="c1"),
            decision="confirm", reason="人工确认",
        )
        with pytest.raises(DomainError) as exc:
            evidence.review(request, Actor(name="anon", is_admin=False), new_ctx(world["scope"]))
        assert exc.value.code == ErrorCode.INVALID_INPUT

    def test_review_is_deduplicated(self, world):
        """重复提交同 scope/target/decision/reason → 返回同记录。"""
        from app.contracts.common import ArtifactRef
        from app.modules import evidence

        request = ReviewRequest(
            scope=world["scope"], target=ArtifactRef(kind="claim", id="c1"),
            decision="confirm", reason="人工确认",
        )
        actor = Actor(name="admin", is_admin=True)
        first = evidence.review(request, actor, new_ctx(world["scope"]))
        second = evidence.review(request, actor, new_ctx(world["scope"]))
        assert first.id == second.id
        assert first.applied_revision_id is None
        assert first.job_id is None

    def test_mark_review_applied_is_idempotent_and_conflicts_on_overwrite(self, world):
        """mark_review_applied 幂等；换 revision 覆盖 → CONFLICT。"""
        from app.contracts.common import ArtifactRef
        from app.modules import evidence

        request = ReviewRequest(
            scope=world["scope"], target=ArtifactRef(kind="claim", id="c1"),
            decision="confirm", reason="确认",
        )
        actor = Actor(name="admin", is_admin=True)
        record = evidence.review(request, actor, new_ctx(world["scope"]))

        applied = evidence.mark_review_applied(record.id, world["scope"], 7, new_ctx(world["scope"]))
        assert applied.applied_revision_id == world["scope"].revision_id
        assert applied.job_id == 7
        # 幂等重放
        again = evidence.mark_review_applied(record.id, world["scope"], 7, new_ctx(world["scope"]))
        assert again.applied_revision_id == world["scope"].revision_id
        # 另一 revision → CONFLICT
        with pytest.raises(DomainError) as exc:
            evidence.mark_review_applied(record.id, world["scope"].model_copy(
                update={"revision_id": "other"}), 7, new_ctx(world["scope"]))
        assert exc.value.code == ErrorCode.CONFLICT
        # 原 request 未被修改
        assert record.request.decision == "confirm"

    def test_expected_validation_expired_conflicts(self, world):
        from app.contracts.common import ArtifactRef
        from app.modules import evidence

        request = ReviewRequest(
            scope=world["scope"], target=ArtifactRef(kind="claim", id="c1"),
            decision="confirm", reason="确认", expected_validation_id="nope",
        )
        with pytest.raises(DomainError) as exc:
            evidence.review(request, Actor(name="admin", is_admin=True),
                            new_ctx(world["scope"]))
        assert exc.value.code == ErrorCode.CONFLICT

    def test_correct_page_label_requires_label_and_index(self):
        """correct_page_label 必须给 page_label + valid index（契约校验）。"""
        from app.contracts.common import ArtifactRef
        from app.contracts.evidence import ReviewRequest as RR

        with pytest.raises(Exception):
            RR(scope=Scope(paper_id=1, revision_id="r"),
               target=ArtifactRef(kind="claim", id="c"),
               decision="correct_page_label", reason="修页码")  # 缺字段


# =============================================================== export


class TestExport:
    def test_export_has_hash_and_no_base64(self, world):
        """导出必须含 hash/状态，且**不含** PDF/base64/全文。"""
        import json

        from app.modules import evidence

        quote = "比基线高出 3.4 个百分点"
        draft = _draft(world, "该方法比基线高出 3.4 个百分点。",
                       citations=[_cite(world, "blk1", quote)])
        saved = evidence.save_report(evidence.validate(draft, new_ctx(world["scope"])),
                                     new_ctx(world["scope"]))

        from app.contracts.evidence import ClaimRecord, VerifiedStatement

        claim = ClaimRecord(scope=world["scope"], id="cr1", claim_id="c1",
                            statement_id="stmt-1", evidence_ids=[saved.evidence[0].id],
                            status="verified")
        stmt = VerifiedStatement(scope=world["scope"], id="stmt-1", claim_id="c1",
                                 text="该方法比基线高出 3.4 个百分点。",
                                 evidence_ids=[saved.evidence[0].id])
        exported = evidence.export(world["scope"], [claim], [stmt], [])

        assert exported.source_sha256 == world["source"].sha256
        assert len(exported.evidence) == 1
        blob = json.dumps(exported.model_dump(mode="json"), ensure_ascii=False)
        assert "base64" not in blob
        assert "%PDF" not in blob
        assert "JVBERi" not in blob   # PDF 的 base64 头

    def test_export_rejects_cross_scope_claim(self, world):
        from app.contracts.evidence import ClaimRecord
        from app.modules import evidence

        claim = ClaimRecord(scope=Scope(paper_id=999, revision_id="other"),
                            id="cr2", claim_id="c9", statement_id="s9")
        with pytest.raises(DomainError) as exc:
            evidence.export(world["scope"], [claim], [], [])
        assert exc.value.code == ErrorCode.REVISION_MISMATCH


# =============================================================== 边界规则


class TestBoundaryRules:
    def test_m04_does_not_import_m06(self):
        """M04 不得 import M06（避免 claims ↔ evidence 循环）。"""
        import inspect

        from app.modules.evidence import gate, legacy_resolver, locator, repository, service

        for module in (service, repository, gate, locator, legacy_resolver):
            src = inspect.getsource(module)
            assert "modules.claims" not in src, f"{module.__name__} 不得依赖 M06"
            assert "modules import claims" not in src

    def test_contracts_not_redefined(self):
        """不得在 M04 里重定义契约 DTO。"""
        import inspect

        from app.modules.evidence import service

        src = inspect.getsource(service)
        for name in ("class StatementDraft(", "class EvidenceRecord(", "class ValidationReport("):
            assert name not in src

    def test_validate_rejects_empty_text(self, world):
        from app.modules import evidence

        draft = _draft(world, "   ", citations=[])
        with pytest.raises(DomainError) as exc:
            evidence.validate(draft, new_ctx(world["scope"]))
        assert exc.value.code == ErrorCode.INVALID_INPUT
