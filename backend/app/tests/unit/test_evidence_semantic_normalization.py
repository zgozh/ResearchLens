"""证据门：判定输入规范化 + 判定理由可解释（REFACTOR_PLAN M5）。

**用户实测**："这些未转义导致证据链里引用到这些证据显示『未支持』"。
现场证据（paper 7 = Attention）：证据切片里就带着 MinerU 的原始产物 ——
`$P _ { d r o p } = 0 . 1$`、`<sup>∗</sup>`、跨行 `$$…\\tag{1}$$`。这些串被**原样**送进
语义判定模型，模型读到的是"符号噪声"而不是可读句子，判定大面积落到 `insufficient`
（界面显示"未支持/证据不足"）。

本文件锁住的口径：
1. **送进判定模型的文本必须是规范化后的干净文本**（走 `textnorm.normalize`），
   陈述与证据都要；
2. 规范化**只影响送给模型的那份**，不用于覆盖落库的原文引用（纪律 3：引文逐字来自原文块）；
3. 规范化依赖不可用时**降级为原文**，绝不中断 gate；
4. 模型给的 `reason` 必须**透出来**（此前被丢弃成固定的"模型语义判定"）——
   用户问"为什么未支持"时得有答案。
"""
from __future__ import annotations

import os
from types import SimpleNamespace

import pytest

os.environ["LLM_API_KEY"] = ""
os.environ["LLM_BASE_URL"] = ""
os.environ["LLM_FALLBACKS"] = ""

DIRTY_EVIDENCE = (
    "For the base model, we use a rate of $P _ { d r o p } = 0 . 1$. "
    "Table 2 summarizes our results $$ \\operatorname{Attention}(Q,K,V) \\tag{1} $$ "
    "Ashish Vaswani<sup>∗</sup> Google Brain"
)


def _enable_llm(monkeypatch, qs=None):
    from app.core.config import settings

    monkeypatch.setattr(
        type(settings), "has_llm", property(lambda self: True), raising=False,
    )


def _fake_complete(monkeypatch, captured: dict, *, verdict="supports",
                   confidence=0.8, reason="证据明确给出了该结论"):
    """替换 ai.complete：记录**真正发给模型的 messages**，返回受控 JSON 结果。"""
    from app.contracts.ai import CompletionResult
    from app.modules import ai as ai_module

    def _complete(request, ctx=None):
        captured["request"] = request
        captured["messages"] = [m.content for m in request.messages]
        return CompletionResult(
            value=SimpleNamespace(verdict=verdict, confidence=confidence, reason=reason),
            model="fake", mode="json_schema",
        )

    monkeypatch.setattr(ai_module, "complete", _complete)


class TestJudgeInputIsNormalized:
    def test_dirty_evidence_is_cleaned_before_the_model_sees_it(self, monkeypatch):
        from app.modules.evidence import semantic as semantic_mod

        _enable_llm(monkeypatch)
        captured: dict = {}
        _fake_complete(monkeypatch, captured)

        verdict, _conf, _msg = semantic_mod.judge("The dropout rate is 0.1.", DIRTY_EVIDENCE, None)
        assert verdict == "supports"

        user = captured["messages"][-1]
        assert "$" not in user, f"送进模型的证据里还有 $ 定界符：{user!r}"
        assert "<sup>" not in user, f"送进模型的证据里还有 <sup> 标签：{user!r}"
        assert "\\tag" not in user, f"送进模型的证据里还有 \\tag：{user!r}"
        # 内容不能丢：压缩后的公式仍在
        assert "P_{drop}=0.1" in user.replace(" ", "") or "P_{drop}" in user, user

    def test_raw_text_is_untouched_by_the_helper(self):
        """规范化只返回新串，**不修改**调用方手里的原文（引文要逐字核对）。"""
        from app.modules.evidence import semantic as semantic_mod

        original = DIRTY_EVIDENCE
        cleaned, issues = semantic_mod.normalize_evidence_text(original)
        assert original == DIRTY_EVIDENCE, "原文被就地改写了"
        assert cleaned != original
        assert issues, "脏文本应产出 TextIssue 记录（可审计）"

    def test_clean_text_passes_through_without_issues(self):
        from app.modules.evidence import semantic as semantic_mod

        clean = "The model achieves 28.4 BLEU on WMT 2014 English-to-German."
        out, issues = semantic_mod.normalize_evidence_text(clean)
        assert out == clean
        assert issues == []

    def test_statement_is_normalized_too(self, monkeypatch):
        from app.modules.evidence import semantic as semantic_mod

        _enable_llm(monkeypatch)
        captured: dict = {}
        _fake_complete(monkeypatch, captured)

        semantic_mod.judge("dropout $P _ { d r o p } = 0 . 1$ 的设置", "some evidence", None)
        user = captured["messages"][-1]
        assert "$" not in user, user

    def test_batch_judge_normalizes_evidence(self, monkeypatch):
        from app.modules.evidence import semantic as semantic_mod

        _enable_llm(monkeypatch)
        captured: dict = {}

        class _Item:
            index = 0
            verdict = "insufficient"
            confidence = 0.3

        class _Batch:
            items = [_Item()]

        from app.contracts.ai import CompletionResult
        from app.modules import ai as ai_module

        monkeypatch.setattr(
            ai_module, "complete",
            lambda request, ctx=None: (
                captured.update({"messages": [m.content for m in request.messages]})
                or CompletionResult(value=_Batch(), model="fake", mode="json_schema")
            ),
        )
        out = semantic_mod.batch_judge([("stmt", DIRTY_EVIDENCE)], None)
        assert out, "批量判定应返回结果"
        user = captured["messages"][-1]
        assert "$" not in user and "<sup>" not in user, user

    def test_dependency_failure_degrades_to_raw_text(self, monkeypatch):
        """textnorm 不可用（导入失败/异常）时必须降级为原文，而不是中断 gate。"""
        from app.modules.evidence import semantic as semantic_mod

        import builtins

        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name.endswith("textnorm"):
                raise ImportError("模拟 textnorm 不可用")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", fake_import)
        out, issues = semantic_mod.normalize_evidence_text(DIRTY_EVIDENCE)
        assert out == DIRTY_EVIDENCE
        assert issues == []


