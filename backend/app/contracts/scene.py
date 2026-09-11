"""M00 — 场景化讲解契约（REFACTOR_SPEC §5.5 后半）。

媒体只能来自「scene 的已验证 statement → Claim/Evidence → verified Binding → Media」；
图号/印刷页字符串仅作 legacy_candidate，绝不进入 verified linked。
无真实时间轴时 audio_url=null 且 SubtitleCue 两端为 null，禁止猜时间标同步。
"""
from __future__ import annotations

from typing import List, Optional

from pydantic import Field

from .common import ContractModel, Id, MediaId, Scope, StatementId, Warning
from .evidence import ArtifactText

PublicClaimId = str


class SubtitleCue(ContractModel):
    id: Id
    start_ms: Optional[int] = Field(default=None, ge=0)
    end_ms: Optional[int] = Field(default=None, ge=0)
    text: ArtifactText


class NarrationRecord(ContractModel):
    script: ArtifactText
    tts_text: ArtifactText
    subtitle_cues: List[SubtitleCue] = Field(default_factory=list)
    audio_url: Optional[str] = None


class SceneRecord(ContractModel):
    scope: Scope
    id: Id
    order: int = Field(default=0, ge=0)
    title: ArtifactText
    kind: str = "intro"
    summary: ArtifactText
    step_ids: List[Id] = Field(default_factory=list)
    statement_ids: List[StatementId] = Field(default_factory=list)
    claim_ids: List[PublicClaimId] = Field(default_factory=list)
    binding_ids: List[Id] = Field(default_factory=list)
    media_ids: List[MediaId] = Field(default_factory=list)
    narration: NarrationRecord


class PresentationArtifact(ContractModel):
    scope: Scope
    id: Id
    scenes: List[SceneRecord] = Field(default_factory=list)
    warnings: List[Warning] = Field(default_factory=list)


__all__ = [
    "SubtitleCue",
    "NarrationRecord",
    "SceneRecord",
    "PresentationArtifact",
]
