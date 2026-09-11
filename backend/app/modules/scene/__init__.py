"""M09 — 场景化讲解模块（REFACTOR_SPEC §3.2、§5.5、§5.10、§6.11）。

只从**已验证** statements/claims 生成；媒体只走
``scene → 已验证 statement → Claim/Evidence → verified Binding → Media``；
图号/印刷页字符串仅作 legacy_candidate；无关联显示无已验证媒体、不造假链接；
无音频时 ``audio_url=null`` 且字幕两端为 null；GET 不调 LLM、不写库。

API:
- ``build(scope, structure, claims, ctx) -> PresentationArtifact``（canonical）
- ``get(scope) -> PresentationArtifact``（canonical，只读）
- ``get_presentation(db, paper_id) -> dict``（旧 HTTP 兼容投影）
"""
from .legacy import get_presentation  # noqa: F401
from .service import (  # noqa: F401
    ALGORITHM_VERSION,
    build,
    get,
    legacy_candidates,
    verified_media_for,
)

__all__ = [
    "build",
    "get",
    "get_presentation",
    "verified_media_for",
    "legacy_candidates",
    "ALGORITHM_VERSION",
]
