"""QA 引文恢复：模型不给引用时用**确定性原文定位**救回答案（ADR-0035）。

真实缺陷（容器内实测，``/papers/1/qa/stream`` 恒空气泡）：

1. ``CallContext.model_snapshot`` 被声明成 ``ModelSnapshotLike`` → 下游
   ``CompletionRequest`` 校验失败 → ``llm_failed``（已由 D-32 修复）；
2. 快照修好后模型**能答**了，但返回 ``block_ids=[]`` / ``quote=""``
   （提示里展示的是 ``[chunk_id]`` 而 schema 字段叫 ``block_ids``）→ gate 判
   ``claim_without_citation`` → ``sentences=0`` → 整题**降级为拒答**。

本文件锁定第 2 类的安全网：拿模型给的引文（或整句）到**命中块的真实原文**里做
空白无关匹配，命中才恢复 ``(block_id, 原文切片)``；**找不到就照旧拒绝**——
恢复不是放宽 gate，更不是伪造引用。
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


BLOCK_TEXT = (
    "本文提出了一种基于 Haar 小波域指标自适应选择载体的 JPEG 隐写方法。"
    "该方法通过计算图像在 Haar 小波域的高频成分分解图像的高阶范数，用以优选 JPEG 隐写的载体图像。"
)


@pytest.fixture
def world():
    from app.contracts.common import Scope
    from app.contracts.documents import PaperCreate, SourceMetadata
    from app.modules import papers as papers_mod

    paper = papers_mod.create_paper(
        PaperCreate(title="QA 引文恢复", source_mode="upload", provenance_class="source_document")
    )
    source = papers_mod.store_source(
        paper.id, _minimal_pdf("qa-cite"), SourceMetadata(original_filename="q.pdf")
    )
    revision = papers_mod.create_revision(paper.id, source.id, "source")
    scope = Scope(paper_id=paper.id, revision_id=revision.id)

    from app.core import db as db_mod
    from app.models.artifacts import BlockORM, PageORM

    page_id = _uniq("pg")
    block_id = _uniq("blk")
    with db_mod.SessionLocal() as db:
        db.add(PageORM(id=page_id, paper_id=paper.id, revision_id=revision.id,
                       pdf_page_index=0, width_pt=595.0, height_pt=842.0))
        db.add(BlockORM(id=block_id, paper_id=paper.id, revision_id=revision.id,
                        page_id=page_id, ordinal=0, kind="paragraph", text=BLOCK_TEXT,
                        origin="source_extraction"))
        db.commit()
    return {"scope": scope, "block_id": block_id}


def _hit(block_id: str, text: str):
    from app.contracts.retrieval import RetrievalHit

    return RetrievalHit(chunk_id=_uniq("chunk"), block_ids=[block_id], text=text)


class TestRecoverCitation:
    def test_paraphrased_claim_text_is_not_recovered(self, world):
        """模型**改写**过的整句在原文里找不到 → 不恢复（恢复只认原文子串）。"""
        from app.modules.qa.service import _recover_citation

        scope = world["scope"]
        hits = [_hit(world["block_id"], BLOCK_TEXT)]
        allowed = {world["block_id"]}

        ids, quote = _recover_citation(
            scope, "该方法用 Haar 小波域高频成分的高阶范数优选载体。", "", hits, allowed
        )

        assert ids == [] and quote == "", "改写过的句子不得被当作引用依据"

    def test_recovers_verbatim_quote(self, world):
        from app.modules.qa.service import _recover_citation

        scope = world["scope"]
        hits = [_hit(world["block_id"], BLOCK_TEXT)]
        allowed = {world["block_id"]}
        verbatim = "该方法通过计算图像在 Haar 小波域的高频成分分解图像的高阶范数"

        ids, quote = _recover_citation(scope, "无关句子但引文正确。", verbatim, hits, allowed)

        assert ids == [world["block_id"]]
        assert quote == verbatim, "恢复的引文必须是原文片段，gate 才能判 quote_in_block"

    def test_whitespace_difference_does_not_block_recovery(self, world):
        from app.modules.qa.service import _recover_citation

        scope = world["scope"]
        hits = [_hit(world["block_id"], BLOCK_TEXT)]
        allowed = {world["block_id"]}
        spaced = "该方法通过计算图像在 Haar 小波域的高频成分分解图像的高阶范数"

        ids, _ = _recover_citation(scope, "x", spaced.replace("图像", "图 像"), hits, allowed)

        assert ids == [world["block_id"]]

    def test_paraphrase_is_not_recovered(self, world):
        """**关键**：模型改写的句子不得被"恢复"成引用（否则就是伪造引用）。"""
        from app.modules.qa.service import _recover_citation

        scope = world["scope"]
        hits = [_hit(world["block_id"], BLOCK_TEXT)]
        allowed = {world["block_id"]}

        ids, quote = _recover_citation(
            scope, "作者认为隐写不重要，因此没有做实验。", "完全没有出现在原文里的一句话。",
            hits, allowed,
        )

        assert ids == [] and quote == ""

    def test_blocks_outside_hits_are_never_used(self, world):
        """只允许用**检索命中**的块；命中之外的块不得成为引用来源。"""
        from app.modules.qa.service import _recover_citation

        scope = world["scope"]
        hits = [_hit(_uniq("other-blk"), BLOCK_TEXT)]  # 命中块 id 与库中块不一致

        ids, _ = _recover_citation(scope, BLOCK_TEXT, "", hits, {world["block_id"]})

        assert ids == [], "不得引用未被检索命中的块"


class TestExtractiveFallback:
    """模型草稿全被 gate 拒时，必须降级为**检索原文**作答，而不是直接拒答。

    实测同一问题会出现"这一次 2 句通过、下一次 0 句通过"（模型改写引文），
    直接拒答会让"证据问答"看起来完全不能用。
    """

    def _hit_with_chapter_prefix(self, block_id: str):
        """命中文本与真实检索一致：``【章节：…】`` 前缀 + 多块拼接。

        兜底抽取此前直接把这种文本整句当引文 → gate 判 ``quote_not_in_block``
        → 连兜底答案也被丢光。这里锁住"必须先收敛到某一块的原文切片"。
        """
        return _hit(block_id, f"【章节：6 总结】\n{BLOCK_TEXT}")

    def test_extractive_draft_recovers_verbatim_slice(self, world):
        from app.modules import claims as claims_svc
        from app.modules.qa.service import _extractive_draft, _statement_id

        scope = world["scope"]
        hits = [self._hit_with_chapter_prefix(world["block_id"])]
        warnings: list = []

        text, _sentences = _extractive_draft(scope, "本文方法是什么？", hits, None, warnings)

        codes = [w.code for w in warnings]
        assert "gate_unavailable" not in codes, [(w.code, w.message) for w in warnings]
        assert text, "兜底抽取必须产出原文句子"
        assert "【章节" not in text, f"章节前缀不该进入引文：{text[:60]!r}"
        stored = claims_svc.get_statements(scope, [_statement_id(scope.revision_id, text, 0)])
        assert stored, "兜底抽取必须真的注册陈述（引用落在真实块上）"
        assert [c.block_id for c in stored[0].citations] == [world["block_id"]]

    def test_draft_falls_back_when_all_claims_rejected(self, world, monkeypatch):
        """``_llm_draft`` 给的句子全部无法定位时，``_draft`` 必须走抽取兜底并留告警。"""
        from app.contracts.common import new_ctx
        from app.modules.qa import service as qa_svc

        scope = world["scope"]
        hits = [self._hit_with_chapter_prefix(world["block_id"])]
        # 单测默认关闭 LLM；这里显式打开，才能走到"模型给了草稿但全被 gate 拒"的分支
        # （``has_llm`` 是只读 property，只能打在类上）
        monkeypatch.setattr(
            type(qa_svc.settings), "has_llm", property(lambda self: True), raising=False,
        )
        ctx = new_ctx(scope, snapshot={"id": "snap-test", "chat_model": "qwen-plus"})
        monkeypatch.setattr(
            qa_svc, "_llm_draft",
            lambda q, h, c: ("模型改写过的答案。", [{
                "text": "这篇论文证明了永动机可行。",
                "block_ids": [], "quote": "永动机是可行的。", "kind": "fact",
            }], qa_svc.Usage()),
        )

        text, _sentences, _usage, _snap, returned_warnings = qa_svc._draft(
            scope, "本文方法是什么？", hits, ctx
        )

        codes = [w.code for w in returned_warnings]
        assert "extractive_fallback" in codes, [(w.code, w.message) for w in returned_warnings]
        assert text, "兜底必须产出可发布文本"


class TestGateClaimsUsesRecovery:
    def test_recovered_citation_reaches_the_gate(self, world):
        """端到端效果：模型不给引用时，恢复出的引用**必须真的送进 gate**。

        单测里语义判定（LLM）被禁用，所以陈述最终一定是 ``unverified`` ——
        这里断言的是"链路走到了 gate 且引用正确"，而不是"句子通过了"：
        ① 有 ``citation_recovered``；② 没有 ``claim_without_citation``；
        ③ **没有 ``gate_unavailable``**（这条锁住"``ctx=None`` 导致 AttributeError
        被吞成 gate 不可用"的事故）；④ 落库的陈述里引用块就是恢复出的那个。
        """
        from app.contracts.common import Warning
        from app.modules import claims as claims_svc
        from app.modules.qa.service import _gate_claims, _statement_id

        scope = world["scope"]
        hits = [_hit(world["block_id"], BLOCK_TEXT)]
        text = "本文提出基于 Haar 小波域指标的 JPEG 隐写载体选择方法。"
        claims = [{
            "text": text,
            "block_ids": [],
            "quote": "本文提出了一种基于 Haar 小波域指标自适应选择载体的 JPEG 隐写方法。",
            "kind": "fact",
        }]
        warnings: list = []

        _gate_claims(scope, claims, hits, warnings)

        codes = [w.code for w in warnings]
        assert "citation_recovered" in codes, codes
        assert "claim_without_citation" not in codes, codes
        assert "gate_unavailable" not in codes, \
            f"gate 必须是走通的，不能是依赖异常兜底：{[(w.code, w.message) for w in warnings]}"
        assert isinstance(warnings[0], Warning)

        # 陈述确实落库了，且引用块 = 恢复出来的块
        stored = claims_svc.get_statements(scope, [_statement_id(scope.revision_id, text, 0)])
        assert stored, "恢复后必须真的注册了陈述"
        assert [c.block_id for c in stored[0].citations] == [world["block_id"]]

    def test_gate_still_rejects_unrecoverable_claims(self, world):
        """恢复不了就必须照旧拒绝——安全网不是放宽 gate。"""
        from app.modules.qa.service import _gate_claims

        scope = world["scope"]
        hits = [_hit(world["block_id"], BLOCK_TEXT)]
        claims = [{
            "text": "这篇论文证明了永动机可行。",
            "block_ids": [],
            "quote": "永动机是可行的。",
            "kind": "fact",
        }]
        warnings: list = []

        sentences = _gate_claims(scope, claims, hits, warnings)

        assert sentences == []
        assert "claim_without_citation" in [w.code for w in warnings]
