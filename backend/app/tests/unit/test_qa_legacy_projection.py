"""旧问答投影（`qa/legacy.py`）的两个真缺陷（ADR-0060）。

用户侧表现：问论文问题时 **HTTP 500**；问与论文无关的问题**仍然被拒答**（通用模式不生效）。

取证（容器内 traceback）：
1. ``AttributeError: 'AnchorSegment' object has no attribute 'block_id'``
   —— `qa/legacy.to_legacy_answer` 读 ``ev.source_region[0].block_id``。
   **同一个 bug 早前在 `schemas/adapters.py` 修过**（改成 `_legacy_region_label`），
   但 `qa/legacy.py` 里还有一份**副本**没修 → 只要答案带证据就 500。
2. ``_legacy_ctx -> None`` —— 旧入口不建 CallContext，于是
   ``_draft`` 走 ``llm_unavailable`` 抽取降级（**根本不用模型**），
   `_general_answer` 也因为没有 snapshot 直接返回 None（通用模式永远不触发）。
"""
from __future__ import annotations

import os
from types import SimpleNamespace

import pytest

os.environ["LLM_API_KEY"] = ""
os.environ["LLM_BASE_URL"] = ""
os.environ["LLM_FALLBACKS"] = ""

from app.contracts.common import Scope  # noqa: E402


def _evidence():
    """一条带 `source_region`（AnchorSegment）的证据 —— 触发过 500 的最小形状。"""
    from app.contracts.evidence import EvidenceRecord

    return EvidenceRecord(
        scope=Scope(paper_id=1, revision_id="rev-legacy-qa"),
        id="e1", legacy_id=1, claim_id="c1", source_document_id="",
        anchor_id="a1", source_page=7,
        source_region=[{
            "page_id": "pg1", "pdf_page_index": 6, "page_label": "7",
            "block_ids": ["b1"],
        }],
        source_text="原文片段",
        quote_spans=[],
        support_status="supports",
    )


def _record(*, with_evidence: bool):
    from app.contracts.evidence import ArtifactText
    from app.contracts.qa import AnswerRecord

    return AnswerRecord(
        scope=Scope(paper_id=1, revision_id="rev-legacy-qa"),
        id="ans1", question="本文的方法是什么？",
        text=ArtifactText(text="答案正文", spans=[]),
        statements=[], evidence=[_evidence()] if with_evidence else [],
        grounded=with_evidence, confidence="High", note="",
        mode="generated",
    )


class TestLegacyAnswerProjection:
    def test_evidence_region_does_not_crash(self):
        """**带证据的答案不得 500**（此前 AttributeError: block_id）。"""
        from app.modules.qa import legacy as qa_legacy

        resp = qa_legacy.to_legacy_answer(_record(with_evidence=True))
        assert resp.answer == "答案正文"
        assert len(resp.evidence) == 1
        region = resp.evidence[0].region
        assert isinstance(region, str) and region, f"region 必须给出可读定位，实际 {region!r}"

    def test_mode_is_passed_through(self):
        """``mode`` 必须透传：前端要靠它区分"通用回答"与"拒答"（ADR-0057）。"""
        from app.modules.qa import legacy as qa_legacy

        assert qa_legacy.to_legacy_answer(_record(with_evidence=True)).mode == "generated"

        general = _record(with_evidence=False).model_copy(update={"mode": "general"})
        assert qa_legacy.to_legacy_answer(general).mode == "general"

    def test_two_projections_agree(self):
        """`qa/legacy` 与 `schemas/adapters` 两处投影必须同口径（别再各写一份）。"""
        from app.modules.qa import legacy as qa_legacy
        from app.schemas import adapters

        rec = _record(with_evidence=True)
        a = qa_legacy.to_legacy_answer(rec)
        b = adapters.to_legacy_answer(rec)
        assert a.model_dump() == b.model_dump(), "两处投影结果不一致 = 迟早又只修一处"


@pytest.fixture
def real_scope():
    from app.contracts.documents import PaperCreate, SourceMetadata
    from app.modules import papers as papers_mod

    paper = papers_mod.create_paper(
        PaperCreate(title="旧问答上下文测试", source_mode="upload",
                    provenance_class="source_document")
    )
    source = papers_mod.store_source(
        paper.id, b"%PDF-1.4\n%%EOF\n", SourceMetadata(original_filename="q.pdf")
    )
    revision = papers_mod.create_revision(paper.id, source.id, "source")
    return Scope(paper_id=paper.id, revision_id=revision.id)


class TestLegacyCtxUsesModel:
    def test_legacy_ctx_carries_model_snapshot(self, real_scope):
        """旧入口必须带模型快照：否则永远走抽取降级、通用回答也永远不触发。"""
        from app.modules.qa import legacy as qa_legacy
        from app.modules.qa import repository as qa_repo
        from app.core.db import SessionLocal

        with SessionLocal() as db:
            found = qa_repo.paper_revision(db, real_scope.paper_id)
        assert found is not None
        ctx = qa_legacy._legacy_ctx(real_scope, found[1])
        assert ctx is not None, "旧入口此前 ctx=None → 不调用生成模型"
        assert getattr(ctx, "model_snapshot", None) is not None, \
            "ctx 必须带论文的模型快照（问答草稿与通用回答都依赖它）"
