"""M09 scene 单元测试（REFACTOR_SPEC §6.11「单元测试」要点）。

覆盖：仅 ``p.1587``、中英图号、子图、表 S1、无关联不造假链接、
无音频时 audio_url 与 timecode 合法为 null。

全部使用临时 sqlite，绝不触碰 data/researchlens.db。
"""
from __future__ import annotations

import os

import pytest

os.environ["LLM_API_KEY"] = ""
os.environ["LLM_BASE_URL"] = ""
os.environ["LLM_FALLBACKS"] = ""
os.environ["EMBEDDING_MODEL"] = ""

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


def _seed_statement(scope, *, statement_id, claim_id, text,
                    display_class="verified_fact", evidence_ids=()):
    from app.core import db as db_mod
    from app.models.evidence import StatementORM

    with db_mod.SessionLocal() as db:
        db.add(StatementORM(
            id=statement_id, paper_id=scope.paper_id, revision_id=scope.revision_id,
            claim_id=claim_id, text=text, kind="fact", citations=[],
            qualifiers=[], validation=None, evidence_ids=list(evidence_ids),
            origin="generated", display_class=display_class, ordinal=0,
        ))
        db.commit()
    return statement_id


def _seed_claim(scope, *, claim_id, statement_id, type_="RESULT",
                status="verified", evidence_ids=()):
    from app.core import db as db_mod
    from app.models.evidence import ClaimRecordORM

    with db_mod.SessionLocal() as db:
        db.add(ClaimRecordORM(
            id=_uniq("cr"), paper_id=scope.paper_id, revision_id=scope.revision_id,
            claim_id=claim_id, statement_id=statement_id, type=type_, status=status,
            rationale=f"理由 {claim_id}", evidence_ids=list(evidence_ids),
            confidence=None, visibility="exhibit",
        ))
        db.commit()


def _seed_media(scope, *, media_id, kind="figure", legacy_no=1, label=None,
                caption="图 1 系统架构"):
    from app.core import db as db_mod
    from app.models.artifacts import MediaORM

    with db_mod.SessionLocal() as db:
        db.add(MediaORM(
            id=media_id, paper_id=scope.paper_id, revision_id=scope.revision_id,
            kind=kind, original_label=label, legacy_no=legacy_no, caption=caption,
            anchor_ids=[], original_asset_ids=[], thumbnail_asset_id=None,
            extracted=None, provenance={"representation": "pdf_crop",
                                        "verification": "source_bound"},
            excluded=False, exclusion_reason=None,
        ))
        db.commit()
    return media_id


def _seed_media_binding(scope, *, from_kind, from_id, to_id, state="verified"):
    from app.core import db as db_mod
    from app.models.evidence import BindingORM

    with db_mod.SessionLocal() as db:
        db.add(BindingORM(
            id=_uniq("bg"), paper_id=scope.paper_id, revision_id=scope.revision_id,
            from_kind=from_kind, from_id=from_id, to_kind="media", to_id=to_id,
            relation="illustrates", method="verified_claim_join", validation_id=None,
            state=state, reason="测试", score=None,
        ))
        db.commit()


def _section(scope, *, section_id, heading, claim_ids=(), kind="method"):
    from app.contracts.evidence import ArtifactText, SectionRecord

    return SectionRecord(
        scope=scope, id=section_id, heading=heading, kind=kind,
        source_block_ids=[], anchor_ids=[],
        summary=ArtifactText(text=f"{heading} 的摘要", spans=[]),
        key_points=[],
    )


def _structure(scope, sections):
    from app.contracts.evidence import StructureArtifact

    return StructureArtifact(scope=scope, sections=list(sections))


@pytest.fixture
def world():
    from app.modules import papers as papers_mod

    paper = papers_mod.create_paper(
        PaperCreate(title="讲解测试", source_mode="upload",
                    provenance_class="source_document")
    )
    source = papers_mod.store_source(
        paper.id, _minimal_pdf("scene"), SourceMetadata(original_filename="s.pdf")
    )
    revision = papers_mod.create_revision(paper.id, source.id, "source")
    return {
        "paper": paper, "source": source, "revision": revision,
        "scope": Scope(paper_id=paper.id, revision_id=revision.id),
    }


# =============================================================== 无音频 / 时间轴


