"""M09 — 旧 HTTP 兼容适配（REFACTOR_SPEC §5.11）。

``api/routes.py`` 仍以 ``get_presentation(db, paper_id)`` 调用本包，且旧前端读
``figure_refs`` / ``table_refs`` / ``linked`` / ``narration`` 等字段。本模块负责把
``PresentationArtifact`` 投影回旧结构：

- ``linked`` **只由 verified binding 产生**（canonical 媒体通道）；
- ``figure_refs`` / ``table_refs`` 是**整数兼容编号**（legacy_candidate），
  仅从已验证媒体的 legacy_no 取，绝不靠正则从正文猜图号；
- **无关联时为 ``[]``**，不生成看似合理的链接。
"""
from __future__ import annotations

from typing import Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.contracts.common import Scope

from . import service as svc


def get_presentation(db: Session, paper_id: int) -> Dict[str, List[dict]]:
    """旧签名：返回 ``{scenes: [...]}``，字段与旧 ``SceneOut`` 兼容。"""
    revision_id = _readable_revision(db, paper_id)
    if not revision_id:
        return {"scenes": []}

    artifact = svc.get(Scope(paper_id=paper_id, revision_id=revision_id))
    media_by_id = _media_index(db, revision_id)
    return to_legacy_presentation(artifact, media_by_id)


def to_legacy_presentation(artifact, media_by_id: Optional[Dict[str, object]] = None) -> Dict:
    """``PresentationArtifact → PresentationOut`` 兼容投影。"""
    media_by_id = media_by_id or {}
    scenes: List[dict] = []

    for scene in artifact.scenes:
        linked: List[dict] = []
        figure_refs: List[int] = []
        table_refs: List[int] = []

        for mid in scene.media_ids:
            row = media_by_id.get(mid)
            if row is None:
                continue
            kind = getattr(row, "kind", "figure")
            label = getattr(row, "original_label", None)
            legacy_no = getattr(row, "legacy_no", None)
            caption = getattr(row, "caption", "") or ""
            linked.append({
                "type": "media" if kind == "figure" else kind,
                "media_id": mid,
                "label": label or "",
                "caption": caption,
            })
            # 旧前端读整数编号：只在持久化 legacy_no 存在时给出（不重编）
            if isinstance(legacy_no, int):
                if kind == "table":
                    table_refs.append(legacy_no)
                elif kind == "figure":
                    figure_refs.append(legacy_no)

        narration = scene.narration
        scenes.append({
            "order": scene.order,
            "title": scene.title.text if scene.title else "",
            "kind": scene.kind,
            "summary": scene.summary.text if scene.summary else "",
            "steps": list(scene.step_ids or []),
            "evidence_refs": list(scene.statement_ids or []),
            "figure_refs": _dedup_ints(figure_refs),
            "table_refs": _dedup_ints(table_refs),
            "narration": {
                "script": narration.script.text if narration else "",
                "tts_text": narration.tts_text.text if narration else "",
                "audio_url": (narration.audio_url if narration else None),
                "subtitle": [
                    {
                        "id": cue.id,
                        "start_ms": cue.start_ms,
                        "end_ms": cue.end_ms,
                        "text": cue.text.text,
                    }
                    for cue in (narration.subtitle_cues if narration else [])
                ],
            },
            "linked": linked,
            "media_ids": list(scene.media_ids or []),
        })

    return {"scenes": scenes}


def _media_index(db: Session, revision_id: str) -> Dict[str, object]:
    """取出该 revision 全部媒体快照（离开 Session 后仍可读）。"""
    from app.modules.scene.repository import all_media

    return {row.id: row for row in all_media(db, revision_id)}


def _dedup_ints(values: List[int]) -> List[int]:
    out: List[int] = []
    for v in values:
        if v not in out:
            out.append(v)
    return out


def _readable_revision(db: Session, paper_id: int) -> Optional[str]:
    from app.models.models import Paper

    row = db.get(Paper, paper_id)
    if row is None:
        return None
    if row.readable_revision_id:
        return row.readable_revision_id
    from app.models.source import RevisionORM

    stmt = (
        select(RevisionORM.id)
        .where(RevisionORM.paper_id == paper_id)
        .order_by(RevisionORM.created_at.desc())
        .limit(1)
    )
    found = db.execute(stmt).first()
    return found[0] if found else None


__all__ = ["get_presentation", "to_legacy_presentation"]
