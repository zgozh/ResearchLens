"""M06 claims 单元测试（REFACTOR_SPEC §6.8「单元测试」要点）。

覆盖：空论文/LLM 不可用、claim_id 碰撞、statement spans 完整覆盖、
unsupported 不可通过 summary 泄漏、方法图关联不猜图号、公式条件不被摘要省略、
draft 永不直接 SUPPORTED、MethodStep.id 必填、register_statement 只建 unverified。

全部使用临时 sqlite，绝不触碰 data/researchlens.db。
"""
from __future__ import annotations

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
    CitationCandidate,
    ClaimDraftBatch,
    ClaimRecord,
    StatementDraft,
    StatementSpan,
)
from app.core.db import Base  # noqa: E402
from app.core.errors import DomainError, ErrorCode  # noqa: E402
from app.core.security import Actor  # noqa: E402


# 数据库隔离由 ``app/tests/unit/conftest.py`` 统一负责（共享 tmp 引擎 +
# 让 session_scope 指向测试 factory），本文件不再自建引擎，避免会话中途清表。


def _minimal_pdf(text: str = "Hi") -> bytes:
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
    """论文 + revision + 原文块（直接写 canonical 表，模拟 M02 产物）。"""
    from app.models.artifacts import AnchorORM, BlockORM, PageORM
    from app.models.source import new_id
    from app.modules import papers as papers_mod

    paper = papers_mod.create_paper(
        PaperCreate(title="断言抽取测试", source_mode="upload",
                    provenance_class="source_document")
    )
    source = papers_mod.store_source(
        paper.id, _minimal_pdf("claims"), SourceMetadata(original_filename="c.pdf")
    )
    revision = papers_mod.create_revision(paper.id, source.id, "source")
    scope = Scope(paper_id=paper.id, revision_id=revision.id)

    p1 = "本文提出的方法在 ImageNet 上达到 91.2% 的准确率，比基线高出 3.4 个百分点。"
    p2 = "实验仅在单卡 A100 环境下进行，未验证多卡扩展性。"
    p3 = "训练时采用 Adam 优化器并设置学习率为 0.001。"

    from app.core import db as db_mod

    with db_mod.SessionLocal() as db:
        page = PageORM(id=new_id(), paper_id=paper.id, revision_id=revision.id,
                       pdf_page_index=0, page_label="1", label_status="verified",
                       width_pt=612.0, height_pt=792.0, text=p1)
        db.add(page)
        db.flush()
        anchor = AnchorORM(id=new_id(), paper_id=paper.id, revision_id=revision.id,
                           source_document_id=source.id, precision="region",
                           segments=[{"page_id": page.id, "pdf_page_index": 0,
                                      "page_label": "1", "rect": [0.1, 0.1, 0.9, 0.2],
                                      "quads": [], "block_ids": [], "quote_spans": []}])
        db.add(anchor)
        db.flush()
        banks = [
            BlockORM(id=new_id(), paper_id=paper.id, revision_id=revision.id,
                     page_id=page.id, ordinal=0, kind="paragraph", text=p1,
                     origin="source_extraction", anchor_id=anchor.id),
            BlockORM(id=new_id(), paper_id=paper.id, revision_id=revision.id,
                     page_id=page.id, ordinal=1, kind="paragraph", text=p2,
                     origin="source_extraction", anchor_id=anchor.id),
            BlockORM(id=new_id(), paper_id=paper.id, revision_id=revision.id,
                     page_id=page.id, ordinal=2, kind="paragraph", text=p3,
                     origin="source_extraction", anchor_id=anchor.id),
        ]
        db.add_all(banks)
        db.commit()
        ids = [b.id for b in banks]

    return {
        "paper": paper, "source": source, "revision": revision, "scope": scope,
        "b1": ids[0], "b2": ids[1], "b3": ids[2],
        "p1": p1, "p2": p2, "p3": p3,
    }


def _batch(scope, *drafts) -> ClaimDraftBatch:
    return ClaimDraftBatch(scope=scope, drafts=list(drafts))


