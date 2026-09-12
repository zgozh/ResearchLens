"""可见性隔离：QA 的 ``answer_only`` 断言**不得**进入论文产物（ADR-0041）。

真实缺陷（Postgres 实测 paper 1）：``claim_records`` 里
``answer_only`` **15 条** vs ``exhibit`` **5 条**，而
``claims.build_structure`` 与 ``claims.get_verified_statements`` **都没有按 visibility 过滤**：

- ``build_structure`` 用 ``repo.list_claim_rows(db, revision_id)``（全量）→ 论文地图 /
  方法步骤 / 章节概览由**问答答案**拼出来。实测：我跑了几轮问答之后，
  paper 1 的 ``method_steps`` 从 1 条涨到 **12 条**（内容全部来自 answer_only）。
- ``get_verified_statements`` 只过滤 ``display_class``，被 scene / graph / exhibits /
  evaluation 四处共用 → 讲解分镜、研究图谱、展项包、评测指标一起被污染。

用户可见后果：论文地图/方法动画/讲解里混进"针对某个提问临时生成"的句子，
看起来就是"内容乱、也不是论文自己的结论"。

纪律：**排除"已知是问答派生"的断言，其余一律保留**（不误伤来源不明的历史行）。
"""
from __future__ import annotations

import os

import pytest

os.environ["LLM_API_KEY"] = ""
os.environ["LLM_BASE_URL"] = ""
os.environ["LLM_FALLBACKS"] = ""
os.environ["EMBEDDING_MODEL"] = ""


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


def _uniq(prefix: str) -> str:
    import uuid

    return f"{prefix}-{uuid.uuid4().hex[:12]}"


@pytest.fixture
def world():
    from app.contracts.common import Scope
    from app.contracts.documents import PaperCreate, SourceMetadata
    from app.modules import papers as papers_mod

    paper = papers_mod.create_paper(
        PaperCreate(title="可见性隔离", source_mode="upload", provenance_class="source_document")
    )
    source = papers_mod.store_source(
        paper.id, _minimal_pdf("vis"), SourceMetadata(original_filename="v.pdf")
    )
    revision = papers_mod.create_revision(paper.id, source.id, "source")
    scope = Scope(paper_id=paper.id, revision_id=revision.id)

    from app.core import db as db_mod
    from app.models.artifacts import BlockORM, PageORM

    page_id = _uniq("pg")
    block_a, block_b = _uniq("blk"), _uniq("blk")
    with db_mod.SessionLocal() as db:
        db.add(PageORM(id=page_id, paper_id=paper.id, revision_id=revision.id,
                       pdf_page_index=0, width_pt=595.0, height_pt=842.0))
        db.add(BlockORM(id=block_a, paper_id=paper.id, revision_id=revision.id,
                        page_id=page_id, ordinal=0, kind="heading", text="1 引言",
                        origin="source_extraction"))
        db.add(BlockORM(id=block_b, paper_id=paper.id, revision_id=revision.id,
                        page_id=page_id, ordinal=1, kind="paragraph",
                        text="本文提出一种基于 Haar 小波域指标的隐写方法。",
                        origin="source_extraction"))
        db.commit()
    return {"scope": scope, "block_a": block_a, "block_b": block_b}


def _seed_claim(scope, *, claim_id, text, visibility, type_="RESULT", status="verified",
                block_id=""):
    from app.core import db as db_mod
    from app.models.evidence import ClaimRecordORM, StatementORM

    statement_id = _uniq("stmt")
    with db_mod.SessionLocal() as db:
        db.add(StatementORM(
            id=statement_id, paper_id=scope.paper_id, revision_id=scope.revision_id,
            claim_id=claim_id, text=text, kind="fact",
            citations=[{"block_id": block_id}] if block_id else [],
            qualifiers=[], validation=None, evidence_ids=[], origin="generated",
            display_class="verified_fact", ordinal=0,
        ))
        db.add(ClaimRecordORM(
            id=_uniq("cr"), paper_id=scope.paper_id, revision_id=scope.revision_id,
            claim_id=claim_id, statement_id=statement_id, type=type_, status=status,
            rationale="", evidence_ids=[], confidence=None, visibility=visibility,
        ))
        db.commit()
    return statement_id


class TestVerifiedStatementsExcludeAnswerOnly:
    def test_answer_only_statements_are_excluded(self, world):
        """``get_verified_statements`` 必须排除问答派生的 ``answer_only``。"""
        from app.modules import claims as claims_mod

        scope = world["scope"]
        _seed_claim(scope, claim_id="paper_claim", text="论文自己的结论。",
                    visibility="exhibit", block_id=world["block_b"])
        _seed_claim(scope, claim_id="qa_claim", text="问答临时生成的句子。",
                    visibility="answer_only", block_id=world["block_b"])

        texts = [s.text for s in claims_mod.get_verified_statements(scope)]

        assert "论文自己的结论。" in texts
        assert "问答临时生成的句子。" not in texts, "问答断言泄漏进了论文陈述集合"

    def test_statement_without_claim_is_kept(self, world):
        """来源不明（没有 claim 行）的陈述**不误伤**：只排除明确标记的 answer_only。"""
        from app.core import db as db_mod
        from app.models.evidence import StatementORM
        from app.modules import claims as claims_mod

        scope = world["scope"]
        orphan_id = _uniq("orphan")
        with db_mod.SessionLocal() as db:
            db.add(StatementORM(
                id=orphan_id, paper_id=scope.paper_id, revision_id=scope.revision_id,
                claim_id="orphan_claim", text="来源不明的历史陈述。", kind="fact",
                citations=[], qualifiers=[], validation=None, evidence_ids=[],
                origin="source_extraction", display_class="verified_fact", ordinal=1,
            ))
            db.commit()

        texts = [s.text for s in claims_mod.get_verified_statements(scope)]

        assert "来源不明的历史陈述。" in texts, "不得误伤没有 claim 行的历史陈述"


