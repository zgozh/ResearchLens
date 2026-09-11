"""M03 — 原件媒体与提取表示（REFACTOR_SPEC §5.10 M03、§5.3、§6.5）。

公共入口：

- ``build_media(scope, parsed: ParseSummary, ctx) -> MediaBuildResult``
- ``get_media(scope, ids: MediaId[]) -> Media[]``
- ``list_media(scope, kind, cursor, limit) -> PageResult[Media]``
- ``get_policy(media: Media) -> MediaViewPolicy``
- ``ensure_page_preview(scope, pdf_page_no, ctx) -> Asset``

纪律：
- 从**同源 PDF 坐标**裁剪优先，复用可核验 MinerU crop 次之；
- 保留原编号、跨页表有序资产、子图关系；
- 整页只当 ``page_preview``；**不凑数量、不重编原标签、不把 HTML 标"原版"**；
- 缺原图时 policy 返回 unavailable/extracted，绝不 synthetic。
"""
from __future__ import annotations

import uuid
from typing import Dict, List, Optional

from app.contracts.artifacts import (
    Asset,
    AssetWrite,
    ExtractedMedia,
    Media,
    MediaBuildResult,
    MediaProvenance,
    MediaViewPolicy,
)
from app.contracts.common import CallContext, PageResult, Scope, Warning
from app.contracts.documents import Page, ParseSummary, SourceDocument
from app.core.db import session_scope
from app.core.errors import DomainError, ErrorCode, invalid_input, not_found
from app.core.logging import get_logger

from . import crops, pages_util, policy as policy_mod, repository as repo, tables as tables_mod

log = get_logger(__name__)


# --------------------------------------------------------------- build


