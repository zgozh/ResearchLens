"""M03 — 来源显示策略（REFACTOR_SPEC §5.3、§3.4）。

**核心纪律：真实 source 缺原图不允许返回 synthetic。**

原件模式优先（§3.4）：可验证的 PDF 区域裁剪 → 与同一源文件绑定且可追溯的
MinerU 裁剪 → 对应整页预览 → 明示不可用。

- ``pdf_crop``/``mineru_crop`` 且 ``source_bound`` → ``original``
- 只有提取表示（HTML/LaTeX）→ ``extracted``（**不得标"原版"**）
- 真实 source（``source_document_id`` 存在）且无原件 → ``unavailable``（绝不 synthetic）
- 只有受控 seed 的 synthetic 资产 → ``synthetic``
"""
from __future__ import annotations

from typing import List, Optional

from app.contracts.artifacts import Media, MediaProvenance, MediaViewPolicy
from app.contracts.common import Warning


def build_policy(media: Media, *, fallback_page_ids: Optional[List[str]] = None) -> MediaViewPolicy:
    """由 Media 计算视图策略；不编造资产，不用示意 SVG 顶替真实原件。"""
    warnings: List[Warning] = []
    provenance: MediaProvenance = media.provenance
    originals = list(media.original_asset_ids or [])
    is_real_source = bool(provenance.source_document_id)

    if media.excluded:
        return MediaViewPolicy(
            default_mode="unavailable",
            original_asset_ids=[],
            fallback_page_ids=[],
            label="已排除（不可追溯的媒体候选）",
            warnings=[
                Warning(
                    code="media_excluded",
                    message=media.exclusion_reason or "媒体候选已被排除",
                    stage="visual",
                )
            ],
        )

    # 1) 可验证原件：PDF 坐标裁剪 / 同源可追溯 MinerU 裁剪
    if originals and provenance.representation in ("pdf_crop", "mineru_crop"):
        if provenance.verification == "source_bound":
            return MediaViewPolicy(
                default_mode="original",
                original_asset_ids=originals,
                fallback_page_ids=[],
                label="PDF 原件",
                warnings=warnings,
            )
        # 未验证绑定：可作为"解析器提取图"查看，不叫精确原件
        warnings.append(
            Warning(
                code="provenance_unverified",
                message="裁剪来源未验证到同一 PDF 字节/正确区域，按解析器提取图呈现",
                stage="visual",
            )
        )
        return MediaViewPolicy(
            default_mode="extracted",
            original_asset_ids=originals,
            fallback_page_ids=list(fallback_page_ids or []),
            label="解析器提取图（来源未验证）",
            warnings=warnings,
        )

    # 2) 真实来源但无原件：整页预览兜底；无预览则 unavailable（绝不 synthetic）
    if is_real_source:
        if originals:
            warnings.append(
                Warning(
                    code="original_unverified",
                    message="存在资产但未确认为可核验原件，按提取/预览呈现",
                    stage="visual",
                )
            )
        if fallback_page_ids:
            return MediaViewPolicy(
                default_mode="extracted" if media.extracted else "unavailable",
                original_asset_ids=originals,
                fallback_page_ids=list(fallback_page_ids),
                label="整页预览（非区域原件）" if not originals else "提取表示 + 整页预览",
                warnings=warnings,
            )
        return MediaViewPolicy(
            default_mode="extracted" if _has_extracted(media) else "unavailable",
            original_asset_ids=originals,
            fallback_page_ids=[],
            label="提取表示（无可用原件）" if _has_extracted(media) else "原件不可用",
            warnings=warnings,
        )

    # 3) 受控 synthetic（仅来源于 seed，且无真实 source）
    if provenance.representation == "synthetic" or provenance.verification == "synthetic":
        warnings.append(
            Warning(
                code="synthetic_source",
                message="示意内容来自受控 seed，不代表论文原件",
                stage="visual",
            )
        )
        return MediaViewPolicy(
            default_mode="synthetic",
            original_asset_ids=originals,
            fallback_page_ids=[],
            label="示意（非论文原件）",
            warnings=warnings,
        )

    # 4) 无来源信息
    return MediaViewPolicy(
        default_mode="extracted" if _has_extracted(media) else "unavailable",
        original_asset_ids=originals,
        fallback_page_ids=list(fallback_page_ids or []),
        label="提取表示" if _has_extracted(media) else "原件不可用",
        warnings=warnings,
    )


def _has_extracted(media: Media) -> bool:
    ex = media.extracted
    if ex is None:
        return False
    return bool(ex.table_html or ex.latex or ex.table_cells or ex.equation_label)


def label_for_mode(mode: str) -> str:
    """统一来源标签文案（前端 SourceMedia/MediaModal 共用）。"""
    return {
        "original": "PDF 原件",
        "extracted": "提取表示（非原版）",
        "synthetic": "示意（非论文原件）",
        "unavailable": "原件不可用",
    }.get(mode, "未知来源")


__all__ = ["build_policy", "label_for_mode"]
