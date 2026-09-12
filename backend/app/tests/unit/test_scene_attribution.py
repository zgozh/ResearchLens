"""M09 讲解「断言归属」回归测试。

真实缺陷（3 篇真实论文实测）：``scene.build`` 产出的每个场景都塞进了**全部**断言，
6 个场景内容完全相同、summary 也相同（"讲解乱"）。根因三连击：

1. LLM 结构产物（``_structure_with_llm``）的 section 没有 block 链接
   （``source_block_ids`` 与 ``summary.spans`` 都为空）→ ``has_link_clue=False``；
2. ``_section_kind`` 只识别英文关键词，6 个中文标题（"1 引言"/"5 实验与结果分析"…）
   全被归为默认 ``intro``；
3. ``_scene_from_section`` 的兜底分支 ``picked = all claim_rows``
   把全部断言灌进**每一个** section。

本文件锁死修复后的不变式：**每条断言最多出现在一个场景里**，
且无归属线索时**不得**把全部断言复制到每个场景。
"""
from __future__ import annotations

import os

import pytest

os.environ["LLM_API_KEY"] = ""
os.environ["LLM_BASE_URL"] = ""
os.environ["LLM_FALLBACKS"] = ""
os.environ["EMBEDDING_MODEL"] = ""

from app.contracts.common import Scope  # noqa: E402
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


def _seed_statement(scope, *, statement_id, claim_id, text, citations=(),
                    display_class="verified_fact"):
    from app.core import db as db_mod
    from app.models.evidence import StatementORM

    with db_mod.SessionLocal() as db:
        db.add(StatementORM(
            id=statement_id, paper_id=scope.paper_id, revision_id=scope.revision_id,
            claim_id=claim_id, text=text, kind="fact",
            citations=[{"block_id": b} for b in citations],
            qualifiers=[], validation=None, evidence_ids=[],
            origin="generated", display_class=display_class, ordinal=0,
        ))
        db.commit()
    return statement_id


def _seed_claim(scope, *, claim_id, statement_id, type_="RESULT", status="verified"):
    from app.core import db as db_mod
    from app.models.evidence import ClaimRecordORM

    with db_mod.SessionLocal() as db:
        db.add(ClaimRecordORM(
            id=_uniq("cr"), paper_id=scope.paper_id, revision_id=scope.revision_id,
            claim_id=claim_id, statement_id=statement_id, type=type_, status=status,
            rationale=f"理由 {claim_id}", evidence_ids=[], confidence=None,
            visibility="exhibit",
        ))
        db.commit()


def _section(scope, *, heading, kind="body", block_ids=(), summary_text="", summary_spans=()):
    """构造 SectionRecord；``block_ids``/``summary_spans`` 为空即"无归属线索"。"""
    from app.contracts.evidence import ArtifactText, SectionRecord, StatementSpan

    return SectionRecord(
        scope=scope, id=_uniq("sec"), heading=heading, kind=kind,
        source_block_ids=list(block_ids), anchor_ids=[],
        summary=ArtifactText(
            text=summary_text,
            spans=[StatementSpan(start_cp=0, end_cp=1, statement_id=s) for s in summary_spans],
        ) if summary_text else ArtifactText(text="", spans=[]),
        key_points=[],
    )


def _structure(scope, sections):
    from app.contracts.evidence import StructureArtifact

    return StructureArtifact(scope=scope, sections=list(sections))


@pytest.fixture
def world():
    from app.modules import papers as papers_mod

    paper = papers_mod.create_paper(
        PaperCreate(title="归属测试", source_mode="upload",
                    provenance_class="source_document")
    )
    source = papers_mod.store_source(
        paper.id, _minimal_pdf("attr"), SourceMetadata(original_filename="a.pdf")
    )
    revision = papers_mod.create_revision(paper.id, source.id, "source")
    return {
        "paper": paper, "source": source, "revision": revision,
        "scope": Scope(paper_id=paper.id, revision_id=revision.id),
    }


def _statements_by_scene(artifact):
    """{scene 序号: set(statement_id)}，用于检查归属与重复。"""
    return {i: set(s.statement_ids) for i, s in enumerate(artifact.scenes)}