def build_media(
    scope: Scope,
    parsed: ParseSummary,
    ctx: Optional[CallContext] = None,
) -> MediaBuildResult:
    """由 ParseSummary 的媒体候选构建 Media。

    对每个候选尝试：同源 PDF 区域裁剪 → 已有嵌入资产 → 仅提取表示。
    不做数量填充：候选有几个就建几个。
    """
    warnings: List[Warning] = []
    if int(parsed.scope.paper_id) != int(scope.paper_id) or (
        parsed.scope.revision_id != scope.revision_id
    ):
        raise DomainError(
            ErrorCode.REVISION_MISMATCH, "ParseSummary 与 scope 不一致", retryable=False
        )

    source = _load_source(scope)
    source_bytes = _source_bytes(source)
    page_index = _page_geometry(scope)

    # 幂等：先按 revision 清空旧 Media 再重建（§6.5 / §5.8 stage 幂等）。
    # 为什么必须做：Media 有唯一约束 (revision_id, legacy_no)。重跑同一阶段时
    # 旧行仍在，逐条 INSERT 会撞 uq_media_revision_legacy_no → 整个 media 阶段
    # 失败（Postgres 实测：job retry 时 3 次尝试全 500）。
    # 清理只发生在该 revision 的 staging 写入路径；已发布 revision 由 publish
    # 的 CAS 保护，不会被本函数重写。
    with session_scope() as db:
        repo.assert_writable_revision(db, scope.revision_id)
        repo.delete_media_for_revision(db, scope.revision_id)

    counters: Dict[str, int] = {}
    built: List[Media] = []

    for candidate in parsed.media_candidates:
        kind = candidate.kind
        counters[kind] = counters.get(kind, 0) + 1
        original_assets: List[str] = []
        provenance = MediaProvenance(
            representation="extracted",
            source_document_id=source.id if source else None,
            source_sha256=source.sha256 if source else None,
            transform="none",
            verification="unverified",
        )

        extracted = _extracted_for(candidate, kind)

        # 1) 优先：同源 PDF 坐标裁剪（需要 bbox 与页尺寸）
        rect = _candidate_rect(candidate, page_index)
        if source_bytes and rect is not None and candidate.anchor_ids:
            page_no = _page_index_for_candidate(candidate, page_index)
            rendered = _try_crop(scope, source_bytes, page_no, rect)
            if rendered is not None:
                asset = _store_image(
                    scope, rendered.data, kind_hint="crop".strip(), width=rendered.width_px,
                    height=rendered.height_px,
                )
                if asset is not None:
                    original_assets.append(asset.id)
                    provenance = MediaProvenance(
                        representation="pdf_crop",
                        source_document_id=source.id if source else None,
                        source_sha256=source.sha256 if source else None,
                        raw_asset_id=candidate.raw_ref.asset_id if candidate.raw_ref else None,
                        transform="crop",
                        renderer_version=crops.RENDERER_VERSION,
                        verification="source_bound",
                    )

        # 2) 次之：已有的嵌入资产（MinerU 提取图字节）；未经区域核验只标 unverified
        if not original_assets and candidate.embedded_asset_id:
            original_assets.append(candidate.embedded_asset_id)
            if provenance.representation == "extracted":
                provenance = MediaProvenance(
                    representation="mineru_crop",
                    source_document_id=source.id if source else None,
                    source_sha256=source.sha256 if source else None,
                    raw_asset_id=candidate.embedded_asset_id,
                    transform="none",
                    renderer_version=None,
                    verification="unverified",
                )

        if not original_assets and extracted is None:
            warnings.append(
                Warning(
                    code="media_defaults_excluded",
                    message="媒体候选既无原件也无法形成提取表示，已排除",
                    stage="visual",
                )
            )
            continue

        media_id = _new_id()
        with session_scope() as db:
            repo.insert_media(
                db,
                media_id=media_id,
                paper_id=scope.paper_id,
                revision_id=scope.revision_id,
                kind=kind,
                original_label=candidate.original_label,
                legacy_no=counters[kind],
                caption=candidate.caption or "",
                caption_alt=getattr(candidate, "caption_alt", "") or "",
                anchor_ids=list(candidate.anchor_ids),
                original_asset_ids=original_assets,
                thumbnail_asset_id=None,
                extracted=extracted.model_dump() if extracted else None,
                provenance=provenance.model_dump(),
                excluded=bool(candidate.excluded),
                exclusion_reason=candidate.exclusion_reason,
            )
        built.append(
            Media(
                scope=scope,
                id=media_id,
                kind=kind,
                original_label=candidate.original_label,
                legacy_no=counters[kind],
                caption=candidate.caption or "",
                caption_alt=getattr(candidate, "caption_alt", "") or "",
                anchor_ids=list(candidate.anchor_ids),
                original_asset_ids=original_assets,
                thumbnail_asset_id=None,
                extracted=extracted,
                provenance=provenance,
                excluded=bool(candidate.excluded),
                exclusion_reason=candidate.exclusion_reason,
            )
        )

    return MediaBuildResult(scope=scope, media=built, warnings=warnings)


def _extracted_for(candidate, kind: str) -> Optional[ExtractedMedia]:
    if candidate.extracted is not None:
        return candidate.extracted
    if kind == "table" and candidate.caption:
        return tables_mod.build_extracted_media(table_html=candidate.caption)
    if kind == "equation":
        return tables_mod.build_extracted_media(equation_label=candidate.original_label)
    return None


def _candidate_rect(candidate, page_index: Dict[str, Page]) -> Optional[List[float]]:
    """把候选的像素 bbox 归一化到 0..1；缺坐标/尺寸未知则返回 None（page-only）。"""
    raw_ref = candidate.raw_ref
    if raw_ref is None or not raw_ref.bbox_values:
        return None
    if raw_ref.bbox_units not in ("pixel", "point"):
        return None
    page = _page_for_candidate(candidate, page_index)
    if page is None or page.width_pt <= 0 or page.height_pt <= 0:
        return None
    x0, y0, x1, y1 = (float(v) for v in raw_ref.bbox_values[:4])
    width = page.width_pt
    height = page.height_pt
    nx0, nx1 = sorted((x0 / width, x1 / width))
    ny0, ny1 = sorted((y0 / height, y1 / height))
    nx0, nx1 = max(0.0, min(1.0, nx0)), max(0.0, min(1.0, nx1))
    ny0, ny1 = max(0.0, min(1.0, ny0)), max(0.0, min(1.0, ny1))
    if not (nx0 < nx1 and ny0 < ny1):
        return None
    return [nx0, ny0, nx1, ny1]


