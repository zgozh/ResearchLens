"""M04 绑定：**已验证陈述 → 媒体**的生成（ADR-0009）。

真实缺陷：``bindings`` 表恒为 0 行——``evidence.bind()`` 虽然完整可用，但
**pipeline 从不调用它**，于是
``scene → verified statement → Claim/Evidence → verified Binding → Media``
这条唯一合法媒体通道永远走不通：讲解拿不到任何图表。

精度优先（用户第一要求是"不乱"），只承认两类可复核的关联：
1. ``explicit_block_ref``：陈述正文**显式写出**图/表编号，且编号能整号命中同 kind 媒体；
2. ``caption_ref``：陈述与 caption 共享至少 ``CAPTION_REF_MIN_SHARED_TOKENS``
   个区分性 token（如 MAE / FPA / F1-score）。

**宁缺勿造**：证据不足一律不建绑定，绝不"同页图表全部填满"。
"""
from __future__ import annotations

import os

import pytest

os.environ["LLM_API_KEY"] = ""
os.environ["LLM_BASE_URL"] = ""
os.environ["LLM_FALLBACKS"] = ""

from app.contracts.common import Scope, new_ctx  # noqa: E402
from app.contracts.documents import PaperCreate, SourceMetadata  # noqa: E402


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


def _seed_media(scope, *, kind="table", legacy_no=10, label="10", caption=""):
    from app.core import db as db_mod
    from app.models.artifacts import MediaORM

    media_id = _uniq("md")
    with db_mod.SessionLocal() as db:
        db.add(MediaORM(
            id=media_id, paper_id=scope.paper_id, revision_id=scope.revision_id,
            kind=kind, original_label=label, legacy_no=legacy_no, caption=caption,
            anchor_ids=[], original_asset_ids=[], thumbnail_asset_id=None,
            extracted=None, provenance={"representation": "mineru_crop"},
            excluded=False, exclusion_reason=None,
        ))
        db.commit()
    return media_id


def _seed_verified_statement(scope, *, claim_id, text, display_class="verified_fact"):
    from app.core import db as db_mod
    from app.models.evidence import ClaimRecordORM, StatementORM

    statement_id = _uniq("st")
    with db_mod.SessionLocal() as db:
        db.add(StatementORM(
            id=statement_id, paper_id=scope.paper_id, revision_id=scope.revision_id,
            claim_id=claim_id, text=text, kind="fact", citations=[], qualifiers=[],
            validation=None, evidence_ids=[], origin="generated",
            display_class=display_class, ordinal=0,
        ))
        db.add(ClaimRecordORM(
            id=_uniq("cr"), paper_id=scope.paper_id, revision_id=scope.revision_id,
            claim_id=claim_id, statement_id=statement_id, type="RESULT",
            status="verified", rationale="", evidence_ids=[], confidence=None,
            visibility="exhibit",
        ))
        db.commit()
    return statement_id


@pytest.fixture
def world():
    from app.modules import papers as papers_mod

    paper = papers_mod.create_paper(
        PaperCreate(title="绑定测试", source_mode="upload",
                    provenance_class="source_document")
    )
    source = papers_mod.store_source(
        paper.id, _minimal_pdf("bind"), SourceMetadata(original_filename="b.pdf")
    )
    revision = papers_mod.create_revision(paper.id, source.id, "source")
    return {"paper": paper, "scope": Scope(paper_id=paper.id, revision_id=revision.id)}


def _bind_all(scope, statement_ids):
    """取出陈述 DTO 并跑绑定生成。"""
    from app.modules import claims as claims_mod, evidence as evidence_mod

    statements = claims_mod.get_statements(scope, list(statement_ids))
    return evidence_mod.bind_media_for_statements(scope, statements, new_ctx())


def _bindings(scope):
    from app.core import db as db_mod
    from app.models.evidence import BindingORM

    with db_mod.SessionLocal() as db:
        return db.query(BindingORM).filter(
            BindingORM.revision_id == scope.revision_id).all()


class TestExplicitReference:
    def test_explicit_table_reference_binds_verified(self, world):
        """陈述写出 "Table 10" 且存在表 10 → verified illustrates 绑定。"""
        scope = world["scope"]
        media_id = _seed_media(scope, kind="table", legacy_no=10, label="10",
                               caption="表 10 各类型缺陷的 PDM 值和预测模型 F1-score 值")
        sid = _seed_verified_statement(
            scope, claim_id="c1",
            text="Table 10 reports both PDM (percentage of defective modules) and "
                 "F1-score values for eight specific defect types.",
        )

        created = _bind_all(scope, [sid])

        assert len(created) == 1, f"应产生 1 条绑定，实际 {created}"
        row = _bindings(scope)[0]
        assert row.to_kind == "media" and row.to_id == media_id
        assert row.relation == "illustrates"
        assert row.state == "verified"
        assert row.method == "explicit_block_ref"

    def test_chinese_figure_reference_binds(self, world):
        scope = world["scope"]
        media_id = _seed_media(scope, kind="figure", legacy_no=7, label="7",
                               caption="图 7 缺陷倾向性预测模型性能比较箱线图")
        sid = _seed_verified_statement(scope, claim_id="c2", text="如图 7 所示，箱线图给出分布。")

        _bind_all(scope, [sid])

        rows = _bindings(scope)
        assert len(rows) == 1 and rows[0].to_id == media_id
        assert rows[0].method == "explicit_block_ref"

    def test_wrong_kind_reference_does_not_bind(self, world):
        """陈述说 "表 3"，但只有图 3 → 不得绑定（编号必须同 kind 才算命中）。"""
        scope = world["scope"]
        _seed_media(scope, kind="figure", legacy_no=3, label="3", caption="图 3 代码片段")
        sid = _seed_verified_statement(scope, claim_id="c3", text="表 3 给出度量元映射关系。")

        _bind_all(scope, [sid])

        assert _bindings(scope) == [], "图表 kind 不匹配时不得建立绑定"


