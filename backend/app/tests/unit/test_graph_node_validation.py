"""R4-M9 — 图谱证据节点带 `validation`，前端四分类徽标才接得上（欠账 2）。

## 背景

`VerdictBadge`（R3-M2 做的四分类：非研究发现 / 真矛盾 / 有支持但未过其他检查 /
证据不足）需要 `validation{decision, semantic_status, reasons}` 三件套。
但图谱节点 props 里**只有 `support_status`** —— 于是徽标接不上，
用户在图谱上只能看到"未支持"这一个词，看不到**为什么**。

## 前科（必须防住）

`to_legacy_graph` 的白名单投影曾经把 `props.support_status` **丢掉**（实测发现），
所以本次加字段必须同步改**唯一实现** + `CONTRACT.md` 清单 + 双读一致性测试 ——
否则就是又一次"投影丢字段"。
"""
from __future__ import annotations

import os

import pytest

os.environ["LLM_API_KEY"] = ""
os.environ["LLM_BASE_URL"] = ""
os.environ["LLM_FALLBACKS"] = ""


# ------------------------------------------------------------------ 1


class TestEvidenceNodeProps:
    """节点 props 装配：有 validation 就带上，没有就是 None（不编造空判定）。"""

    def _row(self, **kw):
        from types import SimpleNamespace

        base = dict(
            id="ev1", support_status="insufficient", source_text="证据原文" * 10,
            source_page=3, anchor_id="a1", validation_id="v1",
        )
        base.update(kw)
        return SimpleNamespace(**base)

    def test_validation_is_included_when_present(self):
        from app.modules.graph.service import _evidence_node_props

        validation = {
            "decision": "rejected", "semantic_status": "supports",
            "reasons": [{"code": "numeric_mismatch", "message": "数字不一致"}],
        }
        props = _evidence_node_props(self._row(), validation)
        assert props["validation"] == validation
        # 旧字段一个都不能少（前端在用的）
        assert props["support_status"] == "insufficient"
        assert props["page"] == 3
        assert props["anchor_id"] == "a1"
        assert props["quote"]

    def test_validation_is_none_when_absent(self):
        """没有判定 → None（前端 `classifyVerdict(null)` 返回 null，不渲染徽标）。"""
        from app.modules.graph.service import _evidence_node_props

        props = _evidence_node_props(self._row(validation_id=None), None)
        assert props["validation"] is None, "不许编造一个空判定冒充实测结论"

    def test_props_are_json_serializable(self):
        """props 要能进 JSON（它是节点属性，会被序列化下发）。"""
        import json

        from app.modules.graph.service import _evidence_node_props

        props = _evidence_node_props(self._row(), {
            "decision": "verified", "semantic_status": "supports", "reasons": [],
        })
        assert json.loads(json.dumps(props)) == props


# ------------------------------------------------------------------ 2


class TestBatchFetchAvoidsNPlusOne:
    def test_batch_helper_exists_and_is_single_query(self):
        import pathlib
        import re

        src = (pathlib.Path(__file__).resolve().parents[2]
               / "modules/graph/service.py")
        text = src.read_text(encoding="utf-8")
        assert "_validations_for_evidence" in text, "必须有批量取判定的助手"
        # 批量实现里只应有一次 select（不是逐条查）
        block = text[text.index("def _validations_for_evidence"):]
        block = block[:block.index("\ndef ", 10)] if "\ndef " in block[10:] else block
        selects = len(re.findall(r"db\.execute\(", block))
        assert selects == 1, f"批量取判定应只有一次查询，实际 {selects} 次"

    def test_assembly_passes_validation_into_props(self):
        import pathlib

        src = (pathlib.Path(__file__).resolve().parents[2]
               / "modules/graph/service.py")
        text = src.read_text(encoding="utf-8")
        assert "validation_by_evidence.get(ev_id)" in text, (
            "装配处必须把批量结果传给 props（否则字段加了但永远是 None）"
        )


# ------------------------------------------------------------------ 3


class TestProjectionKeepsTheField:
    """投影侧：加字段必须同步改唯一实现 + CONTRACT.md（D-101/D-102 的教训）。"""

    def test_contract_documents_validation_field(self):
        import pathlib

        contract = (pathlib.Path(__file__).resolve().parents[2]
                    / "projection/CONTRACT.md")
        text = contract.read_text(encoding="utf-8")
        assert "validation" in text, (
            "CONTRACT.md 是投影字段清单的唯一真相；新字段必须登记，否则下次迁移又丢"
        )

    def test_legacy_graph_projection_keeps_props(self):
        """legacy 投影必须**整体透传** props（不能只挑几个键）。

        为什么这样断言：白名单式投影漏字段时 API 表面看不出异常，功能却整块失效
        （ADR-0058 / D-48 的真实前科）。正确的形态有两种：
        整体展开 `**props`，或显式列出全部键（含新字段）。
        """
        import pathlib
        import re

        root = pathlib.Path(__file__).resolve().parents[2]
        candidates = [
            root / "projection/graph.py",
            root / "modules/graph/legacy.py",
            root / "schemas/adapters.py",
        ]
        hits = [p for p in candidates if p.exists()]
        assert hits, "找不到 graph 的 legacy 投影实现"
        checked = 0
        for path in hits:
            text = path.read_text(encoding="utf-8")
            if '"props"' not in text:
                continue
            checked += 1
            spreads = re.search(r"\*\*\(?\s*dict\(\s*getattr\(\s*n,\s*[\"']props[\"']", text)
            named = "validation" in text
            assert spreads or named, (
                f"{path.name} 的 props 投影既不是整体透传、也没有显式列出 validation —— "
                f"这正是'投影丢字段'的前科形态"
            )
        assert checked > 0, "没有任何投影实现处理 props"