def _draft(scope, claim_id, text, citations=(), kind="fact", qualifiers=(), sid=None):
    # statement id 必须**跨测试唯一**：statement PK 是全局的，复用会让后一个
    # 测试撞上前一个测试留下的行（导致 revision_mismatch）。
    local = sid or claim_id
    return StatementDraft(
        id=f"stmt-{scope.revision_id[:8]}-{local}",
        scope=scope,
        claim_id=claim_id,
        text=text,
        kind=kind,
        citations=list(citations),
        qualifiers=list(qualifiers),
    )


# =============================================================== 空论文 / 无 LLM


class TestEmptyAndNoLlm:
    def test_extract_empty_source_returns_empty_batch(self, world):
        """没有任何原文块 → 空 batch + warning，不抛异常。"""
        from app.modules import claims

        empty_scope = Scope(paper_id=world["paper"].id, revision_id=world["revision"].id)
        batch = claims.extract(empty_scope, ["no-such-block"], new_ctx(empty_scope))
        assert batch.drafts == []
        assert any(w.code == "empty_source" for w in batch.warnings)

    def test_extract_without_llm_returns_empty_not_fabricated(self, world):
        """无 LLM → 不伪造断言，空 batch + llm_unavailable warning。"""
        from app.modules import claims

        batch = claims.extract(world["scope"], [world["b1"]], new_ctx(world["scope"]))
        assert batch.drafts == []
        assert any(w.code == "llm_unavailable" for w in batch.warnings)

    def test_extract_unknown_revision_raises_not_found(self, world):
        from app.modules import claims
        from app.core.errors import DomainError as DE

        bad = Scope(paper_id=world["paper"].id, revision_id="missing-rev")
        with pytest.raises(DE):
            claims.extract(bad, [world["b1"]], new_ctx(bad))


# =============================================================== 状态边界


class TestDraftNeverSupported:
    def test_draft_without_evidence_is_unverified(self, world):
        """无引用 → draft 不得变成 verified。"""
        from app.modules import claims

        draft = _draft(world["scope"], "c1", "本方法显著优于所有基线。")
        result = claims.verify_and_store(_batch(world["scope"], draft), new_ctx(world["scope"]))
        assert result.claims
        assert result.claims[0].status in ("unverified", "rejected")
        assert result.claims[0].status != "verified"

    def test_exact_quote_becomes_verified_only_through_gate(self, world):
        """精确引用 + 数字一致 → 经 M04 gate 才 verified。"""
        from app.modules import claims

        draft = _draft(
            world["scope"], "c1", "该方法比基线高出 3.4 个百分点。",
            citations=[CitationCandidate(block_id=world["b1"],
                                         proposed_quote="比基线高出 3.4 个百分点")],
        )
        result = claims.verify_and_store(_batch(world["scope"], draft), new_ctx(world["scope"]))
        assert result.claims[0].status == "verified"
        assert result.claims[0].evidence_ids

    def test_fake_quote_never_verified(self, world):
        from app.modules import claims

        draft = _draft(
            world["scope"], "c1", "本方法在 ImageNet 上达到 99.9% 的准确率。",
            citations=[CitationCandidate(block_id=world["b1"],
                                         proposed_quote="本方法在 ImageNet 上达到 99.9%")],
        )
        result = claims.verify_and_store(_batch(world["scope"], draft), new_ctx(world["scope"]))
        assert result.claims[0].status == "rejected"
        assert result.claims[0].evidence_ids == []


# =============================================================== claim_id


