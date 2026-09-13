"""M00 — Evidence-first、断言与生成产物契约（REFACTOR_SPEC §5.4、§5.9）。"""
from __future__ import annotations

from datetime import datetime
from typing import Any, List, Literal, Optional

from pydantic import Field, model_validator

from .artifacts import Media
from .common import (
    AnchorId,
    ArtifactRef,
    BlockId,
    ContractModel,
    Hash,
    Id,
    LegacyEvidenceId,
    MediaId,
    RevisionId,
    Scope,
    Score,
    SourceRef,
    StatementId,
    Warning,
)
from .documents import AnchorSegment, QuoteSpan

#: 公开陈述身份：非空 ASCII，≤32，旧 claim_07 保留
PublicClaimId = str

ClaimType = Literal["RESULT", "METHOD", "LIMITATION", "CONTEXT"]
ClaimStatus = Literal["verified", "inference", "contested", "unverified", "rejected"]
SupportStatus = Literal["supports", "contradicts", "insufficient", "unreviewed"]
Decision = Literal["verified", "inference", "contested", "unverified", "rejected"]
DisplayClass = Literal[
    "verified_fact", "attributed_quote", "inference", "unverified", "transition"
]


class CitationCandidate(ContractModel):
    """LLM 只能选择已提供的块 ID，不允许生成可信页码/坐标。"""

    block_id: BlockId
    proposed_quote: str = ""
    media_id: Optional[MediaId] = None


class StatementDraft(ContractModel):
    """claim_id 为公开陈述身份；新事实（讲解/QA）也必须注册。"""

    scope: Scope
    id: StatementId
    claim_id: str = Field(max_length=32)
    text: str
    kind: Literal["fact", "inference", "quote", "transition"] = "fact"
    citations: List[CitationCandidate] = Field(default_factory=list)
    qualifiers: List[str] = Field(default_factory=list)


class EvidenceRecord(ContractModel):
    """source_text 由服务端原文拼接；未能定位者不创建假的 EvidenceRecord。"""

    scope: Scope
    id: Id
    legacy_id: Optional[LegacyEvidenceId] = None
    claim_id: str = Field(max_length=32)
    source_document_id: Id
    anchor_id: AnchorId
    source_page: int = Field(ge=1)
    source_region: List[AnchorSegment] = Field(default_factory=list)
    source_text: str = ""
    quote_spans: List[QuoteSpan] = Field(default_factory=list)
    media_ids: List[MediaId] = Field(default_factory=list)
    confidence: Optional[Score] = None
    confidence_method: Optional[str] = None
    locator_status: Literal["exact", "page_only"] = "exact"
    support_status: SupportStatus = "unreviewed"
    validation_id: Optional[Id] = None


class ValidationReason(ContractModel):
    code: Literal[
        "missing_source", "wrong_scope", "quote_mismatch", "ambiguous_page",
        "coordinate_missing", "unsupported_entailment", "numeric_mismatch",
        "qualifier_missing", "contradiction", "budget_exhausted",
        "external_unavailable", "passed",
        # R4-M1（需求 A）：把"语义未判定"这一条**细分到成因**，因为界面上的
        # 「未判定」原本把四种完全不同的情况压成一个状态：
        #   · semantic_unavailable —— 未配置 LLM（用户可操作：去配 Key）
        #   · semantic_timeout     —— 调用超时 / 超过 deadline（用户可操作：重试）
        #   · semantic_failed      —— 调用失败（其他异常）/ 未返回结果 / 输出非法
        # 全是**新增**码（expand-first）：旧码 `external_unavailable` 保留为兜底，
        # 历史数据不受影响。
        "semantic_unavailable", "semantic_timeout", "semantic_failed",
    ]
    message: str = ""
    block_ids: List[BlockId] = Field(default_factory=list)


class ValidationReport(ContractModel):
    scope: Scope
    id: Id
    statement_id: StatementId
    locator_valid: bool = False
    quote_valid: bool = False
    scope_valid: bool = False
    semantic_status: SupportStatus = "unreviewed"
    numeric_status: Literal["pass", "fail", "not_applicable", "unreviewed"] = "unreviewed"
    qualifier_status: Literal["pass", "fail", "unreviewed"] = "unreviewed"
    decision: Decision = "unverified"
    evidence: List[EvidenceRecord] = Field(default_factory=list)
    reasons: List[ValidationReason] = Field(default_factory=list)
    assessor: Literal["rule", "model", "human"] = "rule"
    assessor_version: str = ""
    confidence: Optional[Score] = None
    created_at: Optional[datetime] = None

    @property
    def passed(self) -> bool:
        return self.decision in ("verified", "inference")