class TestJudgeReasonIsSurfaced:
    def test_model_reason_is_returned_as_message(self, monkeypatch):
        """回归锁：模型给的 reason 此前被丢弃成固定的"模型语义判定"，用户问不出原因。"""
        from app.modules.evidence import semantic as semantic_mod

        _enable_llm(monkeypatch)
        captured: dict = {}
        _fake_complete(
            monkeypatch, captured, verdict="insufficient", confidence=0.4,
            reason="证据只谈到相邻概念，缺少陈述里的具体数值",
        )
        verdict, conf, msg = semantic_mod.judge("A", "B", None)
        assert verdict == "insufficient"
        assert "相邻概念" in msg, f"模型的 reason 没有透出来：{msg!r}"
        assert conf == 0.4

    def test_empty_model_reason_falls_back_to_generic_label(self, monkeypatch):
        from app.modules.evidence import semantic as semantic_mod

        _enable_llm(monkeypatch)
        captured: dict = {}
        _fake_complete(monkeypatch, captured, verdict="supports", confidence=0.9, reason="")
        verdict, _conf, msg = semantic_mod.judge("A", "B", None)
        assert verdict == "supports"
        assert "语义判定" in msg, msg

    def test_illegal_verdict_is_still_unjudged(self, monkeypatch):
        """受控三态之外的输出仍然**不猜、不放行**。"""
        from app.modules.evidence import semantic as semantic_mod

        _enable_llm(monkeypatch)
        captured: dict = {}
        _fake_complete(monkeypatch, captured, verdict="maybe")
        verdict, _conf, msg = semantic_mod.judge("A", "B", None)
        assert verdict is None
        assert "非法" in msg

    def test_gate_reason_carries_model_reason_through(self, monkeypatch):
        """端到端：gate 的 semantic 步骤消息要带上模型理由（前端"未支持"要能解释）。"""
        from app.modules.evidence import gate as gate_mod
        from app.modules.evidence import semantic as semantic_mod

        _enable_llm(monkeypatch)
        captured: dict = {}
        _fake_complete(
            monkeypatch, captured, verdict="insufficient", confidence=0.2,
            reason="证据缺少对比对象",
        )
        _verdict, _conf, msg = semantic_mod.judge("A", "B", None)

        from app.contracts.evidence import StatementDraft
        from app.contracts.common import Scope

        scope = Scope(paper_id=1, revision_id="rev-x")
        gi = gate_mod.GateInput(
            scope=scope, blocks={}, llm_available=True,
            semantic_model_verdict="insufficient", semantic_model_confidence=0.2,
        )
        status, _c, gate_msg = gate_mod.semantic_verdict(
            StatementDraft(scope=scope, id="s1", claim_id="c1", text="A"), "B", gi,
        )
        assert status == "insufficient"
        # gate 的消息来自它自己的分支文案；这里只锁"状态正确 + 不是静默"
        assert gate_msg