class TestNoDuplication:
    def test_each_statement_lands_in_exactly_one_scene(self, world):
        """有 block 归属线索时，每条断言只进它引用的那个章节。"""
        from app.modules import scene

        scope = world["scope"]
        for claim_id, block, ctype, text in (
            ("c-method", "blk-1", "METHOD", "本文提出一种新的度量元集设计方法。"),
            ("c-result", "blk-2", "RESULT", "实验显示 F1 提升了 8%。"),
            ("c-limit", "blk-3", "LIMITATION", "本研究未覆盖数值溢出漏洞。"),
        ):
            sid = _seed_statement(scope, statement_id=_uniq("st"), claim_id=claim_id,
                                  text=text, citations=[block])
            _seed_claim(scope, claim_id=claim_id, statement_id=sid, type_=ctype)

        artifact = scene.build(scope, _structure(scope, [
            _section(scope, heading="3 方法", kind="method", block_ids=["blk-1"]),
            _section(scope, heading="5 实验结果与分析", kind="result", block_ids=["blk-2"]),
            _section(scope, heading="6 有效性分析", kind="limitation", block_ids=["blk-3"]),
        ]))

        by_scene = _statements_by_scene(artifact)
        all_ids = [sid for ids in by_scene.values() for sid in ids]
        assert len(all_ids) == len(set(all_ids)) == 3, \
            f"每条断言必须恰好归属一个场景，实际 {by_scene}"

        # 归属到正确章节（标题含中文关键词 → kind 必须被正确推断）
        method_scene = artifact.scenes[0]
        assert len(method_scene.statement_ids) == 1

    def test_unanchored_sections_do_not_duplicate_all_claims(self, world):
        """**真实缺陷回归**：section 无任何归属线索时，不得把全部断言复刻到每个场景。

        修复前：3 个 section × 5 条断言 = 15 次归属，且每场景内容完全相同。
        """
        from app.modules import scene

        scope = world["scope"]
        for i in range(5):
            claim_id = f"c{i}"
            sid = _seed_statement(scope, statement_id=_uniq("st"), claim_id=claim_id,
                                  text=f"第 {i} 条结论。", citations=[f"other-{i}"])
            _seed_claim(scope, claim_id=claim_id, statement_id=sid, type_="RESULT")

        artifact = scene.build(scope, _structure(scope, [
            _section(scope, heading="1 引言", kind="body"),
            _section(scope, heading="3 度量元集设计", kind="body"),
            _section(scope, heading="5 实验结果与分析", kind="body"),
        ]))

        # 5 条 RESULT 断言按 kind 分流到"5 实验结果与分析"，其余两节无内容被丢弃
        by_scene = _statements_by_scene(artifact)
        all_ids = [sid for ids in by_scene.values() for sid in ids]
        assert len(all_ids) == len(set(all_ids)) == 5, \
            f"5 条断言必须各归属一次（不是每场景 5 条），实际 {by_scene}"

    def test_claims_are_not_duplicated_across_scenes_with_mixed_linkage(self, world):
        """部分章节有链接、部分没有时，仍然不重复。"""
        from app.modules import scene

        scope = world["scope"]
        for claim_id, block in (("m1", "blk-1"), ("m2", "blk-1"), ("r1", "other")):
            sid = _seed_statement(scope, statement_id=_uniq("st"), claim_id=claim_id,
                                  text=f"{claim_id} 的结论。", citations=[block])
            _seed_claim(scope, claim_id=claim_id, statement_id=sid, type_="RESULT")

        artifact = scene.build(scope, _structure(scope, [
            _section(scope, heading="1 引言", kind="intro", block_ids=["blk-1"]),
            _section(scope, heading="5 实验结果与分析", kind="body"),
        ]))

        by_scene = _statements_by_scene(artifact)
        all_ids = [sid for ids in by_scene.values() for sid in ids]
        assert len(all_ids) == len(set(all_ids)) == 3, f"不得重复归属：{by_scene}"