class TestClaimId:
    def test_claim_id_collision_is_renamed_not_overwritten(self, world):
        """两个不同 statement 用同一 claim_id → 第二个被重命名，不得覆盖。"""
        from app.modules import claims

        d1 = _draft(world["scope"], "dup", "本文方法在 ImageNet 上达到 91.2% 的准确率。", sid="s1")
        d2 = _draft(world["scope"], "dup", "实验仅在单卡 A100 环境下进行。", sid="s2")
        result = claims.verify_and_store(
            _batch(world["scope"], d1, d2), new_ctx(world["scope"])
        )
        ids = [c.claim_id for c in result.claims]
        assert len(set(ids)) == 2, "同 revision 内 claim_id 必须唯一"
        assert any(w.code == "claim_id_renamed" for w in result.warnings)

    def test_claim_id_length_capped_at_32(self, world):
        """>32 字符的 claim_id 在契约层就被拒绝（不允许构造）。"""
        import pydantic
        import pytest as _pytest

        with _pytest.raises(pydantic.ValidationError):
            _draft(world["scope"], "x" * 80, "本文方法达到 91.2%。", sid="s-long")

    def test_extract_sanitizes_overlong_claim_id(self, world):
        """抽取路径上超长 claim_id 会被服务端截断到 32 字符。"""
        from app.modules.claims.service import _sanitize_claim_id, _unique_claim_id

        cleaned = _sanitize_claim_id("x" * 80, fallback_seed="s")
        assert len(cleaned) <= 32
        assert len(_unique_claim_id("y" * 80, set())) <= 32

    def test_register_statement_creates_unverified_identity_only(self, world):
        """注册只建立 unverified 身份，不产生 evidence / 不 verified。"""
        from app.modules import claims

        draft = _draft(world["scope"], "r1", "这是一个待校验的新陈述。", sid="s-reg")
        record = claims.register_statement(draft, "exhibit", new_ctx(world["scope"]))
        assert record.status == "unverified"
        assert record.evidence_ids == []
        assert record.visibility == "exhibit"

    def test_register_rejects_claim_id_taken_by_other_statement(self, world):
        from app.modules import claims

        first = _draft(world["scope"], "taken", "第一个陈述。", sid="s-first")
        claims.register_statement(first, "exhibit", new_ctx(world["scope"]))
        second = _draft(world["scope"], "taken", "第二个陈述。", sid="s-second")
        with pytest.raises(DomainError) as exc:
            claims.register_statement(second, "exhibit", new_ctx(world["scope"]))
        assert exc.value.code == ErrorCode.INVALID_INPUT

    def test_answer_only_not_listed_as_exhibit(self, world):
        """QA 临时陈述（answer_only）不得出现在展项列表。"""
        from app.modules import claims

        draft = _draft(world["scope"], "qa1", "隐藏的 QA 陈述。", sid="s-qa")
        claims.register_statement(draft, "answer_only", new_ctx(world["scope"]))
        listed = claims.list_claims(world["scope"])
        assert all(c.claim_id != "qa1" for c in listed)
        # 但按 id 仍可访问
        assert claims.get_claim(world["scope"], "qa1").claim_id == "qa1"


# =============================================================== ArtifactText


class TestArtifactTextCoverage:
    def test_spans_cover_all_non_whitespace(self, world):
        """ArtifactText.spans 必须完整覆盖所有非空白文字。"""
        from app.modules.claims import build_artifact_text

        text = "本文方法在 ImageNet 上达到 91.2%。实验仅在单卡 A100 上进行。"
        artifact = build_artifact_text(text, ["s1", "s2"])
        assert artifact.text == text
        # 覆盖检查
        covered = [False] * len(text)
        for sp in artifact.spans:
            for i in range(sp.start_cp, sp.end_cp):
                covered[i] = True
        missing = [i for i, ch in enumerate(text) if not ch.isspace() and not covered[i]]
        assert missing == [], f"存在未覆盖字符：{missing}"

    def test_no_statement_ids_yields_empty_text(self):
        """没有 statement 支撑 → 不生成任何文字（禁止无引用副文案）。"""
        from app.modules.claims import build_artifact_text

        artifact = build_artifact_text("某些生成文字", [])
        assert artifact.text == ""
        assert artifact.spans == []

    def test_empty_text_yields_empty_artifact(self):
        from app.modules.claims import build_artifact_text

        assert build_artifact_text("", ["s1"]).spans == []

    def test_spans_are_ordered_and_non_overlapping(self):
        from app.modules.claims import build_artifact_text

        text = "第一句话内容较长一些。第二句话。第三句稍微长一点。"
        artifact = build_artifact_text(text, ["a", "b", "c"])
        last_end = -1
        for sp in artifact.spans:
            assert sp.start_cp >= last_end
            assert sp.end_cp > sp.start_cp
            last_end = sp.end_cp


# =============================================================== 结构概览


