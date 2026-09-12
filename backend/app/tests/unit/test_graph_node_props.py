"""图谱投影层**不许静默丢字段**，且节点要带够展示事实（ADR-0058）。

用户实测反馈两条：
1. "图表节点没有给出具体的图表" —— 根因是 `graph/legacy.to_legacy_graph` 的 props
   **白名单里没有 `media_id`**，前端"图表节点"分支永远拿不到 id。这与 D-48
   （`_legacy_step` 丢掉 `figure_refs`）是同一类缺陷：白名单式投影漏一个字段，
   API 表面毫无异常，功能整块失效。
2. "证据节点只有一个'可定位锚点 1 个'标签" —— 节点没带**判定/引文/页码**，
   前端除了数锚点个数无话可说。
"""
from __future__ import annotations

from types import SimpleNamespace

from app.contracts.common import Scope
from app.contracts.evidence import ArtifactText
from app.contracts.graph import GraphArtifact, GraphNodeRecord
from app.modules.graph import legacy as graph_legacy

SCOPE = Scope(paper_id=1, revision_id="rev-graph-props")


def _artifact() -> GraphArtifact:
    return GraphArtifact(
        scope=SCOPE, id="g1",
        nodes=[
            GraphNodeRecord(
                id="n:media:m1", kind="media", label=ArtifactText(text="图 3 消融实验"),
                media_id="m1", status="verified",
                props={"media_kind": "figure", "legacy_no": 3, "caption": "消融实验"},
            ),
            GraphNodeRecord(
                id="n:evidence:e1", kind="evidence", label=ArtifactText(text="原文片段"),
                evidence_id="e1", anchor_ids=["a1"], status="verified",
                props={"support_status": "supports", "quote": "原文片段", "page": 7},
            ),
        ],
        edges=[],
    )


class TestGraphProjectionKeepsMediaId:
    def test_legacy_props_include_media_id(self):
        out = graph_legacy.to_legacy_graph(_artifact())
        media = [n for n in out["nodes"] if n["kind"] == "media"][0]
        assert media["props"].get("media_id") == "m1", \
            "投影层丢掉 media_id → 前端图表节点整块失效"

    def test_node_own_props_are_passed_through(self):
        out = graph_legacy.to_legacy_graph(_artifact())
        media = [n for n in out["nodes"] if n["kind"] == "media"][0]
        assert media["props"].get("legacy_no") == 3
        assert media["props"].get("caption") == "消融实验"

    def test_evidence_node_carries_verdict_and_page(self):
        out = graph_legacy.to_legacy_graph(_artifact())
        ev = [n for n in out["nodes"] if n["kind"] == "evidence"][0]
        assert ev["props"].get("support_status") == "supports"
        assert ev["props"].get("page") == 7
        assert ev["props"].get("anchor_ids") == ["a1"]


class TestNodePropBuilders:
    def test_media_props_from_snapshot(self):
        from app.modules.graph import service as gs

        row = SimpleNamespace(id="m1", kind="figure", legacy_no=3, label="图 3 消融")
        props = gs._media_node_props(row)
        assert props["media_id"] == "m1"
        assert props["legacy_no"] == 3
        assert props["media_kind"] == "figure"

    def test_evidence_props_from_snapshot(self):
        from app.modules.graph import service as gs

        row = SimpleNamespace(id="e1", anchor_id="a1", source_text="原文片段",
                              support_status="contradicts", source_page=7)
        props = gs._evidence_node_props(row)
        assert props["support_status"] == "contradicts"
        assert props["page"] == 7
        assert props["anchor_id"] == "a1"