class TestNoAudio:
    def test_audio_url_is_null_and_timecodes_null(self, world):
        """无音频服务：audio_url=null，SubtitleCue 两端为 null（不猜时间轴）。"""
        from app.modules import scene

        scope = world["scope"]
        sid = _seed_statement(scope, statement_id=_uniq("st"), claim_id="c1",
                              text="本文提出一种新的图神经网络方法。")
        _seed_claim(scope, claim_id="c1", statement_id=sid)

        artifact = scene.build(scope, _structure(scope, [
            _section(scope, section_id=_uniq("sec"), heading="方法", claim_ids=["c1"]),
        ]))
        assert artifact.scenes
        for s in artifact.scenes:
            assert s.narration.audio_url is None
            for cue in s.narration.subtitle_cues:
                assert cue.start_ms is None
                assert cue.end_ms is None

    def test_tts_text_and_script_cover_all_text(self, world):
        """讲解词与 tts_text 都是 ArtifactText，spans 覆盖非空白文字。"""
        from app.modules import scene

        scope = world["scope"]
        sid = _seed_statement(scope, statement_id=_uniq("st"), claim_id="c2",
                              text="实验在 ImageNet 上达到 91.2% 准确率。")
        _seed_claim(scope, claim_id="c2", statement_id=sid)

        artifact = scene.build(scope, _structure(scope, [
            _section(scope, section_id=_uniq("sec"), heading="结果", claim_ids=["c2"]),
        ]))
        s = artifact.scenes[0]
        assert s.narration.script.text.strip()
        assert s.narration.tts_text.text.strip()
        for span in s.narration.script.spans:
            assert 0 <= span.start_cp < span.end_cp <= len(s.narration.script.text)


# =============================================================== 不造假链接


class TestNoFakeLinks:
    def test_no_binding_no_media(self, world):
        """无 verified binding → media_ids 为空，不生成看似合理的链接。"""
        from app.modules import scene

        scope = world["scope"]
        sid = _seed_statement(scope, statement_id=_uniq("st"), claim_id="c3",
                              text="参见图 1 与表 S1 的实验设置。")
        _seed_claim(scope, claim_id="c3", statement_id=sid)
        # 故意造出「图 1 / 表 S1」的媒体行，但**不给 verified binding**
        _seed_media(scope, media_id=_uniq("md"), kind="figure", legacy_no=1)
        _seed_media(scope, media_id=_uniq("md"), kind="table", legacy_no=101,
                    label="表 S1", caption="表 S1 实验设置")

        artifact = scene.build(scope, _structure(scope, [
            _section(scope, section_id=_uniq("sec"), heading="方法", claim_ids=["c3"]),
        ]))
        for s in artifact.scenes:
            assert s.media_ids == [], "图号字符串不得直接产生 verified 媒体链接"
            assert s.binding_ids == []

    def test_pattern_1587_is_legacy_candidate_only(self, world):
        """``p.1587`` 只作 legacy_candidate，不进入 verified linked。"""
        from app.modules import scene

        scope = world["scope"]
        sid = _seed_statement(scope, statement_id=_uniq("st"), claim_id="c4",
                              text="如 p.1587 所述，该方法具良好泛化性。")
        _seed_claim(scope, claim_id="c4", statement_id=sid)

        artifact = scene.build(scope, _structure(scope, [
            _section(scope, section_id=_uniq("sec"), heading="讨论", claim_ids=["c4"]),
        ]))
        s = artifact.scenes[0]
        assert s.media_ids == []
        candidates = scene.legacy_candidates(s)
        assert any("1587" in p for p in candidates["print_pages"]), \
            "印刷页字符串应进入 legacy_candidate"
        assert s.media_ids == [], "候选不得升级为 verified linked"

    def test_chinese_and_english_figure_labels_are_candidates(self, world):
        from app.modules import scene

        scope = world["scope"]
        sid = _seed_statement(scope, statement_id=_uniq("st"), claim_id="c5",
                              text="Fig. 2 与图 2(a) 展示了子图对比，Table S1 给出结果。")
        _seed_claim(scope, claim_id="c5", statement_id=sid)

        artifact = scene.build(scope, _structure(scope, [
            _section(scope, section_id=_uniq("sec"), heading="结果", claim_ids=["c5"]),
        ]))
        s = artifact.scenes[0]
        cand = scene.legacy_candidates(s)
        assert cand["figure_labels"], "中英图号应被识别为候选"
        assert cand["table_labels"], "表号应被识别为候选"
        assert s.media_ids == []

    def test_verified_binding_produces_media(self, world):
        """有 verified binding 时媒体才进入 scene（正确路径）。"""
        from app.modules import scene

        scope = world["scope"]
        mid = _seed_media(scope, media_id=_uniq("md"), kind="figure", legacy_no=3)
        sid = _seed_statement(scope, statement_id=_uniq("st"), claim_id="c6",
                              text="图 3 给出的架构包含三个模块。",
                              evidence_ids=[_uniq("ev")])
        _seed_claim(scope, claim_id="c6", statement_id=sid,
                    evidence_ids=[])
        _seed_media_binding(scope, from_kind="claim", from_id="c6", to_id=mid,
                            state="verified")

        artifact = scene.build(scope, _structure(scope, [
            _section(scope, section_id=_uniq("sec"), heading="方法", claim_ids=["c6"]),
        ]))
        s = artifact.scenes[0]
        assert mid in s.media_ids, "verified binding 应使媒体进入 scene"
        assert s.binding_ids

    def test_candidate_binding_does_not_link(self, world):
        """candidate 绑定不得产生 verified linked。"""
        from app.modules import scene

        scope = world["scope"]
        mid = _seed_media(scope, media_id=_uniq("md"), kind="figure", legacy_no=4)
        sid = _seed_statement(scope, statement_id=_uniq("st"), claim_id="c7",
                              text="图 4 展示了消融结果。")
        _seed_claim(scope, claim_id="c7", statement_id=sid)
        _seed_media_binding(scope, from_kind="claim", from_id="c7", to_id=mid,
                            state="candidate")

        artifact = scene.build(scope, _structure(scope, [
            _section(scope, section_id=_uniq("sec"), heading="结果", claim_ids=["c7"]),
        ]))
        assert artifact.scenes[0].media_ids == []


