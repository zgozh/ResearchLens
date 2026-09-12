"""M06 重抽取：换语料后必须**先清旧断言**（ADR-0022）。

``upsert_claim`` 以 ``(revision_id, claim_id)`` 为键、``upsert_statement`` 以 statement id
为键，而 claim_id 由**模型输出**决定。换一份语料（例如把"只读头部"改成"按章节分配"）
就会产出一批新 id → 旧行**不会被覆盖**，而是残留成孤儿：新旧 claim 混杂、旧 statement
还挂在同一 revision 上，图谱/讲解会同时看到两套。

所以"重抽取"必须**显式清理**该 revision 的断言派生数据，而不是指望幂等 upsert。
清理范围要精确：只删断言派生行，不碰解析产物（pages/blocks/media/anchors）。
"""
from __future__ import annotations

import os

import pytest

os.environ["LLM_API_KEY"] = ""
os.environ["LLM_BASE_URL"] = ""
os.environ["LLM_FALLBACKS"] = ""

from app.contracts.common import Scope, new_ctx  # noqa: E402
from app.contracts.documents import PaperCreate, SourceMetadata  # noqa: E402


def _uniq(prefix: str) -> str:
    import uuid

    return f"{prefix}-{uuid.uuid4().hex[:12]}"


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


def _seed_claim_stack(scope, *, tag="old"):
    """在该 revision 造一整套断言派生数据 + 一条 media（media 不该被清）。"""
    from app.core import db as db_mod
    from app.models.artifacts import MediaORM
    from app.models.evidence import (
        BindingORM, ClaimRecordORM, EvidenceRowORM, StatementORM, ValidationORM,
    )

    statement_id = _uniq("st")
    media_id = _uniq("md")
    with db_mod.SessionLocal() as db:
        db.add(StatementORM(
            id=statement_id, paper_id=scope.paper_id, revision_id=scope.revision_id,
            claim_id=f"{tag}-claim", text="旧断言文本", kind="fact", citations=[],
            qualifiers=[], validation=None, evidence_ids=[], origin="generated",
            display_class="verified_fact", ordinal=0,
        ))
        db.add(ClaimRecordORM(
            id=_uniq("cr"), paper_id=scope.paper_id, revision_id=scope.revision_id,
            claim_id=f"{tag}-claim", statement_id=statement_id, type="RESULT",
            status="verified", rationale="", evidence_ids=[], confidence=None,
            visibility="exhibit",
        ))
        db.add(ValidationORM(
            id=_uniq("va"), paper_id=scope.paper_id, revision_id=scope.revision_id,
            statement_id=statement_id, decision="verified",
        ))
        db.add(EvidenceRowORM(
            id=_uniq("ev"), paper_id=scope.paper_id, revision_id=scope.revision_id,
            claim_id=f"{tag}-claim", anchor_id="", source_text="旧证据",
        ))
        db.add(BindingORM(
            id=_uniq("bg"), paper_id=scope.paper_id, revision_id=scope.revision_id,
            from_kind="statement", from_id=statement_id, to_kind="media",
            to_id=media_id, relation="illustrates", method="explicit_block_ref",
            state="verified", reason="",
        ))
        db.add(MediaORM(
            id=media_id, paper_id=scope.paper_id, revision_id=scope.revision_id,
            kind="figure", original_label="1", legacy_no=1, caption="图 1",
            anchor_ids=[], original_asset_ids=[], thumbnail_asset_id=None,
            extracted=None, provenance={"representation": "mineru_crop"},
            excluded=False, exclusion_reason=None,
        ))
        db.commit()
    return statement_id, media_id


def _counts(scope):
    from app.core import db as db_mod
    from app.models.artifacts import MediaORM
    from app.models.evidence import (
        BindingORM, ClaimRecordORM, EvidenceRowORM, StatementORM, ValidationORM,
    )

    with db_mod.SessionLocal() as db:
        def n(model):
            return db.query(model).filter(
                model.revision_id == scope.revision_id).count()
        return {
            "claim_records": n(ClaimRecordORM),
            "statements": n(StatementORM),
            "validations": n(ValidationORM),
            "evidence_records": n(EvidenceRowORM),
            "bindings": n(BindingORM),
            "media": n(MediaORM),
        }


