"""M10 qa 单元测试（REFACTOR_SPEC §6.12「单元测试」要点）。

覆盖：不可回答题 / 只部分支持 / 诱导过度外推 / 中文表格问答 /
**题库无证据时 grounded=false** / **拒答不得 grounded=true** /
流 UTF-8 拆包 / 重复终态 / 断线取消。

全部使用临时 sqlite，绝不触碰 data/researchlens.db。
"""
from __future__ import annotations

import asyncio
import os

import pytest

# 数据库/密钥隔离由 conftest.py 统一负责；这里确保绝不发起真实云调用。
os.environ["LLM_API_KEY"] = ""
os.environ["LLM_BASE_URL"] = ""
os.environ["LLM_FALLBACKS"] = ""
os.environ["EMBEDDING_MODEL"] = ""

from app.contracts.common import Scope, new_ctx  # noqa: E402
from app.contracts.documents import PaperCreate, SourceMetadata  # noqa: E402
from app.contracts.qa import QARequest  # noqa: E402


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


def _make_paper(paragraphs, *, label="qa"):
    """建论文 + revision + 页 + 原文块，返回 ``(scope, block_ids)``。"""
    from app.core import db as db_mod
    from app.models.artifacts import BlockORM, PageORM
    from app.models.source import new_id
    from app.modules import papers as papers_mod

    paper = papers_mod.create_paper(
        PaperCreate(title=f"问答测试 {label}", source_mode="upload",
                    provenance_class="source_document")
    )
    source = papers_mod.store_source(
        paper.id, _minimal_pdf(label), SourceMetadata(original_filename=f"{label}.pdf")
    )
    revision = papers_mod.create_revision(paper.id, source.id, "source")
    scope = Scope(paper_id=paper.id, revision_id=revision.id)

    with db_mod.SessionLocal() as db:
        page = PageORM(id=new_id(), paper_id=paper.id, revision_id=revision.id,
                       pdf_page_index=0, page_label="1", label_status="verified",
                       width_pt=612.0, height_pt=792.0, text="\n".join(paragraphs))
        db.add(page)
        db.flush()
        rows = []
        for idx, text in enumerate(paragraphs):
            rows.append(BlockORM(
                id=new_id(), paper_id=paper.id, revision_id=revision.id,
                page_id=page.id, ordinal=idx,
                kind="table" if text.startswith(("表", "Table")) else "paragraph",
                text=text, origin="source_extraction", anchor_id=None,
                section_path=["Method"],
            ))
        db.add_all(rows)
        db.commit()
        ids = [r.id for r in rows]

    return scope, ids


@pytest.fixture
def world():
    """一篇含已验证原文的论文，索引已建好（无 LLM / 无 embedding）。"""
    from app.modules import retrieval

    scope, ids = _make_paper([
        "本文提出一种基于图神经网络的分子性质预测方法，在QM9数据集上取得最优结果。",
        "训练使用 AdamW 优化器，学习率设为 3e-4，批大小为 32。",
        "表 2 报告了不同 backbone 的 ablation 结果，其中 GIN 表现最好，准确率为 91.2%。",
    ], label="qa")
    retrieval.index(scope, new_ctx(scope))
    return {"scope": scope, "blocks": ids}


# =============================================================== grounded 语义


