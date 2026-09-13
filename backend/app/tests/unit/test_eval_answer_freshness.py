"""两处"过期数据掩盖改进"的回归测试（ADR-0054）。

1. **评测读最旧的答案**：`list_answers` 按 ``created_at`` **升序**返回，而
   ``honesty_metrics`` 用 ``seen`` 去重、**先到先得** → 同一问题重跑后，**旧答案赢**。
   实测后果：修好检索后重跑题库，仍按旧的记录算分。
2. **QA 缓存键不含检索版本**：``cache_key`` 有 source/model/prompt/gate，独缺检索算法版本
   → 检索行为变了，旧答案照样命中缓存返回（"改了没生效"的经典成因）。
"""
from __future__ import annotations

import os
from types import SimpleNamespace

os.environ["LLM_API_KEY"] = ""
os.environ["LLM_BASE_URL"] = ""
os.environ["LLM_FALLBACKS"] = ""

from app.contracts.common import Scope  # noqa: E402
from app.contracts.documents import SourceMetadata  # noqa: E402
from app.contracts.evaluation import GoldenQuestion  # noqa: E402
from app.modules.evaluation import metrics as M  # noqa: E402

_SCOPE = Scope(paper_id=1, revision_id="rev-stale")


def _golden(question: str, answerable: bool) -> GoldenQuestion:
    return GoldenQuestion(id=f"g-{question}", scope=_SCOPE, question=question,
                          answerable=answerable)


def _qa(question: str, *, mode: str, statements=(), text: str = ""):
    return SimpleNamespace(question=question, mode=mode, statements=list(statements),
                           text=SimpleNamespace(text=text), grounded=False,
                           warnings=[], usage=SimpleNamespace(elapsed_ms=1))


class TestNewestAnswerWins:
    """R4-M3 改写：指标从"拒答率"换成"不可答题诚实率"，但**取最新一条**这条不变量不变。

    原语义为什么失效：旧断言用 ``answerable_false_refusal_rate``（可答题被误拒）来验证
    "最新一条赢"。决策 1 之后该指标与"拒答"动作一并删除，可答题也不再进分母。
    新口径下仍能完整验证同一件事：同一问题重跑后，**以最新一条的诚实与否为准**。
    """

    def test_newest_answer_wins_over_oldest(self):
        """先如实说明、后给出编造作答 → 以**最新**一条为准 → 诚实率 0。"""
        q = "本文是如何使用 Kubernetes 完成实验与部署的？"
        answers = [
            _qa(q, mode="not_mentioned", text="论文中没有提到 Kubernetes。"),  # 旧：如实
            _qa(q, mode="generated", statements=["s"], text="用了 Kubernetes。"),  # 新：编造
        ]
        entry = M.honesty_metrics(answers, [_golden(q, False)])
        assert entry.value.value == 0.0, "应以**最新**一条为准"
        assert entry.value.denominator == 1.0, "同一问题只能算一票"

    def test_latest_answer_can_also_be_honest(self):
        """反过来也一样：先编造、后如实 → 记 1（不是只挑好看的）。"""
        q = "不可回答问题"
        answers = [
            _qa(q, mode="generated", statements=["s"], text="编的"),
            _qa(q, mode="not_mentioned", text="论文中没有提到 X。"),
        ]
        entry = M.honesty_metrics(answers, [_golden(q, False)])
        assert entry.value.value == 1.0

    def test_unanswerable_uses_latest(self):
        q = "本文是如何使用 Kubernetes 完成实验与部署的？"
        answers = [
            _qa(q, mode="generated", statements=["幻觉"], text="编的"),  # 旧：答了（错）
            _qa(q, mode="not_mentioned", text="论文中没有提到。"),        # 新：如实
        ]
        entry = M.honesty_metrics(answers, [_golden(q, False)])
        assert entry.value.value == 1.0

    def test_latest_answers_helper_keeps_order_and_dedups(self):
        a = _qa("q1", mode="not_mentioned")
        b = _qa("q2", mode="not_mentioned")
        a2 = _qa("q1", mode="generated", statements=["s"])
        picked = M.latest_answers([a, b, a2])
        assert [x.question for x in picked] == ["q1", "q2"]
        assert picked[0] is a2, "同问题取最后一条（list_answers 是时间升序）"

    def test_timing_does_not_double_count_reasked_questions(self):
        """重复问过的问题，计时只算最新一次，否则 token/时延被灌水。"""
        old = _qa("q1", mode="not_mentioned")
        old.usage = SimpleNamespace(elapsed_ms=10_000)
        new = _qa("q1", mode="generated", statements=["s"])
        new.usage = SimpleNamespace(elapsed_ms=1_000)
        entries = {e.name: e.value for e in M.timing_metrics(M.latest_answers([old, new]))}
        assert entries["qa_total_ms"].value == 1_000.0