class TestCaptionOverlap:
    def test_two_shared_metric_tokens_bind(self, world):
        """共享 MAE + FPA 两个区分性 token → caption_ref 绑定。"""
        scope = world["scope"]
        media_id = _seed_media(scope, kind="table", legacy_no=11, label="11",
                               caption="表 11 缺陷数量预测模型的 MAE 和 FPA 值")
        sid = _seed_verified_statement(
            scope, claim_id="c4",
            text="RFR achieved the highest overall ranking across MAE and FPA metrics "
                 "for defect number prediction.",
        )

        _bind_all(scope, [sid])

        rows = _bindings(scope)
        assert len(rows) == 1, f"应产生 1 条绑定，实际 {len(rows)}"
        assert rows[0].to_id == media_id
        assert rows[0].method == "caption_ref"
        assert rows[0].state == "verified"

    def test_single_shared_token_does_not_bind(self, world):
        """只共享 1 个 token → 证据不足，不建绑定（宁缺勿造）。"""
        scope = world["scope"]
        _seed_media(scope, kind="table", legacy_no=11, label="11",
                    caption="表 11 缺陷数量预测模型的 MAE 和 FPA 值")
        sid = _seed_verified_statement(
            scope, claim_id="c5",
            text="COOP-SC-Sol outperforms COOP in FPA for defect number prediction.",
        )

        _bind_all(scope, [sid])

        assert _bindings(scope) == [], "仅 1 个共享 token 不足以建立绑定"

    def test_unrelated_statement_does_not_bind(self, world):
        scope = world["scope"]
        _seed_media(scope, kind="table", legacy_no=1, label="1", caption="表 1 合约结构")
        sid = _seed_verified_statement(
            scope, claim_id="c6", text="本文提出了一个新的采样方法并验证其有效性。",
        )

        _bind_all(scope, [sid])

        assert _bindings(scope) == []


class TestVerifiedOnlyAndCap:
    def test_unverified_statement_produces_no_binding(self, world):
        """未验证陈述不得产生绑定（媒体通道只服务已验证事实）。"""
        scope = world["scope"]
        _seed_media(scope, kind="table", legacy_no=10, label="10", caption="表 10 PDM 与 F1-score")
        sid = _seed_verified_statement(
            scope, claim_id="c7", text="Table 10 reports PDM and F1-score values.",
            display_class="unverified",
        )

        _bind_all(scope, [sid])

        assert _bindings(scope) == []

    def test_binding_is_idempotent(self, world):
        """重复跑不产生重复行（幂等键 = statement+media）。"""
        scope = world["scope"]
        media_id = _seed_media(scope, kind="table", legacy_no=10, label="10",
                               caption="表 10 PDM 与 F1-score")
        sid = _seed_verified_statement(
            scope, claim_id="c8", text="Table 10 reports PDM and F1-score values.")

        _bind_all(scope, [sid])
        _bind_all(scope, [sid])

        rows = _bindings(scope)
        assert len(rows) == 1, f"重复绑定应幂等，实际 {len(rows)} 行"
        assert rows[0].to_id == media_id

    def test_media_per_statement_is_capped(self, world):
        """同一陈述命中过多媒体时必须截断（不让一个场景被图表刷屏）。"""
        scope = world["scope"]
        for no in (1, 2, 3):
            _seed_media(scope, kind="table", legacy_no=no, label=str(no),
                        caption=f"表 {no} MAE 和 FPA 值")
        sid = _seed_verified_statement(
            scope, claim_id="c9", text="Both MAE and FPA metrics are reported.")

        _bind_all(scope, [sid])

        from app.modules import evidence as evidence_mod

        rows = _bindings(scope)
        assert 0 < len(rows) <= evidence_mod.CAPTION_REF_MAX_PER_STATEMENT


class TestSceneIntegration:
    def test_scene_links_media_after_binding(self, world):
        """端到端：绑定生成后，讲解场景才能挂上媒体（修复前恒为空）。"""
        from app.contracts.evidence import ArtifactText, SectionRecord, StructureArtifact
        from app.modules import claims as claims_mod, scene as scene_mod

        scope = world["scope"]
        media_id = _seed_media(scope, kind="table", legacy_no=10, label="10",
                               caption="表 10 各类型缺陷的 PDM 值和预测模型 F1-score 值")
        sid = _seed_verified_statement(
            scope, claim_id="c10", text="Table 10 reports PDM and F1-score values.")
        _bind_all(scope, [sid])

        claim_ids = [c.claim_id for c in claims_mod.list_claims(scope)]
        structure = StructureArtifact(scope=scope, sections=[SectionRecord(
            scope=scope, id="sec-1", heading="5 实验结果与分析", kind="experiment",
            source_block_ids=[], anchor_ids=[],
            summary=ArtifactText(text="", spans=[]), key_points=[],
        )])
        artifact = scene_mod.build(scope, structure, claims_mod.list_claims(scope))

        linked = [mid for s in artifact.scenes for mid in s.media_ids]
        assert media_id in linked, (
            f"绑定后场景必须挂上媒体；实际 media_ids={linked}，claim_ids={claim_ids}"
        )
