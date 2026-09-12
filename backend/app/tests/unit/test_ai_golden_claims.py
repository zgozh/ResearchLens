"""AI 起草参考断言：**引文必须逐字来自原文**，且仍不是人工真值（ADR-0065）。

为什么要做：现在的参考集是"每块最像断言的一句"，与抽取产出的断言**内容不重合**
（paper 2 的 precision 只有 0.18），AI 语义裁判再准也没用——分母本身没对准。
用户指示"自动评测按你的建议改动"：让**模型读原文起草关键断言**，但守住两条纪律：

1. 每条参考断言必须带**逐字出现在原文块里**的 ``quote``，校验不过就丢弃
   （真值来源仍是原文，模型只是"起草"，不是自证）；
2. 集合仍标 ``is_tuning=True``（**AI 起草 ≠ 人工确认**），因此
   ``support_precision`` 依旧是 proxy、人工真值口径的 ``overall_score`` 依旧是 null。
"""
from __future__ import annotations

import os
from types import SimpleNamespace

import pytest

os.environ["LLM_API_KEY"] = ""
os.environ["LLM_BASE_URL"] = ""
os.environ["LLM_FALLBACKS"] = ""

BLOCK_A = "本文提出一种基于 Haar 小波域指标自适应选择载体的 JPEG 隐写方法,通过高阶范数度量图像高频成分."
BLOCK_B = "实验在 BOSS v0.92 与 BOSS v1.01 图像库上进行,每次随机选取 1000 张图像用于测试."


@pytest.fixture
def world():
    import uuid

    from app.contracts.common import Scope
    from app.contracts.documents import PaperCreate, SourceMetadata
    from app.core import db as db_mod
    from app.models.artifacts import BlockORM, PageORM
    from app.modules import papers as papers_mod

    paper = papers_mod.create_paper(
        PaperCreate(title="AI 参考断言", source_mode="upload",
                    provenance_class="source_document")
    )
    source = papers_mod.store_source(
        paper.id, b"%PDF-1.4\n%%EOF\n", SourceMetadata(original_filename="ai.pdf")
    )
    revision = papers_mod.create_revision(paper.id, source.id, "source")
    scope = Scope(paper_id=paper.id, revision_id=revision.id)
    with db_mod.SessionLocal() as db:
        page = PageORM(id=f"pg-{uuid.uuid4().hex[:8]}", paper_id=paper.id,
                       revision_id=revision.id, pdf_page_index=0,
                       width_pt=595.0, height_pt=842.0)
        db.add(page)
        db.flush()
        for i, text in enumerate((BLOCK_A, BLOCK_B)):
            db.add(BlockORM(id=f"blk-{uuid.uuid4().hex[:8]}", paper_id=paper.id,
                            revision_id=revision.id, page_id=page.id, ordinal=i,
                            kind="paragraph", text=text, origin="source_extraction",
                            section_path=["1 方法"] if i == 0 else ["5 实验"]))
        db.commit()
    return scope


def _canned(items, monkeypatch):
    """让 golden_builder 里的 LLM 返回受控的"起草结果"。"""
    from app.modules import ai as ai_module
    from app.core.config import settings

    monkeypatch.setattr(type(settings), "has_llm", property(lambda self: True), raising=False)
    monkeypatch.setattr(
        ai_module, "complete",
        lambda request, ctx=None: SimpleNamespace(
            value=SimpleNamespace(claims=[SimpleNamespace(**c) for c in items]),
            model="fake",
        ),
    )