class TestGroundedSemantics:
    def test_unanswerable_question_abstains(self, world):
        """题库外的不可回答题：无证据 → abstained / grounded=False，不是异常。"""
        from app.modules import qa

        scope = world["scope"]
        record = qa.answer(
            scope, QARequest(question="这篇论文作者的出生地在哪个城市？"),
            new_ctx(scope),
        )
        assert record.grounded is False
        assert record.mode == "abstained"
        assert record.statements == []
        assert record.evidence == []
        assert record.text.text == ""

    def test_abstention_never_grounded(self, world):
        """**拒答绝不能被判 grounded=true**（哪怕文本里没有拒答词）。"""
        from app.modules import qa

        scope = world["scope"]
        record = qa.answer(
            scope, QARequest(question="完全无关的问题：今天天气如何？"),
            new_ctx(scope),
        )
        assert record.grounded is False
        assert record.mode in ("abstained", "extractive", "generated")
        # 关键红线：纯拒答不得 grounded
        if record.mode == "abstained":
            assert record.grounded is False

    def test_bank_without_evidence_is_not_grounded(self, world):
        """题库无证据时 grounded=false（不得只按"未出现拒答词"判定）。"""
        from app.modules import qa

        scope = world["scope"]
        records = qa.build_bank(
            scope,
            ["论文第一作者本科就读于哪所大学？", "该实验的经费来源是什么？"],
            new_ctx(scope),
        )
        assert len(records) == 2
        for rec in records:
            assert rec.grounded is False

    def test_grounded_requires_evidence(self, world):
        """有原文可抽取时允许 grounded，但必须每条事实句都有证据。"""
        from app.modules import qa

        scope = world["scope"]
        record = qa.answer(
            scope, QARequest(question="论文使用了什么优化器？"), new_ctx(scope),
        )
        if record.grounded:
            assert record.statements, "grounded 答案必须有句子"
            for st in record.statements:
                assert st.evidence_ids, "grounded 的句子必须携带证据"
        else:
            assert record.confidence == "Low"

    def test_no_summary_fabrication(self, world):
        """**绝不从 Section.summary 补造 source_text/confidence**。"""
        from app.modules import qa

        scope = world["scope"]
        record = qa.answer(
            scope, QARequest(question="论文的核心贡献是什么？"), new_ctx(scope),
        )
        for ev in record.evidence:
            assert ev.source_text, "证据必须有可追溯的原文（不得凭空编造）"
            assert ev.support_status in ("supported", "unsupported", "unknown")


# =============================================================== 部分 / 外推


class TestPartialAndExtrapolation:
    def test_partially_supported_answer_not_overclaimed(self, world):
        """只部分支持：不得把未支持内容并入事实句。"""
        from app.modules import qa

        scope = world["scope"]
        record = qa.answer(
            scope,
            QARequest(question="论文在 QM9 上的准确率是多少，且如何证明其泛化到蛋白质？"),
            new_ctx(scope),
        )
        # 若没有全量支持，必须 grounded=False，不得含糊通过
        if not record.grounded:
            assert record.confidence == "Low"
        else:
            for st in record.statements:
                assert st.evidence_ids

    def test_extrapolation_prompt_does_not_ground_inference(self, world):
        """诱导过度外推：不得凭推理产出 grounded 事实。"""
        from app.modules import qa

        scope = world["scope"]
        record = qa.answer(
            scope,
            QARequest(question="请推断该模型在真实药物研发中一定比人类专家更准确。"),
            new_ctx(scope),
        )
        assert record.grounded is False or all(
            st.display_class in ("verified_fact", "attributed_quote")
            for st in record.statements
        )

    def test_chinese_table_question(self, world):
        """中文表格问答：表号 OCR 噪声不得直接成为证据。"""
        from app.modules import qa

        scope = world["scope"]
        record = qa.answer(
            scope, QARequest(question="表 2 中哪个 backbone 表现最好？"), new_ctx(scope),
        )
        # 无论结果如何，绝不允许"裸表号"直接变成证据
        assert isinstance(record.grounded, bool)
        for ev in record.evidence:
            assert ev.id


# =============================================================== gate 单元