# =============================================================== 仅已验证


class TestVerifiedOnly:
    def test_unverified_statement_excluded_from_scene(self, world):
        """未通过验证的陈述不进讲解正文。"""
        from app.modules import scene

        scope = world["scope"]
        sid = _seed_statement(scope, statement_id=_uniq("st"), claim_id="u1",
                              text="这是一句未经验证的草稿。",
                              display_class="unverified")
        _seed_claim(scope, claim_id="u1", statement_id=sid)

        artifact = scene.build(scope, _structure(scope, [
            _section(scope, section_id=_uniq("sec"), heading="方法", claim_ids=["u1"]),
        ]))
        s = artifact.scenes[0]
        assert "未经验证的草稿" not in s.narration.script.text
        assert s.statement_ids == []

    def test_empty_scene_when_no_claims(self, world):
        """无已验证 claim → 空场景，不编造内容。"""
        from app.modules import scene

        scope = world["scope"]
        artifact = scene.build(scope, _structure(scope, [
            _section(scope, section_id=_uniq("sec"), heading="空章节"),
        ]))
        s = artifact.scenes[0]
        assert s.narration.script.text == ""
        assert s.narration.subtitle_cues == []
        assert s.media_ids == []


# =============================================================== GET


class TestGet:
    def test_get_without_build_returns_empty_with_warning(self, world):
        from app.modules import scene

        artifact = scene.get(world["scope"])
        assert artifact.scenes == []
        assert any(w.code == "presentation_absent" for w in artifact.warnings)

    def test_get_does_not_write(self, world):
        from app.core import db as db_mod
        from app.models.artifacts import ArtifactBlobORM
        from app.modules import scene

        scope = world["scope"]
        sid = _seed_statement(scope, statement_id=_uniq("st"), claim_id="g1",
                              text="已生成内容。")
        _seed_claim(scope, claim_id="g1", statement_id=sid)
        scene.build(scope, _structure(scope, [
            _section(scope, section_id=_uniq("sec"), heading="方法", claim_ids=["g1"]),
        ]))

        with db_mod.SessionLocal() as db:
            before = db.query(ArtifactBlobORM).filter(
                ArtifactBlobORM.revision_id == scope.revision_id).count()
        scene.get(scope)
        scene.get(scope)
        with db_mod.SessionLocal() as db:
            after = db.query(ArtifactBlobORM).filter(
                ArtifactBlobORM.revision_id == scope.revision_id).count()
        assert before == after

    def test_unknown_paper_raises(self):
        from app.core.errors import DomainError
        from app.modules import scene

        with pytest.raises(DomainError):
            scene.get(Scope(paper_id=999999, revision_id="nope"))


# =============================================================== 兼容层


class TestLegacyCompat:
    def test_get_presentation_shape(self, world):
        """旧签名返回 ``{scenes: [...]}``，字段与旧 SceneOut 兼容。"""
        from app.core import db as db_mod
        from app.modules import scene

        scope = world["scope"]
        mid = _seed_media(scope, media_id=_uniq("md"), kind="figure", legacy_no=7)
        sid = _seed_statement(scope, statement_id=_uniq("st"), claim_id="l1",
                              text="图 7 内容。")
        _seed_claim(scope, claim_id="l1", statement_id=sid)
        _seed_media_binding(scope, from_kind="claim", from_id="l1", to_id=mid)
        scene.build(scope, _structure(scope, [
            _section(scope, section_id=_uniq("sec"), heading="方法", claim_ids=["l1"]),
        ]))

        with db_mod.SessionLocal() as db:
            payload = scene.get_presentation(db, world["paper"].id)

        assert "scenes" in payload
        first = payload["scenes"][0]
        for key in ("order", "title", "kind", "summary", "steps",
                    "evidence_refs", "figure_refs", "table_refs",
                    "narration", "linked"):
            assert key in first
        assert first["narration"]["audio_url"] is None
        assert 7 in first["figure_refs"], "持久化 legacy_no 应被投影为整数兼容编号"

    def test_get_presentation_unknown_paper_empty(self):
        from app.core import db as db_mod
        from app.modules import scene

        with db_mod.SessionLocal() as db:
            payload = scene.get_presentation(db, 999999)
        assert payload == {"scenes": []}