class TestCacheKeyCoversRetrievalVersion:
    def test_key_changes_with_retrieval_version(self):
        from app.modules.qa import repository as repo

        base = dict(revision_id="r1", question="q", model_snapshot_id="m", top_k=5)
        v2 = repo.cache_key(**base, retrieval_version="rl.retrieval/2")
        v3 = repo.cache_key(**base, retrieval_version="rl.retrieval/3")
        assert v2 != v3, "检索版本变化必须得到新键，否则旧答案掩盖检索改动"

    def test_same_inputs_same_key(self):
        from app.modules.qa import repository as repo

        base = dict(revision_id="r1", question="q", model_snapshot_id="m", top_k=5,
                    retrieval_version="rl.retrieval/3")
        assert repo.cache_key(**base) == repo.cache_key(**base)

    def test_service_passes_live_retrieval_version(self):
        from app.modules import retrieval
        from app.modules.qa import service as qs

        assert qs._retrieval_version() == retrieval.ALGORITHM_VERSION


class TestReaskActuallyPersists:
    """**重算出来的答案必须真的写进库**（ADR-0054 的第三个坑）。

    实测：`answer_id` 由 (revision, question) 确定性派生，重问时 `db.add` 撞主键 →
    `IntegrityError` → 被 `_persist` 的 `except Exception: pass` 静默吞掉。
    于是"重算成功（4 句）但库里还是旧的 abstained 行"，评测与前端永远看不到修复。
    另外 `_persist` 还会**自己再算一次键**（且写死 `top_k=5`），与读路径的键不一致。
    """

    def test_insert_answer_upserts_same_id(self):
        """同一 answer_id 写两次 → 第二次内容生效，且不新增行、不抛异常。"""
        from app.contracts.documents import PaperCreate
        from app.core import db as db_mod
        from app.modules import papers as papers_mod
        from app.modules.qa import repository as repo

        paper = papers_mod.create_paper(
            PaperCreate(title="upsert 测试", source_mode="upload",
                        provenance_class="source_document")
        )
        source = papers_mod.store_source(
            paper.id, b"%PDF-1.4\n%%EOF\n", SourceMetadata(original_filename="u.pdf")
        )
        revision = papers_mod.create_revision(paper.id, source.id, "source")
        scope = Scope(paper_id=paper.id, revision_id=revision.id)

        with db_mod.SessionLocal() as db:
            repo.insert_answer(
                db, answer_id="a-fixed", paper_id=paper.id, revision_id=revision.id,
                question="q", payload={"mode": "not_mentioned", "text": {"text": ""}},
                cache_key_value="k1",
            )
            repo.insert_answer(
                db, answer_id="a-fixed", paper_id=paper.id, revision_id=revision.id,
                question="q", payload={"mode": "generated", "text": {"text": "新答案"}},
                cache_key_value="k2",
            )
            rows = [r for r in repo.list_answers(db, revision.id) if r.id == "a-fixed"]
            assert len(rows) == 1, "同一问题只应有一行"
            assert rows[0].mode == "generated", "第二次写入必须生效"
            assert rows[0].cache_key == "k2"

    def test_persist_uses_caller_key_verbatim(self, monkeypatch):
        """`_persist` 必须原样使用调用方算好的键（不得自己再算一遍）。"""
        from app.modules.qa import repository as repo
        from app.modules.qa import service as qs

        captured = {}
        monkeypatch.setattr(repo, "insert_answer", lambda db, **kw: captured.update(kw))
        scope = Scope(paper_id=1, revision_id="rev-key")
        record = SimpleNamespace(id="a1", question="q", model_snapshot_id=None,
                                 model_dump=lambda mode="json": {})
        qs._persist(scope, record, "digest", "KEY-FROM-CALLER")
        assert captured["cache_key_value"] == "KEY-FROM-CALLER"
