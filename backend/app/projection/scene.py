"""讲解投影 —— **唯一实现**（R4-M8 物理迁移，原 `modules/scene/legacy.py`）。

迁移性质：**纯机械**。函数体逐字搬入，`modules/scene/legacy.to_legacy_presentation`
改为薄委托。`schemas/adapters.to_legacy_presentation` 也直接指向本模块。

纪律（原本就写在函数 docstring 里，随迁移保留）：

- ``linked`` **只由 verified binding 产生**（canonical 媒体通道）；
- ``figure_refs`` / ``table_refs`` 是**整数兼容编号**（legacy_candidate），
  仅从已验证媒体的 ``legacy_no`` 取，**绝不靠正则从正文猜图号**；
- **无关联时为 ``[]``**，不生成看似合理的链接。
"""
from __future__ import annotations

from typing import Dict, List, Optional


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


def _dedup_ints(values: List[int]) -> List[int]:
    out: List[int] = []
    for v in values:
        if v not in out:
            out.append(v)
    return out


__all__ = ["to_legacy_presentation"]