def _page_for_candidate(candidate, page_index: Dict[str, Page]) -> Optional[Page]:
    for anchor_id in candidate.anchor_ids:
        page = page_index.get(anchor_id)
        if page is not None:
            return page
    return None


def _page_index_for_candidate(candidate, page_index: Dict[str, Page]) -> int:
    page = _page_for_candidate(candidate, page_index)
    return page.pdf_page_index if page is not None else 0


def _page_geometry(scope: Scope) -> Dict[str, Page]:
    """返回 {anchor_id: Page}，用于把候选锚点映射到页尺寸。

    只经 M02 的**公共**阅读函数取页与锚点，不导入 parse 私有实现。
    """
    from app.modules.parse import service as parse_service

    out: Dict[str, Page] = {}
    try:
        page_result = parse_service.get_pages(scope, None, 200)
    except DomainError:
        return out
    for page in list(page_result.items):
        try:
            content = parse_service.get_page(scope, page.pdf_page_no)
        except DomainError:
            continue
        for anchor in content.anchors:
            out[anchor.id] = page
    return out


def _try_crop(scope: Scope, source_bytes: bytes, pdf_page_index: int, rect: List[float]):
    try:
        return crops.render_region(source_bytes, pdf_page_index, rect)
    except DomainError:
        return None


def _store_image(scope: Scope, data: bytes, *, kind_hint: str, width, height) -> Optional[Asset]:
    from app.modules.papers import service as papers_service

    try:
        return papers_service.put_asset(
            AssetWrite(
                paper_id=scope.paper_id,
                revision_id=scope.revision_id,
                kind="crop",
                mime="image/png",
                width_px=width,
                height_px=height,
            ),
            data,
        )
    except DomainError as exc:
        log.warning("裁剪资产写入失败：%s", exc.code.value)
        return None


# --------------------------------------------------------------- 读取


def get_media(scope: Scope, ids: List[str], *, ctx: Optional[CallContext] = None) -> List[Media]:
    if not ids:
        return []
    with session_scope() as db:
        repo.require_scope_revision(db, scope.paper_id, scope.revision_id)
        rows = repo.get_media_rows(db, scope.revision_id, ids)
        by_id = {r.id: r for r in rows}
        # DTO 必须在 session 内投影：session_scope 退出后 ORM 实例会 detached
        return [_media_dto(scope, by_id[i]) for i in ids if i in by_id]


def list_media(
    scope: Scope,
    kind: Optional[str] = None,
    cursor: Optional[str] = None,
    limit: int = 50,
    *,
    include_excluded: bool = False,
    ctx: Optional[CallContext] = None,
) -> PageResult:
    """默认只返回未排除媒体；管理审计可查排除项。"""
    filter_key = f"kind={kind or ''}|excluded={bool(include_excluded)}"
    size = pages_util.clamp_limit(limit)
    offset = pages_util.decode_cursor(cursor, scope, filter_key)
    with session_scope() as db:
        repo.require_scope_revision(db, scope.paper_id, scope.revision_id)
        rows = repo.list_media(
            db, scope.revision_id, kind=kind, include_excluded=include_excluded
        )
        total = len(rows)
        window = rows[offset : offset + size]
        next_cursor = (
            pages_util.encode_cursor(scope, offset + len(window), filter_key)
            if offset + len(window) < total else None
        )
        items = [_media_dto(scope, r) for r in window]
    return PageResult(items=items, next_cursor=next_cursor, total=total)


def get_policy(media: Media, *, fallback_page_ids: Optional[List[str]] = None) -> MediaViewPolicy:
    """由 Media 计算来源显示策略（真实 source 缺原图不返回 synthetic）。"""
    return policy_mod.build_policy(media, fallback_page_ids=fallback_page_ids)


# --------------------------------------------------------------- 页预览