class TestStructure:
    def _verified_claims(self, world):
        from app.modules import claims

        drafts = [
            _draft(world["scope"], "m1", "训练时采用 Adam 优化器并设置学习率为 0.001。",
                   citations=[CitationCandidate(block_id=world["b3"],
                                                proposed_quote="训练时采用 Adam 优化器并设置学习率为 0.001")],
                   sid="s-m1"),
            _draft(world["scope"], "r1", "该方法比基线高出 3.4 个百分点。",
                   citations=[CitationCandidate(block_id=world["b1"],
                                                proposed_quote="比基线高出 3.4 个百分点")],
                   sid="s-r1"),
        ]
        claims.verify_and_store(_batch(world["scope"], *drafts), new_ctx(world["scope"]))
        return drafts

    def test_build_structure_from_verified_only(self, world):
        from app.modules import claims

        self._verified_claims(world)
        structure = claims.build_structure(world["scope"], new_ctx(world["scope"]))
        assert structure.scope == world["scope"]
        # summary 的文本必须能推进到 spans（可追溯）
        for section in structure.sections:
            if section.summary.text:
                assert section.summary.spans
                for sp in section.summary.spans:
                    assert section.summary.text[sp.start_cp:sp.end_cp]

    def test_unverified_claim_not_in_map(self, world):
        """未验证 claim 不得进入结构产物的 claim 关联。"""
        from app.modules import claims

        draft = _draft(world["scope"], "u1", "本方法显著优于所有基线。", sid="s-u1")
        claims.verify_and_store(_batch(world["scope"], draft), new_ctx(world["scope"]))
        structure = claims.build_structure(world["scope"], new_ctx(world["scope"]))
        refs = set()
        for item in (structure.map.items if structure.map else []):
            refs.update(item.claim_ids)
        assert "u1" not in refs

    def test_method_step_has_id(self, world):
        """MethodStepRecord.id 必填。"""
        from app.modules import claims

        self._verified_claims(world)
        structure = claims.build_structure(world["scope"], new_ctx(world["scope"]))
        for step in structure.method_steps:
            assert step.id, "MethodStep.id 不能为空"

    def test_get_structure_is_read_only_and_llm_free(self, world):
        """get_structure 不调用 LLM、不写库。"""
        from app.modules import claims

        structure = claims.get_structure(world["scope"])
        assert structure.scope == world["scope"]

    def test_build_structure_is_idempotent(self, world):
        """重复生成不累积（整版覆盖）。"""
        from app.modules import claims

        self._verified_claims(world)
        first = claims.build_structure(world["scope"], new_ctx(world["scope"]))
        second = claims.build_structure(world["scope"], new_ctx(world["scope"]))
        assert len(first.sections) == len(second.sections)
        assert len(first.method_steps) == len(second.method_steps)

    def test_unsupported_summary_does_not_leak(self, world):
        """没有已验证 claim 时，结构产物不得含无归属正文（不泄漏 unsupported）。"""
        from app.modules import claims

        structure = claims.build_structure(world["scope"], new_ctx(world["scope"]))
        for section in structure.sections:
            if section.summary.text:
                assert section.summary.spans, "summary 有文字却无 span → 泄漏"


# =============================================================== 读回


