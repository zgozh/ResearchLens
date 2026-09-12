"""M09 — 讲解词与字幕（REFACTOR_SPEC §5.5）。

硬约束：
- **无音频服务时 ``audio_url=null``**，不生成假音频链接；
- **无真实时间轴时 ``SubtitleCue.start_ms/end_ms`` 都为 null**，禁止猜时间却标同步字幕；
- 讲解词与 tts_text 都是 ``ArtifactText``，覆盖每个非空白字（由 statement 拼装）。
"""
from __future__ import annotations

from typing import List, Sequence

from app.contracts.evidence import ArtifactText, StatementSpan
from app.contracts.scene import NarrationRecord, SubtitleCue


def build_narration(
    parts: Sequence[tuple],
    *,
    cue_id_prefix: str,
) -> NarrationRecord:
    """由 ``[(statement_id, text), ...]`` 拼装讲解词。

    每个 statement 成为一个 span（覆盖其文本切片），
    每个 statement 也生成一条 **无时间轴** 字幕（两端 null）。
    """
    script_text, spans = _assemble(parts)
    script = ArtifactText(text=script_text, spans=spans)
    # **TTS 文本必须用自己的 spans**（ADR-0066）：``_to_tts_text`` 会去掉强调符号、压缩空白，
    # 长度与 ``script_text`` 不同；直接复用 script 的 span 会**越界**，触发
    # ``ArtifactText`` 的 "span 超出文本长度" 校验 → 整个 exhibits 阶段失败 →
    # 新导入的论文卡在 processing（实测 paper 9）。
    tts_text, tts_spans = _assemble([(sid, _to_tts_text(text)) for sid, text in parts])
    tts = ArtifactText(text=tts_text, spans=tts_spans)

    cues: List[SubtitleCue] = []
    for idx, (statement_id, text) in enumerate(parts):
        clean = (text or "").strip()
        if not clean:
            continue
        cues.append(SubtitleCue(
            id=f"{cue_id_prefix}:cue:{idx}",
            start_ms=None,
            end_ms=None,
            text=ArtifactText(
                text=clean,
                spans=[StatementSpan(start_cp=0, end_cp=len(clean), statement_id=statement_id)],
            ),
        ))

    return NarrationRecord(
        script=script,
        tts_text=tts,
        subtitle_cues=cues,
        audio_url=None,   # 无新增音频服务：绝不生成假链接
    )


def empty_narration(text: str = "", *, cue_id_prefix: str = "n") -> NarrationRecord:
    """无已验证陈述时的合法空讲解：文本可为空，字幕为空列表，audio_url=null。"""
    body = (text or "").strip()
    return NarrationRecord(
        script=ArtifactText(text=body, spans=[]),
        tts_text=ArtifactText(text=_to_tts_text(body), spans=[]),
        subtitle_cues=[],
        audio_url=None,
    )


def _assemble(parts: Sequence[tuple]) -> tuple:
    """把片段拼成连续文本，并给出非重叠、按序的 span。"""
    chunks: List[str] = []
    spans: List[StatementSpan] = []
    cursor = 0
    for statement_id, text in parts:
        body = (text or "").strip()
        if not body:
            continue
        if chunks:
            sep = " "
            chunks.append(sep)
            cursor += len(sep)
        start = cursor
        chunks.append(body)
        cursor += len(body)
        spans.append(StatementSpan(start_cp=start, end_cp=cursor, statement_id=statement_id))
    return "".join(chunks), spans


def _to_tts_text(text: str) -> str:
    """TTS 文本：去 markdown 强调符号与多余空白，句子间保留自然停顿标点。"""
    if not text:
        return ""
    out = text.replace("*", "").replace("`", "").replace("#", "")
    return " ".join(out.split())


__all__ = ["build_narration", "empty_narration"]