class VerifiedStatement(ContractModel):
    """保留候选引用只作审计，公开展示依赖 evidence_ids。"""

    scope: Scope
    id: StatementId
    claim_id: str = Field(max_length=32)
    text: str
    kind: Literal["fact", "inference", "quote", "transition"] = "fact"
    citations: List[CitationCandidate] = Field(default_factory=list)
    qualifiers: List[str] = Field(default_factory=list)
    validation: Optional[ValidationReport] = None
    evidence_ids: List[Id] = Field(default_factory=list)
    origin: Literal["generated", "source_extraction"] = "generated"
    display_class: DisplayClass = "unverified"

    @classmethod
    def from_draft(
        cls, draft: StatementDraft, validation: ValidationReport,
        evidence_ids: List[Id] | None = None,
        origin: str = "generated",
    ) -> "VerifiedStatement":
        return cls(
            scope=draft.scope, id=draft.id, claim_id=draft.claim_id, text=draft.text,
            kind=draft.kind, citations=draft.citations, qualifiers=draft.qualifiers,
            validation=validation, evidence_ids=list(evidence_ids or []), origin=origin,
            display_class=display_class_for(draft, validation),
        )


def display_class_for(draft: StatementDraft, validation: ValidationReport) -> str:
    """由 gate 结果决定展示类别；无依据候选一律 unverified。"""
    decision = validation.decision
    if draft.kind == "transition" and decision != "rejected":
        return "transition"
    if decision == "verified":
        return "attributed_quote" if draft.kind == "quote" else "verified_fact"
    if decision == "inference":
        return "inference"
    return "unverified"


class ClaimRecord(ContractModel):
    """QA 新陈述默认 answer_only，不污染六展项的断言列表。"""

    scope: Scope
    id: Id
    legacy_id: Optional[int] = None
    claim_id: str = Field(max_length=32)
    statement_id: StatementId
    type: ClaimType = "RESULT"
    status: ClaimStatus = "unverified"
    rationale: str = ""
    evidence_ids: List[Id] = Field(default_factory=list)
    confidence: Optional[Score] = None
    visibility: Literal["exhibit", "answer_only"] = "exhibit"


class Binding(ContractModel):
    scope: Scope
    id: Id
    from_: ArtifactRef = Field(alias="from")
    to: ArtifactRef | SourceRef
    relation: Literal["supports", "contradicts", "illustrates", "mentions"]
    method: Literal[
        "explicit_block_ref", "caption_ref", "verified_claim_join", "manual", "legacy_candidate",
        # 位置兜底：与断言同页/相邻页的图表（低分、**必须**在 UI 标明是位置推断，ADR-0059）。
        # 之所以要显式加进 Literal：它是**受控枚举**，不在列表里的值会让整条绑定校验失败
        # （实测：兜底绑定曾因此一条都没落库，而调用方的 except 把异常吞了）。
        "page_proximity",
    ] = "explicit_block_ref"
    validation_id: Optional[Id] = None
    state: Literal["verified", "candidate", "rejected"] = "candidate"
    reason: str = ""
    score: Optional[Score] = None
    created_at: Optional[datetime] = None

    model_config = {"extra": "forbid", "populate_by_name": True}


class StatementSpan(ContractModel):
    """不重叠、按序，所指 statement 文本与切片一致。"""

    start_cp: int = Field(ge=0)
    end_cp: int = Field(gt=0)
    statement_id: StatementId


class ArtifactText(ContractModel):
    """完整覆盖所有非空白文字，禁止摘要正文之外的“无引用副文案”。"""

    text: str = ""
    spans: List[StatementSpan] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check(self) -> "ArtifactText":
        last = -1
        for sp in self.spans:
            if sp.start_cp < last:
                raise ValueError("spans 必须按序且不重叠")
            if sp.end_cp > len(self.text):
                raise ValueError("span 超出文本长度")
            last = sp.end_cp
        return self


class MapItem(ContractModel):
    id: Id
    kind: Literal["problem", "method", "result", "limitation"]
    text: ArtifactText
    claim_ids: List[str] = Field(default_factory=list)
    anchor_ids: List[AnchorId] = Field(default_factory=list)


class MapArtifact(ContractModel):
    scope: Scope
    id: Id
    items: List[MapItem] = Field(default_factory=list)