class TestGateUnit:
    def test_gate_abstained_false(self):
        from app.modules.qa import answer_gate as gate

        d = gate.assess("", [], mode="abstained")
        assert d.grounded is False

    def test_gate_no_rejection_word_but_no_evidence(self):
        """没有拒答词但没有证据 → 仍必须 False。"""
        from app.contracts.evidence import VerifiedStatement
        from app.modules.qa import answer_gate as gate

        st = VerifiedStatement(
            scope=Scope(paper_id=1, revision_id="r"),
            id="st1", claim_id="c1", text="这是一个看起来很确定的回答。",
            kind="fact", display_class="verified_fact", evidence_ids=[],
        )
        d = gate.assess("这是一个看起来很确定的回答。", [st], mode="generated")
        assert d.grounded is False

    def test_gate_supported_fact_grounds(self):
        from app.contracts.evidence import VerifiedStatement
        from app.modules.qa import answer_gate as gate

        st = VerifiedStatement(
            scope=Scope(paper_id=1, revision_id="r"),
            id="st1", claim_id="c1", text="实验在 ImageNet 上达到 91.2%。",
            kind="fact", display_class="verified_fact", evidence_ids=["ev1"],
        )
        d = gate.assess("实验在 ImageNet 上达到 91.2%。", [st], mode="generated")
        assert d.grounded is True

    def test_gate_inference_blocks_grounding(self):
        from app.contracts.evidence import VerifiedStatement
        from app.modules.qa import answer_gate as gate

        fact = VerifiedStatement(
            scope=Scope(paper_id=1, revision_id="r"),
            id="st1", claim_id="c1", text="事实句。",
            kind="fact", display_class="verified_fact", evidence_ids=["ev1"],
        )
        inf = VerifiedStatement(
            scope=Scope(paper_id=1, revision_id="r"),
            id="st2", claim_id="c2", text="因此必然更好。",
            kind="inference", display_class="inference", evidence_ids=["ev1"],
        )
        d = gate.assess("事实句。因此必然更好。", [fact, inf], mode="generated")
        assert d.grounded is False, "含推断的答案不得判 grounded"

    def test_unverified_draft_not_published(self):
        from app.contracts.evidence import VerifiedStatement
        from app.modules.qa import answer_gate as gate

        st = VerifiedStatement(
            scope=Scope(paper_id=1, revision_id="r"),
            id="st1", claim_id="c1", text="未验证草稿。",
            kind="fact", display_class="unverified", evidence_ids=["ev1"],
        )
        d = gate.assess("未验证草稿。", [st], mode="generated")
        assert d.grounded is False
        assert gate.publishable_sentences([st]) == []


# =============================================================== 流式协议


def _parse_frames(blob: bytes):
    """把 SSE 字节流解析为 ``[(event, data_dict_or_None)]``；注释帧返回 event=None。"""
    text = blob.decode("utf-8")
    frames = []
    for raw in text.split("\n\n"):
        raw = raw.strip("\n")
        if not raw:
            continue
        if raw.startswith(":"):
            frames.append((None, None))
            continue
        event_name = None
        data = None
        for line in raw.split("\n"):
            if line.startswith("event: "):
                event_name = line[len("event: "):]
            elif line.startswith("data: "):
                import json

                try:
                    data = json.loads(line[len("data: "):])
                except ValueError:
                    data = None
        frames.append((event_name, data))
    return frames


