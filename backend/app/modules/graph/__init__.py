"""M08 — 研究图谱模块（REFACTOR_SPEC §3.2、§5.5、§5.10、§6.10）。

由断言 + 证据构建 nodes/edges。核心红线：**无证据的断言不得统一连 supports 边**；
孤立 / candidate / disputed 节点保留明确 status；边端点同图同 scope；节点 ID 稳定；
GET 不调 LLM、不写库。

API:
- ``build(scope, claims, ctx) -> GraphArtifact``（canonical）
- ``get(scope) -> GraphArtifact``（canonical，只读）
- ``get_graph(db, paper_id) -> dict``（旧 HTTP 兼容投影，保留 React-Flow 字段）
"""
from .legacy import get_graph  # noqa: F401
from .service import ALGORITHM_VERSION, build, get  # noqa: F401

__all__ = ["build", "get", "get_graph", "ALGORITHM_VERSION"]