class SectionRecord(ContractModel):
    scope: Scope
    id: Id
    heading: str
    kind: str = "body"
    source_block_ids: List[BlockId] = Field(default_factory=list)
    anchor_ids: List[AnchorId] = Field(default_factory=list)
    summary: ArtifactText = Field(default_factory=ArtifactText)
    key_points: List[ArtifactText] = Field(default_factory=list)


class MethodStepRecord(ContractModel):
    """MethodStep.id 必填（§6.8）。"""

    scope: Scope
    id: Id
    order: int = Field(ge=0)
    label: ArtifactText
    detail: ArtifactText
    phase: Optional[str] = None
    claim_ids: List[str] = Field(default_factory=list)
    media_ids: List[MediaId] = Field(default_factory=list)
    binding_ids: List[Id] = Field(default_factory=list)


class StructureArtifact(ContractModel):
    scope: Scope
    sections: List[SectionRecord] = Field(default_factory=list)
    map: Optional[MapArtifact] = None
    method_steps: List[MethodStepRecord] = Field(default_factory=list)


class ClaimDraftBatch(ContractModel):
    scope: Scope
    drafts: List[StatementDraft] = Field(default_factory=list)
    warnings: List[Warning] = Field(default_factory=list)


class ClaimBuildResult(ContractModel):
    scope: Scope
    claims: List[ClaimRecord] = Field(default_factory=list)
    statements: List[VerifiedStatement] = Field(default_factory=list)
    warnings: List[Warning] = Field(default_factory=list)


# --------------------------------------------------------------- 旧引用解析


class LegacyRef(ContractModel):
    text: str
    page: Optional[int] = None
    region: Optional[str] = None


class ResolutionReport(ContractModel):
    """resolved 仅表示定位已解出，不表示支持已验证。"""

    scope: Scope
    resolved: List[SourceRef] = Field(default_factory=list)
    candidates: List[Any] = Field(default_factory=list)   # MediaLinkCandidate
    unresolved: List[LegacyRef] = Field(default_factory=list)
    warnings: List[Warning] = Field(default_factory=list)


# --------------------------------------------------------------- 复核与导出


class ReviewRequest(ContractModel):
    scope: Scope
    target: ArtifactRef | SourceRef
    decision: Literal["confirm", "reject", "correct_page_label"]
    reason: str
    corrected_page_index: Optional[int] = None
    page_label: Optional[str] = None
    expected_validation_id: Optional[Id] = None

    @model_validator(mode="after")
    def _check(self) -> "ReviewRequest":
        if self.decision == "correct_page_label":
            if self.corrected_page_index is None or self.page_label is None:
                raise ValueError("correct_page_label 需要 page_label 与 corrected_page_index")
            if self.corrected_page_index < 0:
                raise ValueError("corrected_page_index 必须 >= 0")
        if not (self.reason or "").strip():
            raise ValueError("reason 必填")
        return self


class ReviewRecord(ContractModel):
    id: Id
    request: ReviewRequest
    reviewer: str
    created_at: Optional[datetime] = None
    applied_revision_id: Optional[RevisionId] = None
    job_id: Optional[int] = None


class EvidenceExport(ContractModel):
    """资产仅列清单，不内嵌论文全文/PDF/base64。"""

    schema_version: str = "rl.contract/1"
    scope: Scope
    source_sha256: Optional[Hash] = None
    claims: List[ClaimRecord] = Field(default_factory=list)
    statements: List[VerifiedStatement] = Field(default_factory=list)
    evidence: List[EvidenceRecord] = Field(default_factory=list)
    media: List[Media] = Field(default_factory=list)
    validations: List[ValidationReport] = Field(default_factory=list)
    generated_at: Optional[datetime] = None


__all__ = [
    "PublicClaimId", "ClaimType", "ClaimStatus", "SupportStatus", "Decision",
    "DisplayClass", "CitationCandidate", "StatementDraft", "EvidenceRecord",
    "ValidationReason", "ValidationReport", "VerifiedStatement", "display_class_for",
    "ClaimRecord", "Binding", "StatementSpan", "ArtifactText", "MapItem", "MapArtifact",
    "SectionRecord", "MethodStepRecord", "StructureArtifact", "ClaimDraftBatch",
    "ClaimBuildResult", "LegacyRef", "ResolutionReport",
    "ReviewRequest", "ReviewRecord", "EvidenceExport",
]