class TestStructureExcludesAnswerOnly:
    def test_method_steps_and_map_ignore_answer_only_claims(self, world, monkeypatch):
        """结构与地图只能基于论文自己的断言；问答断言一概不参与。"""
        from app.modules import claims as claims_mod
        from app.modules.claims import prompts

        scope = world["scope"]
        # 论文自己的断言（进结构）
        _seed_claim(scope, claim_id="exhibit_step", text="先做 Haar 小波变换。",
                    visibility="exhibit", type_="METHOD", block_id=world["block_b"])
        # 问答断言（绝不进结构）
        _seed_claim(scope, claim_id="qa_step", text="这是问答临时说的步骤。",
                    visibility="answer_only", type_="METHOD", block_id=world["block_b"])

        # 让 LLM 分支"给全部 claim 各生成一步"，从而暴露过滤是否生效
        def fake_complete(request, ctx=None):  # noqa: ANN001
            from types import SimpleNamespace

            content = request.messages[-1].content
            steps = []
            for cid in ("exhibit_step", "qa_step"):
                if cid in content:
                    steps.append(SimpleNamespace(label=cid, detail=f"{cid} 的说明",
                                                 phase=None, claim_ids=[cid]))
            return SimpleNamespace(
                value=SimpleNamespace(sections=[], map_items=[], method_steps=steps),
                mode="json_schema", attempts=1, usage=None, warnings=[],
            )

        monkeypatch.setattr("app.modules.ai.complete", fake_complete)
        from app.modules.claims import service as claims_service

        monkeypatch.setattr(
            type(claims_service.settings), "has_llm", property(lambda self: True), raising=False,
        )

        from app.contracts.common import new_ctx

        artifact = claims_mod.build_structure(scope, new_ctx(scope))

        labels = [s.label.text for s in artifact.method_steps]
        assert any("Haar 小波变换" in t for t in labels), f"论文断言必须进结构：{labels}"
        assert not any("问答临时" in t for t in labels), f"问答断言泄漏进方法步骤：{labels}"
        assert all("qa_step" not in t for t in labels)
        _ = prompts


class TestGraphAndSceneExcludeAnswerOnly:
    """图谱与讲解各自有独立的 ``list_claims``，必须同样只读展项断言。"""

    def test_graph_repository_excludes_answer_only(self, world):
        from app.core import db as db_mod
        from app.modules.graph import repository as graph_repo

        scope = world["scope"]
        _seed_claim(scope, claim_id="g_exhibit", text="论文结论。", visibility="exhibit")
        _seed_claim(scope, claim_id="g_answer", text="问答句子。", visibility="answer_only")

        with db_mod.SessionLocal() as db:
            ids = [r.claim_id for r in graph_repo.list_claims(db, scope.revision_id)]

        assert ids == ["g_exhibit"], f"图谱读到了问答断言：{ids}"

    def test_scene_repository_excludes_answer_only(self, world):
        from app.core import db as db_mod
        from app.modules.scene import repository as scene_repo

        scope = world["scope"]
        _seed_claim(scope, claim_id="s_exhibit", text="论文结论。", visibility="exhibit")
        _seed_claim(scope, claim_id="s_answer", text="问答句子。", visibility="answer_only")

        with db_mod.SessionLocal() as db:
            ids = [r.claim_id for r in scene_repo.list_claims(db, scope.revision_id)]

        assert ids == ["s_exhibit"], f"讲解读到了问答断言：{ids}"

    def test_scene_build_ignores_answer_only(self, world):
        """端到端：分镜里不得出现问答派生断言。"""
        from app.contracts.common import new_ctx
        from app.modules import claims as claims_mod
        from app.modules import scene as scene_mod

        scope = world["scope"]
        _seed_claim(scope, claim_id="e_exhibit", text="实验采用十折交叉验证。",
                    visibility="exhibit", block_id=world["block_b"])
        _seed_claim(scope, claim_id="e_answer", text="这是问答临时说的结果。",
                    visibility="answer_only", block_id=world["block_b"])

        structure = claims_mod.build_structure(scope, new_ctx(scope))
        artifact = scene_mod.build(scope, structure)

        texts = [s.summary.text if hasattr(s.summary, "text") else str(s.summary)
                 for s in artifact.scenes]
        joined = " ".join(t or "" for t in texts)
        assert "问答临时" not in joined, f"分镜被问答断言污染：{texts}"