class TestAiGoldenClaims:
    def test_claims_require_verbatim_quote(self, world, monkeypatch):
        """引文不逐字出现在原文里的"起草断言"必须被丢弃（真值只能来自原文）。"""
        from app.contracts.common import new_ctx
        from app.modules.evaluation import golden_builder

        _canned([
            {"text": "Haar 小波域指标用于优选载体", "quote": "基于 Haar 小波域指标自适应选择载体",
             "section": "1 方法"},
            {"text": "模型自己编的一条", "quote": "这句话原文里根本没有出现过", "section": "1 方法"},
        ], monkeypatch)
        golden = golden_builder.build_golden_set_ai(world, new_ctx(world))
        texts = [c.text for c in golden.claims]
        assert any("Haar" in t for t in texts), f"合法起草应保留：{texts}"
        assert not any("编" in t for t in texts), f"引文对不上的必须丢弃：{texts}"

    def test_claims_carry_acceptable_blocks(self, world, monkeypatch):
        """每条参考断言要能定位回**具体块**（供审计与锚点）。"""
        from app.contracts.common import new_ctx
        from app.modules.evaluation import golden_builder

        _canned([{"text": "口号", "quote": "基于 Haar 小波域指标自适应选择载体",
                  "section": "1 方法"}], monkeypatch)
        golden = golden_builder.build_golden_set_ai(world, new_ctx(world))
        assert golden.claims and golden.claims[0].acceptable_block_ids, "必须声明来源块"

    def test_no_llm_means_empty_not_fabricated(self, world):
        """没有模型时**不产出任何参考断言**（不退回句子挑选冒充 AI 起草）。"""
        from app.contracts.common import new_ctx
        from app.modules.evaluation import golden_builder

        golden = golden_builder.build_golden_set_ai(world, new_ctx(world))
        assert golden.claims == []

    def test_version_is_distinct_from_sentence_builder(self, world, monkeypatch):
        from app.contracts.common import new_ctx
        from app.modules.evaluation import golden_builder

        _canned([{"text": "口号", "quote": "实验在 BOSS v0.92 与 BOSS v1.01 图像库上进行",
                  "section": "5 实验"}], monkeypatch)
        golden = golden_builder.build_golden_set_ai(world, new_ctx(world))
        assert golden.version != golden_builder.GOLDEN_VERSION
        assert "ai" in golden.version.lower()

    def test_saved_ai_set_keeps_deterministic_parts(self, world, monkeypatch):
        """**题目/锚点必须来自确定性构造**：AI 只起草 claims，否则拒答率没有分母（ADR-0065）。"""
        from app.contracts.common import new_ctx
        from app.core.db import session_scope
        from app.modules.evaluation import golden_builder

        _canned([{"text": "口号", "quote": "基于 Haar 小波域指标自适应选择载体",
                  "section": "1 方法"}], monkeypatch)
        saved = golden_builder.build_and_save_ai(world, new_ctx(world))
        assert saved.claims, "AI claims 应保存"
        with session_scope() as db:
            found = golden_builder.find_for_scope(db, world)
        assert found is not None
        assert found.version == golden_builder.AI_GOLDEN_VERSION, "存回来的应还是 AI 版"
        assert isinstance(found.questions, list), "题目字段必须在"
        assert isinstance(found.anchors, list), "锚点字段必须在"

    def test_ai_set_is_preferred_over_sentence_set(self, world, monkeypatch):
        """两版都在时**必须优先 AI 版**：此前只看 created_at，重建句子版就会悄悄换回去。"""
        from app.contracts.common import new_ctx
        from app.core.db import session_scope
        from app.modules.evaluation import golden_builder

        _canned([{"text": "AI 起草的断言", "quote": "基于 Haar 小波域指标自适应选择载体",
                  "section": "1 方法"}], monkeypatch)
        golden_builder.build_and_save_ai(world, new_ctx(world))
        # 再建一份句子版（它更新，但**不该**因此被评测采用）
        golden_builder.build_and_save(world)
        with session_scope() as db:
            found = golden_builder.find_for_scope(db, world)
        assert found is not None
        assert found.version == golden_builder.AI_GOLDEN_VERSION, \
            f"应优先 AI 版，实际用了 {found.version}"

    def test_human_confirmed_wins_over_ai(self, world, monkeypatch):
        """人工确认过的版本优先级最高（AI 起草不能盖过人工真值）。"""
        from app.contracts.common import new_ctx
        from app.core.db import session_scope
        from app.modules.evaluation import golden_builder

        _canned([{"text": "AI 起草的断言", "quote": "基于 Haar 小波域指标自适应选择载体",
                  "section": "1 方法"}], monkeypatch)
        golden_builder.build_and_save(world, annotated=True)   # 人工确认版（句子版）
        golden_builder.build_and_save_ai(world, new_ctx(world))  # AI 版
        with session_scope() as db:
            found, is_tuning = golden_builder.find_for_scope_ex(db, world)
        assert found is not None and is_tuning is False, "人工确认版必须优先"