class TestEmptySceneFiltering:
    def test_empty_scenes_are_dropped(self, world):
        """无已验证陈述的场景对观众是噪音 → 丢弃（"宁缺勿造"）。"""
        from app.modules import scene

        scope = world["scope"]
        sid = _seed_statement(scope, statement_id=_uniq("st"), claim_id="only",
                              text="只有这一条有内容。", citations=["blk-2"])
        _seed_claim(scope, claim_id="only", statement_id=sid, type_="RESULT")

        artifact = scene.build(scope, _structure(scope, [
            _section(scope, heading="1 引言", kind="intro", block_ids=["blk-1"]),
            _section(scope, heading="5 实验结果与分析", kind="experiment", block_ids=["blk-2"]),
            _section(scope, heading="6 有效性分析", kind="limitation", block_ids=["blk-3"]),
        ]))

        assert len(artifact.scenes) == 1, \
            f"应只保留有内容的场景，实际 {[s.title.text for s in artifact.scenes]}"
        assert artifact.scenes[0].statement_ids == [sid]
        assert artifact.scenes[0].order == 0, "保留后 order 应重新连续编号"

    def test_all_empty_keeps_one_scene(self, world):
        """全部为空时保留一个空场景，避免 presentation 变成空列表。"""
        from app.modules import scene

        scope = world["scope"]
        artifact = scene.build(scope, _structure(scope, [
            _section(scope, heading="空章节一"),
            _section(scope, heading="空章节二"),
        ]))

        assert len(artifact.scenes) == 1
        assert artifact.scenes[0].statement_ids == []


class TestChineseHeadingKind:
    def test_chinese_headings_route_claims_by_type(self, world):
        """中文标题必须能推断出 kind，从而按 claim type 正确分流（不重复）。"""
        from app.modules import scene

        scope = world["scope"]
        for claim_id, ctype, text in (
            ("ctx", "CONTEXT", "智能合约缺陷预测是软件工程的重要问题。"),
            ("res", "RESULT", "RFR 在 MAE 指标上取得最优排名。"),
            ("lim", "LIMITATION", "构造有效性可能受评估指标选择影响。"),
        ):
            sid = _seed_statement(scope, statement_id=_uniq("st"), claim_id=claim_id,
                                  text=text, citations=[f"nowhere-{claim_id}"])
            _seed_claim(scope, claim_id=claim_id, statement_id=sid, type_=ctype)

        artifact = scene.build(scope, _structure(scope, [
            _section(scope, heading="1 引言", kind="body"),
            _section(scope, heading="5 实验结果与分析", kind="body"),
            _section(scope, heading="6 有效性分析", kind="body"),
        ]))

        by_scene = _statements_by_scene(artifact)
        all_ids = [sid for ids in by_scene.values() for sid in ids]
        assert len(all_ids) == len(set(all_ids)) == 3, f"不得重复归属：{by_scene}"

        # 引言场景应只收 CONTEXT 那条
        intro_ids = by_scene[0]
        assert len(intro_ids) == 1, f"引言场景实际收到 {intro_ids}"


class TestTtsSpansAreOwn:
    """TTS 文本必须用自己的 spans（ADR-0066）。

    实测缺陷：``build_narration`` 把 **script 的 spans 直接挂到 tts_text** 上，而
    ``_to_tts_text`` 会去掉 ``*``/`` ` ``/``#`` 并压缩空白 → TTS 文本更短 →
    span 越界 → ``ArtifactText`` 校验抛 ValidationError → exhibits 阶段整体失败 →
    新导入的论文永远卡在 processing（paper 9 实测）。
    """

    def test_tts_spans_within_tts_text(self):
        from app.modules.scene import narration as N

        parts = [
            ("s1", "本文**提出**一种方法。"),
            ("s2", "实验表明   效果更好。"),
        ]
        rec = N.build_narration(parts, cue_id_prefix="cue")
        tts = rec.tts_text
        assert tts.text, "TTS 文本不该为空"
        for span in tts.spans:
            assert span.end_cp <= len(tts.text), \
                f"TTS span 越界：end={span.end_cp} len={len(tts.text)}"
        # script 侧同样要合法
        for span in rec.script.spans:
            assert span.end_cp <= len(rec.script.text)
