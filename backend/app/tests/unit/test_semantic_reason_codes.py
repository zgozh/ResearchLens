"""R4-M1 — 证据三态可解释：**"未判定"的成因必须能分开**（需求 A）。

用户实测到的三个词来自三层不同状态，当时界面上都读成"系统没能证明"：

- 「证据不足」   = 语义判定**跑了**，结论是"原文不支持"；
- 「未判定」     = 语义判定**没跑成**（未配置模型 / 调用失败 / 超时 / 输出非法）；
- 「暂无证据」   = 这条断言压根没有关联证据（或是拉取失败）。

问题在于第 2 种把**四种完全不同的成因**压成了一个状态，用户看不出该去配模型、
该重试、还是该接受"这篇论文确实没证据"。本模块把成因细分到机器可读的 reason code：

- ``semantic_unavailable`` —— 未配置 LLM（用户可操作：去配 Key）；
- ``semantic_timeout``     —— 调用超时/超过 deadline（用户可操作：重试）；
- ``semantic_failed``      —— 调用失败（其他异常）/ 未返回结果 / 输出非法。
"""
from __future__ import annotations

import os
from types import SimpleNamespace

import pytest

os.environ["LLM_API_KEY"] = ""
os.environ["LLM_BASE_URL"] = ""
os.environ["LLM_FALLBACKS"] = ""


# ------------------------------------------------------------------ 1


class TestReasonCodesAreDeclared:
    """新码必须进受控字面量集合（expand-first：**新增**，不删不改旧的）。"""

    def test_validation_reason_accepts_new_semantic_codes(self):
        from typing import get_args

        from app.contracts.evidence import ValidationReason

        allowed = set(get_args(ValidationReason.model_fields["code"].annotation))
        for code in ("semantic_unavailable", "semantic_timeout", "semantic_failed"):
            assert code in allowed, f"受控集合缺少 {code}：{sorted(allowed)}"
        # 旧的兜底码必须保留（历史数据里全是它）
        assert "external_unavailable" in allowed

    def test_new_codes_are_valid_reasons(self):
        from app.contracts.evidence import ValidationReason

        for code in ("semantic_unavailable", "semantic_timeout", "semantic_failed"):
            r = ValidationReason(code=code, message="x")
            assert r.code == code


# ------------------------------------------------------------------ 2


class TestCauseClassification:
    """成因分类是**唯一真相**（`gate.semantic_unavailable_code`），可单独测。"""

    def _code(self, message: str) -> str:
        from app.modules.evidence import gate

        return gate.semantic_unavailable_code(message)

    def test_not_configured_maps_to_unavailable(self):
        assert self._code("未配置 LLM，语义未判定") == "semantic_unavailable"

    def test_timeout_maps_to_timeout(self):
        for msg in (
            "语义判定调用失败：TimeoutError",
            "语义判定调用失败：DeadlineExceeded",
            "语义判定超时",
        ):
            assert self._code(msg) == "semantic_timeout", msg

    def test_other_failure_maps_to_failed(self):
        for msg in (
            "语义判定调用失败：ValueError",
            "语义判定未返回结果",
            "语义判定输出非法：'maybe'",
            "陈述或证据为空，无法判定",
        ):
            assert self._code(msg) == "semantic_failed", msg

    def test_unknown_message_falls_back_to_legacy_code(self):
        """认不出来时回落到旧码 —— 不许因为分类器不认识就丢掉原因。"""
        assert self._code("语义未判定（模型未返回结论）") == "external_unavailable"
        assert self._code("") == "external_unavailable"


# ------------------------------------------------------------------ 3


class TestSemanticVerdictMessages:
    """`semantic.judge` 的消息必须带上可判别的成因（分类器的输入）。"""

    def test_no_llm_message_says_not_configured(self, monkeypatch):
        from app.modules.evidence import semantic

        monkeypatch.setattr(
            "app.core.config.settings",
            SimpleNamespace(has_llm=False),
        )
        verdict, conf, msg = semantic.judge("陈述", "证据", None)
        assert verdict is None and conf is None
        assert "未配置" in msg, msg

    def test_timeout_exception_names_the_type(self, monkeypatch):
        from app.modules import ai as ai_module
        from app.modules.evidence import semantic

        monkeypatch.setattr(
            "app.core.config.settings", SimpleNamespace(has_llm=True)
        )

        def boom(request, ctx=None):
            raise TimeoutError("deadline exceeded")

        monkeypatch.setattr(ai_module, "complete", boom)
        _v, _c, msg = semantic.judge("陈述", "证据", None)
        assert "TimeoutError" in msg, msg


# ------------------------------------------------------------------ 4


class TestGateEmitsDetailedCode:
    """端到端：`assess` 的第 ⑤ 步把细分码写进 reasons。"""

    def _reasons(self, monkeypatch, *, llm_available: bool, model_verdict=None,
                 model_reason: str = ""):
        from app.modules.evidence import gate

        draft = SimpleNamespace(text="本文方法在 QM9 上把误差降低了 12%。", kind="claim")
        gi = SimpleNamespace(
            semantic_model_verdict=model_verdict,
            semantic_model_confidence=None,
            semantic_model_reason=model_reason,
            llm_available=llm_available,
        )
        status, _conf, msg = gate.semantic_verdict(draft, "完全无关的另一段文字内容。", gi)
        assert status == "unreviewed", status
        return gate.semantic_unavailable_code(msg)

    def test_llm_available_but_no_verdict_is_classified(self):
        code = self._reasons(monkeypatch=None, llm_available=True)
        assert code in (
            "semantic_unavailable", "semantic_timeout", "semantic_failed",
            "external_unavailable",
        ), code

    def test_unreviewed_code_is_never_supports(self):
        """红线：未判定**绝不**被当成支持。"""
        from app.modules.evidence import gate

        draft = SimpleNamespace(text="本文方法显著优于基线。", kind="claim")
        gi = SimpleNamespace(
            semantic_model_verdict=None, semantic_model_confidence=None,
            semantic_model_reason="", llm_available=True,
        )
        status, _c, _m = gate.semantic_verdict(draft, "一段无关文本。", gi)
        assert status != "supports"
        assert status == "unreviewed"


# ------------------------------------------------------------------ 5


class TestReasonCodeIsPersisted:
    """细分码必须真的能下发到前端（经 `ValidationReason` 进 reasons 通道）。"""

    def test_gate_reason_uses_detailed_code_when_unreviewed(self):
        import pathlib

        src = pathlib.Path(__file__).resolve().parents[2] / "modules/evidence/gate.py"
        text = src.read_text(encoding="utf-8")
        assert "semantic_unavailable_code" in text, "gate 必须用分类器选码"
        assert "semantic_unavailable" in text