class TestReadback:
    def test_get_statements_roundtrip(self, world):
        from app.modules import claims

        draft = _draft(world["scope"], "c9", "该方法比基线高出 3.4 个百分点。",
                       citations=[CitationCandidate(block_id=world["b1"],
                                                    proposed_quote="比基线高出 3.4 个百分点")],
                       sid="s-c9")
        claims.verify_and_store(_batch(world["scope"], draft), new_ctx(world["scope"]))
        sid = f"stmt-{world['scope'].revision_id[:8]}-s-c9"
        statements = claims.get_statements(world["scope"], [sid])
        assert statements and statements[0].claim_id == "c9"
        assert statements[0].evidence_ids

    def test_get_claim_missing_raises_not_found(self, world):
        from app.modules import claims

        with pytest.raises(DomainError) as exc:
            claims.get_claim(world["scope"], "nope")
        assert exc.value.code == ErrorCode.NOT_FOUND

    def test_get_statements_projects_validation_report(self, world):
        """回归：``get_statements`` 必须带出 ``validation``。

        真实缺陷背景（Postgres 实测）：``statements.validation`` 列**已落库**
        （30/30 行非空），但 ``repository.statement_dto`` 漏传该字段，
        于是读回来的 ``VerifiedStatement.validation`` 全是 ``None``。后果：

        - ``stage_verify`` 收集 ``[s.validation for s in statements if s.validation]``
          → 空 → verify 报"没有可决策的校验报告"，Supervisor 从不运行；
        - exhibits/scene/graph 拿不到验证结论 → 图谱与讲解为空。

        本测试锁住"投影必须带出 validation"这条接线。
        """
        from app.modules import claims

        draft = _draft(
            world["scope"], "c-val",
            "本文提出的方法在 ImageNet 上达到 91.2% 的准确率。",
            citations=[CitationCandidate(
                block_id=world["b1"],
                proposed_quote="本文提出的方法在 ImageNet 上达到 91.2% 的准确率",
            )],
            sid="s-cval",
        )
        claims.verify_and_store(_batch(world["scope"], draft), new_ctx(world["scope"]))

        statements = claims.get_statements(world["scope"], [draft.id])
        assert statements, "陈述应能读回"
        st = statements[0]
        assert st.validation is not None, (
            "validation 必须带出——否则 verify 阶段无报告可决策、图谱/讲解为空"
        )
        assert st.validation.statement_id == st.id
        # 报告类型必须是契约 DTO，而不是裸 dict
        from app.contracts.evidence import ValidationReport
        assert isinstance(st.validation, ValidationReport)
        assert st.validation.scope == world["scope"]

    def test_get_statements_projects_citations(self, world):
        """回归：``get_statements`` 必须带出 ``citations``（审计用候选引用）。"""
        from app.modules import claims

        draft = _draft(
            world["scope"], "c-cite", "本文方法在 ImageNet 上达到 91.2% 的准确率。",
            citations=[CitationCandidate(
                block_id=world["b1"],
                proposed_quote="在 ImageNet 上达到 91.2% 的准确率",
            )],
            sid="s-ccite",
        )
        claims.verify_and_store(_batch(world["scope"], draft), new_ctx(world["scope"]))

        st = claims.get_statements(world["scope"], [draft.id])[0]
        assert st.citations, "citations 必须带出（保留候选引用供审计）"
        assert st.citations[0].block_id == world["b1"]
        assert st.citations[0].proposed_quote

    def test_legacy_get_claims_projects_canonical(self, world):
        """回归：旧签名 ``get_claims(db, paper_id)`` 必须投影 canonical 断言。

        真实缺陷背景（Postgres 实测）：该函数此前直接转发
        ``app.services.claims``（读旧 ``claims`` 表），而旧表只被 demo seed 填充，
        于是真实论文的 ``GET /papers/{id}/claims`` 恒为空。本测试锁住
        「canonical 优先 + 陈述正文回填」这条接线。
        """
        from app.core.db import session_scope
        from app.modules import claims

        draft = _draft(
            world["scope"], "c-legacy", "本文方法在 ImageNet 上达到 91.2% 的准确率。",
            citations=[CitationCandidate(
                block_id=world["b1"],
                proposed_quote="在 ImageNet 上达到 91.2% 的准确率",
            )],
            sid="s-legacy",
        )
        claims.verify_and_store(_batch(world["scope"], draft), new_ctx(world["scope"]))

        paper_id = world["paper"].id
        with session_scope() as db:
            rows = claims.get_claims(db, paper_id)

        assert rows, "legacy get_claims 必须返回 canonical 断言（旧表为空）"
        assert any(r.statement for r in rows), "断言正文必须按 statement_id 回填"

    def test_claim_record_max_len_invariant(self, world):
        from app.modules import claims

        draft = _draft(world["scope"], "z" * 32, "本文方法达到 91.2%。", sid="s-z")
        result = claims.verify_and_store(_batch(world["scope"], draft), new_ctx(world["scope"]))
        for claim in result.claims:
            assert isinstance(claim, ClaimRecord)
            assert len(claim.claim_id) <= 32


# =============================================================== 边界


class TestBoundaryRules:
    def test_m06_does_not_touch_block_tables(self):
        """M06 service 不得直接写 Page/Block（只由 M02 拥有）。"""
        import inspect

        from app.modules.claims import service

        source = inspect.getsource(service)
        assert "db.add(BlockORM" not in source
        assert "db.add(PageORM" not in source
        assert "repo.replace_structure" in source
