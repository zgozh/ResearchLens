"""M00 — ORM 汇总入口。

旧模型（models.py，V1.x 兼容）与重构后的 canonical 模型并存：迁移期两者都注册在
同一个 ``Base.metadata`` 上，旧表保留，新表按 Alembic 版本创建。
"""
from .models import (  # noqa: F401
    Claim,
    Evidence,
    Evaluation,
    Figure,
    GenerationJob,
    Narration,
    Paper,
    PaperPage,
    Question,
    ResearchGraphEdge,
    ResearchGraphNode,
    Scene,
    Section,
    Table,
)
from .source import (  # noqa: F401
    AssetORM,
    ModelSnapshotORM,
    RevisionORM,
    SourceDocumentORM,
)
from .artifacts import (  # noqa: F401
    AnchorORM,
    ArtifactBlobORM,
    BlockORM,
    MediaORM,
    PageLabelMappingORM,
    PageORM,
)
from .evidence import (  # noqa: F401
    AnswerORM,
    BindingORM,
    ClaimRecordORM,
    EvidenceRowORM,
    MapItemORM,
    MethodStepORM,
    SectionRecordORM,
    StatementORM,
    ValidationORM,
)
from .jobs import JobEventORM, JobORM, JobStageKeyORM  # noqa: F401
from .retrieval import ChunkORM, ChunkVectorORM  # noqa: F401
from .audit import (  # noqa: F401
    AuditLogORM,
    EvaluationReportORM,
    GoldenSetORM,
    ReviewORM,
)

#: 所有 canonical（重构后）模型的表名，供迁移与自检使用
CANONICAL_TABLES = [
    "source_documents", "revisions", "assets", "model_snapshots",
    "pages", "blocks", "anchors", "page_label_mappings", "media", "artifact_blobs",
    "statements", "claim_records", "evidence_records", "validations", "bindings",
    "section_records", "method_steps", "map_items", "answers",
    "jobs", "job_events", "job_stage_keys",
    "chunks", "chunk_vectors",
    "reviews", "audit_log", "evaluation_reports", "golden_sets",
]

__all__ = ["CANONICAL_TABLES"]