def ensure_page_preview(
    scope: Scope,
    pdf_page_no: int,
    ctx: Optional[CallContext] = None,
    *,
    dpi: Optional[int] = None,
) -> Asset:
    """按 source hash/页/渲染参数幂等缓存页预览；独立于语义 revision。"""
    if pdf_page_no < 1:
        raise invalid_input("pdf_page_no 必须 >= 1", field="pdf_page_no")

    source = _load_source(scope)
    if source is None or not source.asset_id:
        raise not_found("该论文没有可用源文件，无法生成页预览")
    if source.page_count and pdf_page_no > source.page_count:
        raise not_found(f"物理页 {pdf_page_no} 超出源文件页数")

    zoom = crops.clamp_dpi(dpi, default=crops.DEFAULT_PREVIEW_DPI)
    cache_key = crops.preview_cache_key(source.sha256, pdf_page_no - 1, zoom)

    with session_scope() as db:
        from sqlalchemy import select

        from app.models.artifacts import ArtifactBlobORM

        row = db.execute(
            select(ArtifactBlobORM).where(
                ArtifactBlobORM.revision_id == scope.revision_id,
                ArtifactBlobORM.kind == f"page_preview:{cache_key}",
            )
        ).scalars().first()
        if row is not None and row.payload:
            asset_id = row.payload.get("asset_id")
            if asset_id:
                from app.modules.papers import service as papers_service

                assets = papers_service.get_assets(scope, [asset_id])
                if assets:
                    return assets[0]

    source_bytes = _source_bytes(source)
    if not source_bytes:
        raise not_found("源文件字节不可用")
    rendered = crops.render_page(source_bytes, pdf_page_no - 1, dpi=zoom)
    if rendered is None:
        raise DomainError(
            ErrorCode.DEPENDENCY_UNAVAILABLE,
            "页预览渲染暂不可用",
            retryable=True,
        )

    from app.modules.papers import service as papers_service

    asset = papers_service.put_asset(
        AssetWrite(
            paper_id=scope.paper_id,
            revision_id=scope.revision_id,
            kind="page_preview",
            mime=rendered.mime,
            width_px=rendered.width_px,
            height_px=rendered.height_px,
        ),
        rendered.data,
    )

    with session_scope() as db:
        from app.models.artifacts import ArtifactBlobORM

        db.add(
            ArtifactBlobORM(
                id=_new_id(),
                paper_id=scope.paper_id,
                revision_id=scope.revision_id,
                kind=f"page_preview:{cache_key}",
                payload={"asset_id": asset.id, "pdf_page_index": pdf_page_no - 1, "dpi": zoom},
            )
        )
        db.flush()
    return asset


# --------------------------------------------------------------- 内部辅助


def _media_dto(scope: Scope, row) -> Media:
    extracted = None
    if row.extracted:
        try:
            extracted = ExtractedMedia(**row.extracted)
        except Exception:  # noqa: BLE001
            extracted = None
    provenance = MediaProvenance(representation="extracted")
    if row.provenance:
        try:
            provenance = MediaProvenance(**row.provenance)
        except Exception:  # noqa: BLE001
            provenance = MediaProvenance(representation="extracted")
    return Media(
        scope=scope,
        id=row.id,
        kind=row.kind if row.kind in ("figure", "table", "equation", "page_preview")
        else "figure",
        original_label=row.original_label,
        legacy_no=row.legacy_no,
        caption=row.caption or "",
        anchor_ids=list(row.anchor_ids or []),
        original_asset_ids=list(row.original_asset_ids or []),
        thumbnail_asset_id=row.thumbnail_asset_id,
        extracted=extracted,
        provenance=provenance,
        excluded=bool(row.excluded),
        exclusion_reason=row.exclusion_reason,
    )


def _load_source(scope: Scope) -> Optional[SourceDocument]:
    from app.modules.papers import service as papers_service

    try:
        return papers_service.get_source(scope)
    except DomainError:
        return None


def _source_bytes(source: Optional[SourceDocument]) -> Optional[bytes]:
    if source is None or not source.asset_id:
        return None
    from app.modules.papers import service as papers_service

    try:
        handle = papers_service.open_asset(source.asset_id, None)
        return b"".join(handle.stream) or None
    except DomainError:
        return None


def _new_id() -> str:
    return str(uuid.uuid4())


__all__ = [
    "build_media",
    "get_media",
    "list_media",
    "get_policy",
    "ensure_page_preview",
]