@pytest.fixture
def world():
    from app.modules import papers as papers_mod

    paper = papers_mod.create_paper(
        PaperCreate(title="重抽取测试", source_mode="upload",
                    provenance_class="source_document")
    )
    source = papers_mod.store_source(
        paper.id, _minimal_pdf("re"), SourceMetadata(original_filename="r.pdf")
    )
    revision = papers_mod.create_revision(paper.id, source.id, "source")
    return {
        "paper": paper, "source": source, "revision": revision,
        "scope": Scope(paper_id=paper.id, revision_id=revision.id),
    }


class TestDeleteClaimArtifacts:
    def test_removes_only_claim_derived_rows(self, world):
        from app.core.db import session_scope
        from app.modules.claims import repository as repo

        scope = world["scope"]
        _seed_claim_stack(scope)
        before = _counts(scope)
        assert before["claim_records"] == 1 and before["media"] == 1

        # repository 不自行 commit（事务由调用方持有），故用 session_scope 包住
        with session_scope() as db:
            removed = repo.delete_claim_artifacts(db, scope.revision_id)

        after = _counts(scope)
        for table in ("claim_records", "statements", "validations",
                      "evidence_records", "bindings"):
            assert after[table] == 0, f"{table} 应被清空，实际 {after[table]}"
            assert removed[table] == 1, f"{table} 的删除计数应为 1，实际 {removed.get(table)}"
        assert after["media"] == 1, "解析产物（media）不得被清理"

    def test_is_revision_scoped(self, world):
        """只清目标 revision，别的 revision 不受影响。"""
        from app.core.db import session_scope
        from app.modules import papers as papers_mod
        from app.modules.claims import repository as repo

        scope = world["scope"]
        _seed_claim_stack(scope, tag="old")
        other_rev = papers_mod.create_revision(
            world["paper"].id, world["source"].id, "source"
        )
        other_scope = Scope(paper_id=world["paper"].id, revision_id=other_rev.id)
        _seed_claim_stack(other_scope, tag="other")

        with session_scope() as db:
            repo.delete_claim_artifacts(db, scope.revision_id)

        assert _counts(scope)["claim_records"] == 0
        assert _counts(other_scope)["claim_records"] == 1, "不得误删其他 revision"


class TestReextract:
    def test_clears_previous_claim_rows(self, world):
        """重抽取必须先清旧断言——否则新旧 claim 混杂成孤儿。"""
        from app.modules import claims as claims_mod

        scope = world["scope"]
        _seed_claim_stack(scope)
        assert _counts(scope)["claim_records"] == 1

        claims_mod.reextract(scope, new_ctx())

        after = _counts(scope)
        assert after["claim_records"] == 0, "旧 claim 必须被清掉"
        assert after["statements"] == 0, "旧 statement 必须被清掉"
        assert after["bindings"] == 0, "旧绑定必须被清掉"
        assert after["media"] == 1, "media 不该被重抽取清掉"

    def test_reports_what_was_reset(self, world):
        from app.modules import claims as claims_mod

        scope = world["scope"]
        _seed_claim_stack(scope)

        result = claims_mod.reextract(scope, new_ctx())

        codes = {w.code for w in (result.warnings or [])}
        assert "reextract_reset" in codes, f"必须报告清理了什么，实际 {codes}"

    def test_no_llm_still_returns_cleanly(self, world):
        """无 LLM 时重抽取不得抛异常，且不得留下旧数据。"""
        from app.modules import claims as claims_mod

        scope = world["scope"]
        _seed_claim_stack(scope)

        result = claims_mod.reextract(scope, new_ctx())

        assert result.scope.revision_id == scope.revision_id
        assert result.claims == []
        assert _counts(scope)["claim_records"] == 0