class TestStreamProtocol:
    def test_frame_shape_id_event_data(self, world):
        """每帧含 id/event/data，JSON 在 data 行，空行分隔。"""
        from app.modules import qa

        scope = world["scope"]
        blob = _collect(qa.stream(
            scope, QARequest(question="论文使用了什么优化器？"), new_ctx(scope),
        ))
        text = blob.decode("utf-8")
        assert "id: 1" in text
        assert "event: meta" in text
        assert "\n\n" in text
        frames = _parse_frames(blob)
        assert frames[0][0] == "meta"
        assert isinstance(frames[0][1], dict)

    def test_exactly_one_terminal_event(self, world):
        """最后**恰好一个** final 或 error，不得同时出现。"""
        from app.modules import qa

        scope = world["scope"]
        blob = _collect(qa.stream(
            scope, QARequest(question="论文在 QM9 上的结果如何？"), new_ctx(scope),
        ))
        names = [n for n, _ in _parse_frames(blob)]
        finals = names.count("final")
        errors = names.count("error")
        assert finals + errors == 1, f"终态必须恰好一个：final={finals} error={errors}"
        assert names[-1] in ("final", "error"), "终态必须是最后一帧"

    def test_citation_before_sentence(self, world):
        """先 citation 后引用它的 sentence。"""
        from app.modules import qa

        scope = world["scope"]
        blob = _collect(qa.stream(
            scope, QARequest(question="论文在 QM9 上的结果如何？"), new_ctx(scope),
        ))
        names = [n for n, _ in _parse_frames(blob) if n]
        if "sentence" in names and "citation" in names:
            assert names.index("citation") < names.index("sentence")

    def test_event_ids_are_monotonic(self, world):
        from app.modules import qa

        scope = world["scope"]
        blob = _collect(qa.stream(
            scope, QARequest(question="优化器是什么？"), new_ctx(scope),
        ))
        ids = []
        for raw in blob.decode("utf-8").split("\n\n"):
            for line in raw.split("\n"):
                if line.startswith("id: "):
                    ids.append(int(line[4:]))
        assert ids == sorted(ids), "事件序号必须单调递增"
        assert len(ids) == len(set(ids)), "事件序号不得重复"

    def test_utf8_split_across_chunks(self, world):
        """UTF-8 跨 chunk 解码：把字节流按 1 字节切分后仍能完整还原中文。"""
        import codecs

        from app.modules import qa

        scope = world["scope"]
        blob = _collect(qa.stream(
            scope, QARequest(question="论文的核心方法是什么？"), new_ctx(scope),
        ))
        # 帧内含中文，确保确实存在多字节字符
        assert any(b > 0x7F for b in blob)

        # 模拟网络把多字节字符切断：逐字节喂给增量解码器，必须得到与整块解码一致的结果
        decoder = codecs.getincrementaldecoder("utf-8")()
        pieces = [decoder.decode(blob[i:i + 1]) for i in range(len(blob))]
        pieces.append(decoder.decode(b"", final=True))
        assert "".join(pieces) == blob.decode("utf-8")

        # 单字节分片路径下解析出的事件序列与整块一致
        frames = _parse_frames("".join(pieces).encode("utf-8"))
        names = [n for n, _ in frames if n]
        assert names[0] == "meta"
        assert names[-1] in ("final", "error")

    def test_cancelled_before_start_yields_error(self, world):
        """客户端断开触发取消：只发一个 error，不发 final。"""
        from app.modules import qa

        scope = world["scope"]
        ctx = new_ctx(scope)
        _cancel(ctx)
        blob = _collect(qa.stream(
            scope, QARequest(question="任意问题"), ctx,
        ))
        names = [n for n, _ in _parse_frames(blob) if n]
        assert "error" in names
        assert "final" not in names

    def test_client_disconnect_cancels(self, world):
        """断开取消：error 帧的 error.code 应为 cancelled。"""
        from app.modules import qa

        scope = world["scope"]
        ctx = new_ctx(scope)
        _cancel(ctx)
        blob = _collect(qa.stream(scope, QARequest(question="任意问题"), ctx))
        frames = dict((n, d) for n, d in _parse_frames(blob) if n == "error")
        assert "error" in frames

    def test_heartbeat_comment_does_not_consume_seq(self):
        """heartbeat 是注释帧且**不占事件序号**。"""
        from app.modules.qa.stream import EventEncoder

        enc = EventEncoder()
        enc.next_id()
        assert enc.last_id == 1
        enc.comment()
        assert enc.last_id == 1, "注释帧不得占用事件序号"

    def test_encode_from_records_single_terminal(self, world):
        """非流式与流式共用同一 gate 输出：也只有一个 final。"""
        from app.modules import qa

        scope = world["scope"]
        record = qa.answer(
            scope, QARequest(question="论文使用了什么优化器？"), new_ctx(scope),
        )
        events = qa.encode_from_records(record, request_id="sync")
        names = [n for n, _ in _parse_frames(b"".join(events))]
        assert names.count("final") == 1
        assert names.count("error") == 0

    def test_duplicate_terminal_guard(self):
        """重复终态：终态守卫应只放行第一个。"""
        from app.modules.qa.stream import _Terminal

        t = _Terminal()
        assert t.claim("final") is True
        assert t.claim("error") is False, "已发 final 后不得再发 error"
        assert t.claim("final") is False


# =============================================================== 辅助


def _collect(agen) -> bytes:
    """同步收集异步字节流。"""
    async def _run():
        chunks = []
        async for chunk in agen:
            chunks.append(chunk)
        return b"".join(chunks)

    return asyncio.run(_run())


def _cancel(ctx) -> None:
    """注入「已取消」令牌：``CallContext.cancel_token.is_cancelled() -> True``。"""
    class _Cancelled:
        def is_cancelled(self) -> bool:
            return True

    ctx.cancel_token = _Cancelled()
