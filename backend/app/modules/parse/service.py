"""M02 — MinerU/PyMuPDF 解析与页码坐标（REFACTOR_SPEC §5.10 M02、§6.4）。

公共入口：

- ``parse(source: SourceDocument, ctx) -> ParseResult``
- ``persist(scope, result: ParseResult, ctx) -> ParseSummary``（幂等）
- ``get_pages(scope, cursor, limit) -> PageResult[Page]``
- ``get_blocks(scope, ids: BlockId[]) -> Block[]``
- ``resolve_page_label(scope, label) -> PageResolution``
- ``get_page(scope, pdf_page_no) -> PageContent``
- ``apply_page_overrides(scope, overrides, ctx) -> ParseSummary``（只改 staging revision）

纪律：
- 解析**已保存的同一份字节**（从 M01 的 source asset 读回）；
- MinerU 优先，失败/超时/token 缺失 → PyMuPDF 降级并带 warnings；
- 跨模块不传 Session，云调用不持有写事务；
- 同 revision 重复 persist 不重复 page/block。
"""
from __future__ import annotations

import hashlib
import uuid
from typing import Any, Dict, List, Optional

from sqlalchemy import delete, select

from app.contracts.common import CallContext, Scope, Warning
from app.contracts.documents import (
    Anchor,
    Block,
    Page,
    PageContent,
    PageLabelMapping,
    PageLabelOverride,
    PageResolution,
    PageSummary,
    ParseResult,
    ParseSummary,
    SourceDocument,
)
from app.core.db import session_scope
from app.core.errors import (
    DomainError,
    ErrorCode,
    invalid_input,
    not_found,
    revision_mismatch,
)
from app.core.logging import get_logger
from app.models.artifacts import (
    AnchorORM,
    BlockORM,
    PageLabelMappingORM,
    PageORM,
)
from app.models.source import AssetORM

from . import mineru_adapter, normalize, pages as pages_mod, pymupdf_adapter
from .pymupdf_adapter import RawBlock, RawDocument, RawPage

log = get_logger(__name__)

MAX_BLOCKS_PER_PAGE = 2000


# --------------------------------------------------------------- scope 校验


def _load_source_bytes(scope: Scope) -> "tuple[bytes, str]":
    """短事务读回 source 字节与文件名；**不在此事务内做云调用**。"""
    from app.modules.papers import service as papers_service
    from app.modules.papers import storage

    source = papers_service.get_source(scope)
    if not source.asset_id:
        raise DomainError(ErrorCode.NOT_FOUND, "源文件没有可读资产", retryable=False)
    handle = papers_service.open_asset(source.asset_id, None)
    data = b"".join(handle.stream)
    if not data:
        raise DomainError(ErrorCode.NOT_FOUND, "源文件字节为空", retryable=False)
    return data, (source.original_filename or "paper.pdf")


def _check_scope(scope: Optional[Scope]) -> Scope:
    if scope is None:
        raise invalid_input("parse 需要 ctx.scope 且对应 source", field="scope")
    with session_scope() as db:
        from app.modules.papers import repository as repo

        row = repo.require_scope_revision(db, scope.paper_id, scope.revision_id)
        if row.state != "staging":
            raise DomainError(
                ErrorCode.CONFLICT,
                "只允许解析 staging 修订版；已发布版本不得原位重解析",
                retryable=False,
            )
    return scope


# --------------------------------------------------------------- parse


def parse(source: SourceDocument, ctx: Optional[CallContext] = None) -> ParseResult:
    """解析已保存的源字节；MinerU 优先，失败降级 PyMuPDF。"""
    scope = _check_scope(ctx.scope if ctx else None)
    if int(source.paper_id) != int(scope.paper_id):
        raise revision_mismatch("source 与 scope 不属于同一论文")

    data, filename = _load_source_bytes(scope)
    if source.sha256:
        actual = hashlib.sha256(data).hexdigest()
        if actual != source.sha256:
            raise DomainError(
                ErrorCode.REVISION_MISMATCH,
                "读取到的源字节与 SourceDocument.sha256 不一致",
                retryable=False,
            )

    warnings: List[Warning] = []
    raw: Optional[RawDocument] = None
    parser_name = mineru_adapter.ADAPTER_NAME

    if mineru_adapter.enabled():
        try:
            raw = mineru_adapter.parse_bytes(data, filename=filename)
            parser_name = mineru_adapter.ADAPTER_NAME
        except Exception as exc:  # noqa: BLE001
            log.warning("MinerU 解析失败，降级 PyMuPDF：%s", type(exc).__name__)
            warnings.append(
                Warning(
                    code="mineru_unavailable",
                    message=f"MinerU 解析不可用，已降级 PyMuPDF（{type(exc).__name__}）",
                    stage="parse",
                )
            )
            raw = None
    else:
        warnings.append(
            Warning(
                code="mineru_disabled",
                message="未配置 MINERU_TOKEN 或已禁用，使用 PyMuPDF",
                stage="parse",
            )
        )

    if raw is None:
        raw = pymupdf_adapter.parse_bytes(data)
        parser_name = pymupdf_adapter.ADAPTER_NAME
        _fill_page_geometry(raw, data)

    warnings.extend(raw.warnings)

    # 图片字节落库（MinerU 解包出的 images/）：必须在 _persist_raw_asset 之前，
    # 这样 block.image_asset_id 会被一起存档，重放路径才不会又丢图（ADR-0024）。
    _persist_media_images(scope, raw)

    page_ids = [_new_id() for _ in raw.pages]
    block_ids = [[_new_id() for _ in rp.blocks] for rp in raw.pages]
    pages = normalize.build_pages(scope, raw, page_ids=page_ids)
    section_paths = normalize.section_paths_from_headings(
        normalize.build_blocks(scope, raw, pages=pages, block_ids=block_ids)
    )
    blocks = normalize.build_blocks(
        scope, raw, pages=pages, block_ids=block_ids, section_paths=section_paths
    )

    source_id = _source_id_for_scope(scope)
    anchors: List[Anchor] = []
    anchor_id_by_page: Dict[str, str] = {}
    for page in pages:
        page_blocks = [b.id for b in blocks if b.page_id == page.id]
        anchor = normalize.build_page_anchor(
            scope,
            anchor_id=_new_id(),
            source_document_id=source_id or "",
            pages=pages,
            page_id=page.id,
            block_ids=page_blocks,
        )
        anchors.append(anchor)
        anchor_id_by_page[page.id] = anchor.id

    # 反向指针：块 → 所在页的页锚点（ADR-0029）。
    # 页锚点此前已经知道自己的 block_ids，但块不知道自己的 anchor_id，
    # 导致 blocks.anchor_id 全为 NULL、section_records.anchor_ids 无从派生，
    # 「章节 / 正文定位」在第一步就断链。这里把双向关系补齐。
    for block in blocks:
        block.anchor_id = anchor_id_by_page.get(block.page_id)

    labels = normalize.build_label_mappings_with_blocks(
        scope, raw, pages=pages, blocks=blocks, id_factory=lambda kind, key: _new_id()
    )

    raw_asset_id = _persist_raw_asset(scope, raw, data, parser_name)
    media_candidates = normalize.build_media_candidates(
        scope, raw, pages=pages, blocks=blocks,
        page_index_by_id={p.id: p.pdf_page_index for p in pages},
        raw_asset_id=raw_asset_id or "",
    )

    return ParseResult(
        scope=scope,
        source=source,
        pages=pages,
        blocks=blocks,
        anchors=anchors,
        label_mappings=labels,
        media_candidates=media_candidates,
        raw_asset_ids=[raw_asset_id] if raw_asset_id else [],
        parser_name=parser_name,
        parser_version=getattr(
            mineru_adapter if parser_name == mineru_adapter.ADAPTER_NAME else pymupdf_adapter,
            "ADAPTER_VERSION", "",
        ),
        warnings=warnings,
    )


def _fill_page_geometry(raw: RawDocument, data: bytes) -> None:
    """MinerU 路径缺页面尺寸时，用 PyMuPDF 补齐尺寸（不改变文本与页码）。"""
    if not pymupdf_adapter.available():
        return
    try:
        geom = pymupdf_adapter.parse_bytes(data)
    except Exception:  # noqa: BLE001
        return
    for index, page in enumerate(raw.pages):
        if page.width_pt > 0 and page.height_pt > 0:
            continue
        if index >= len(geom.pages):
            break
        source_page = geom.pages[index]
        page.width_pt = source_page.width_pt
        page.height_pt = source_page.height_pt
        page.rotation = source_page.rotation
        page.cropbox_pdf = list(source_page.cropbox_pdf)
        if not page.text:
            page.text = source_page.text
            page.extraction_quality = source_page.extraction_quality


def _persist_raw_asset(scope: Scope, raw: RawDocument, data: bytes, parser_name: str) -> Optional[str]:
    """把原始解析产物作为只读 raw asset 存档（审计用，不当指令执行）。"""
    import json

    from app.contracts.artifacts import AssetWrite
    from app.modules.papers import service as papers_service

    payload = {
        "parser": parser_name,
        "page_count": raw.page_count,
        "toc": raw.toc,
        "pages": [
            {
                "pdf_page_index": p.pdf_page_index,
                "width_pt": p.width_pt,
                "height_pt": p.height_pt,
                "rotation": p.rotation,
                "blocks": [
                    {
                        "kind": b.kind,
                        "text": b.text,
                        "bbox": b.bbox,
                        "units": b.bbox_units,
                        "table_html": getattr(b, "table_html", None),
                        "table_caption": getattr(b, "table_caption", None),
                        # 图片块：路径与已落库的 image asset id 都要存档，
                        # 否则重放（load_media_candidates）还原不出图（ADR-0024）。
                        "img_path": getattr(b, "img_path", None),
                        "image_asset_id": getattr(b, "image_asset_id", None),
                    }
                    for b in p.blocks
                ],
            }
            for p in raw.pages
        ],
    }
    blob = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    try:
        asset = papers_service.put_asset(
            AssetWrite(
                paper_id=scope.paper_id,
                revision_id=scope.revision_id,
                kind="parser_raw",
                mime="application/json",
            ),
            blob,
        )
        return asset.id
    except DomainError as exc:
        log.warning("raw asset 存档失败：%s", exc.code.value)
        return None


def _persist_media_images(scope: Scope, raw: RawDocument) -> int:
    """把解包出的图片字节落成 ``kind="image"`` 资产，并把 asset id 写回 block。

    为什么需要它（ADR-0024）：此前 ``build_media_candidates`` 用
    ``embedded_asset_id = raw_asset_id``（那份 **parser_raw JSON**）顶替"MinerU 提取图"，
    于是 ``Media.original_asset_ids`` 指向一个 JSON 文件——前端把它当图片渲染，
    图表全空（实测 ``GET /api/assets/{id}`` 返回 ``application/json`` 161KB）。

    图片字节一直都在解析产物 ZIP 里，只是没人读。适配器保持纯粹
    （只给 ``RawBlock.img_path`` 与 ``RawDocument.images``），落库放在这里
    （有 scope、能调 papers 服务），并**幂等**（``put_asset`` 按 paper+sha256+kind 去重）。

    返回成功落库的图片数量。缺字节/落库失败只记 warning，不中断解析。
    """
    from app.contracts.artifacts import AssetWrite
    from app.modules.papers import service as papers_service
    from app.modules.papers import storage as storage_mod

    images = getattr(raw, "images", None) or {}
    if not images:
        return 0

    stored = 0
    for page in raw.pages:
        for block in page.blocks:
            if getattr(block, "kind", "") != "image" or block.image_asset_id:
                continue
            path = (getattr(block, "img_path", "") or "").replace("\\", "/")
            if not path:
                continue
            data = images.get(path.split("/")[-1])
            if not data:
                continue
            try:
                asset = papers_service.put_asset(
                    AssetWrite(
                        paper_id=scope.paper_id,
                        revision_id=scope.revision_id,
                        # 契约 AssetKind 里表示"图像字节"的取值是 ``crop``
                        # （与 PyMuPDF 渲染的 pdf_crop 同一类），不新增 Literal。
                        kind="crop",
                        mime=storage_mod.sniff_mime(data[:2048]),
                    ),
                    data,
                )
            except DomainError as exc:
                log.warning("图片资产落库失败（%s）：%s", path, exc.code.value)
                continue
            block.image_asset_id = asset.id
            stored += 1
    return stored


def _source_id_for_scope(scope: Scope) -> Optional[str]:
    with session_scope() as db:
        from app.modules.papers import repository as repo

        row = repo.require_scope_revision(db, scope.paper_id, scope.revision_id)
        return row.source_document_id


# --------------------------------------------------------------- persist


def persist(scope: Scope, result: ParseResult, ctx: Optional[CallContext] = None) -> ParseSummary:
    """幂等持久化：同 revision 重复执行不重复 page/block。

    采用"先删同 revision 的解析产物再写入"策略（仅限 staging），保证重试一致；
    已发布 revision 不允许 persist。
    """
    if int(result.scope.paper_id) != int(scope.paper_id) or (
        result.scope.revision_id != scope.revision_id
    ):
        raise revision_mismatch("ParseResult 与目标 scope 不一致")

    with session_scope() as db:
        from app.modules.papers import repository as repo

        rev = repo.require_scope_revision(db, scope.paper_id, scope.revision_id)
        if rev.state not in ("staging", "readable"):
            raise DomainError(
                ErrorCode.CONFLICT,
                "已发布修订版不得重新写入解析产物",
                retryable=False,
            )
        _delete_parse_rows(db, scope.revision_id)
        _insert_parse_rows(db, scope, result)

        quality = _quality_of(result)
        rev.parser_name = result.parser_name
        rev.parser_version = result.parser_version
        rev.normalizer_version = normalize.NORMALIZER_VERSION
        rev.quality = quality
        rev.warnings = [w.model_dump() for w in result.warnings]
        db.flush()

        summary = ParseSummary(
            scope=scope,
            page_count=len(result.pages),
            block_ids=[b.id for b in result.blocks],
            anchor_ids=[a.id for a in result.anchors],
            media_candidates=result.media_candidates,
            raw_asset_ids=result.raw_asset_ids,
            quality=quality,
            warnings=result.warnings,
        )
    return summary


def _delete_parse_rows(db, revision_id: str) -> None:
    db.execute(delete(BlockORM).where(BlockORM.revision_id == revision_id))
    db.execute(delete(AnchorORM).where(AnchorORM.revision_id == revision_id))
    db.execute(delete(PageLabelMappingORM).where(PageLabelMappingORM.revision_id == revision_id))
    db.execute(delete(PageORM).where(PageORM.revision_id == revision_id))
    db.flush()


def _insert_parse_rows(db, scope: Scope, result: ParseResult) -> None:
    for page in result.pages:
        db.add(
            PageORM(
                id=page.id,
                paper_id=scope.paper_id,
                revision_id=scope.revision_id,
                pdf_page_index=page.pdf_page_index,
                page_label=page.page_label,
                label_status=page.label_status,
                width_pt=page.width_pt,
                height_pt=page.height_pt,
                rotation=page.rotation,
                cropbox_pdf=list(page.cropbox_pdf),
                text=page.text,
                text_origin="source_extraction",
                preview_asset_id=page.preview_asset_id,
                extraction_quality=page.extraction_quality,
            )
        )
    db.flush()
    for block in result.blocks:
        raw_ref = block.raw_ref.model_dump() if block.raw_ref else {}
        db.add(
            BlockORM(
                id=block.id,
                paper_id=scope.paper_id,
                revision_id=scope.revision_id,
                page_id=block.page_id,
                ordinal=block.ordinal,
                kind=block.kind,
                text=block.text,
                origin="source_extraction",
                anchor_id=block.anchor_id,
                media_id=block.media_id,
                section_path=list(block.section_path),
                raw_ref=raw_ref,
                language=block.language,
                content_hash=block.content_hash,
            )
        )
    for anchor in result.anchors:
        db.add(
            AnchorORM(
                id=anchor.id,
                paper_id=scope.paper_id,
                revision_id=scope.revision_id,
                source_document_id=anchor.source_document_id,
                precision=anchor.precision,
                segments=[seg.model_dump() for seg in anchor.segments],
                transform=anchor.transform.model_dump() if anchor.transform else None,
                raw_ref=anchor.raw_ref.model_dump() if anchor.raw_ref else None,
            )
        )
    for mapping in result.label_mappings:
        db.add(
            PageLabelMappingORM(
                id=mapping.id,
                paper_id=scope.paper_id,
                revision_id=scope.revision_id,
                page_label=mapping.page_label,
                pdf_page_index=mapping.pdf_page_index,
                method=mapping.method,
                status=mapping.status,
                source_block_ids=list(mapping.source_block_ids),
                confidence=mapping.confidence,
                review_id=mapping.review_id,
            )
        )
    db.flush()


def _quality_of(result: ParseResult) -> str:
    if not result.pages:
        return "source_only"
    has_text = any(p.extraction_quality == "text" for p in result.pages)
    all_text = all(p.extraction_quality in ("text", "empty") for p in result.pages)
    if has_text and all_text:
        return "complete"
    if has_text:
        return "partial"
    return "source_only"


# --------------------------------------------------------------- 读取


def load_media_candidates(
    scope: Scope,
    *,
    ctx: Optional[CallContext] = None,
) -> List[Any]:
    """从已持久化的解析产物重建 ``ParsedMediaCandidate`` 列表（供 M03 build_media）。

    为什么存在（修复 "media 阶段 succeeded 但产出 0 条"）：
    ``visual.build_media`` 按 ``ParseSummary.media_candidates`` 逐个建 Media。
    pipeline 的 media 阶段此前传的是**空候选**（注释声称"走从已有解析块重建"，
    但实际没有任何重建代码），于是 ``build_media`` 空转，阶段返回 succeeded
    却产出 0 条媒体 —— 前端因此永远看不到原图/原表。

    做法：读回 parse 阶段存档的 ``parser_raw`` 资产（同一 revision 的只读审计
    产物，含每块 kind/text/bbox），配合已持久化的 Page/Block 重新调用
    ``normalize.build_media_candidates``。这是**纯重放**，不做任何猜测：
    候选仍由原文块决定，编号仍来自原文。

    无 raw 资产（老数据 / 解析降级）时返回空列表并记警告，不伪造候选。
    """
    import json

    from app.contracts.documents import ParsedMediaCandidate
    from app.modules.papers import service as papers_service

    candidate_kinds = {"table", "equation", "image"}
    with session_scope() as db:
        _require_revision(db, scope)
        raw_rows = list(
            db.execute(
                select(AssetORM).where(
                    AssetORM.paper_id == int(scope.paper_id),
                    AssetORM.revision_id == scope.revision_id,
                    AssetORM.kind == "parser_raw",
                )
            ).scalars()
        )
        if not raw_rows:
            log.info("load_media_candidates: revision %s 无 parser_raw 资产，跳过", scope.revision_id)
            return []
        raw_asset_id = raw_rows[-1].id

        # 冻结为纯值快照后再离开 session（§ 经验：ORM 实例跨 session 访问会失效）
        page_rows = [
            (r.id, r.pdf_page_index)
            for r in db.execute(
                select(PageORM)
                .where(PageORM.revision_id == scope.revision_id)
                .order_by(PageORM.pdf_page_index)
            ).scalars()
        ]
        block_rows = [
            _block_dto(scope, r)
            for r in db.execute(
                select(BlockORM)
                .where(BlockORM.revision_id == scope.revision_id)
                .order_by(BlockORM.ordinal)
            ).scalars()
        ]
        page_dtos = [
            _page_dto(scope, r)
            for r in db.execute(
                select(PageORM)
                .where(PageORM.revision_id == scope.revision_id)
                .order_by(PageORM.pdf_page_index)
            ).scalars()
        ]

    read = papers_service.open_asset(raw_asset_id)
    blob = b"".join(_iter_bytes(read.stream))
    payload = json.loads(blob.decode("utf-8"))

    raw = _raw_document_from_payload(payload)

    candidates = normalize.build_media_candidates(
        scope,
        raw,
        pages=page_dtos,
        blocks=block_rows,
        page_index_by_id={pid: idx for pid, idx in page_rows},
        raw_asset_id=raw_asset_id,
    )
    log.info(
        "load_media_candidates: revision %s 重建 %d 个候选（raw 块 %d）",
        scope.revision_id, len(candidates), sum(
            len(getattr(p, "blocks", []) or []) for p in getattr(raw, "pages", [])
        ),
    )
    return candidates


def _iter_bytes(stream: Any) -> Any:
    """把 AssetRead.stream 的字节迭代器收敛为可 join 的分块（同步/异步皆容）。"""
    if stream is None:
        return []
    if hasattr(stream, "__aiter__"):
        raise DomainError(
            ErrorCode.INTERNAL_ERROR,
            "raw asset 流为异步迭代器，当前上下文不支持",
            retryable=False,
        )
    return list(stream)


def _raw_document_from_payload(payload: dict) -> RawDocument:
    """把 ``_persist_raw_asset`` 的 JSON 还原为 RawDocument（仅重放，不解释）。"""
    pages: List[RawPage] = []
    for p in payload.get("pages", []):
        blocks = [
            RawBlock(
                kind=b.get("kind", "text"),
                text=b.get("text", "") or "",
                bbox=b.get("bbox"),
                bbox_units=b.get("units") or "unknown",
                ordinal=int(b.get("ordinal") or i),
                table_html=b.get("table_html"),
                table_caption=b.get("table_caption"),
                img_path=b.get("img_path"),
                image_asset_id=b.get("image_asset_id"),
            )
            for i, b in enumerate(p.get("blocks") or [])
        ]
        pages.append(
            RawPage(
                pdf_page_index=int(p.get("pdf_page_index", 0)),
                width_pt=float(p.get("width_pt") or 0.0),
                height_pt=float(p.get("height_pt") or 0.0),
                rotation=int(p.get("rotation") or 0),
                blocks=blocks,
            )
        )
    return RawDocument(
        pages=pages,
        page_count=int(payload.get("page_count") or len(pages)),
        toc=payload.get("toc") or [],
    )


def get_pages(
    scope: Scope,
    cursor: Optional[str] = None,
    limit: int = pages_mod.DEFAULT_LIMIT,
    *,
    ctx: Optional[CallContext] = None,
) -> "Any":
    """分页读取页（只元数据，不含全文）。"""
    from app.contracts.common import PageResult

    size = pages_mod.clamp_limit(limit)
    offset = pages_mod.decode_cursor(cursor, scope)
    with session_scope() as db:
        _require_revision(db, scope)
        rows = list(
            db.execute(
                select(PageORM)
                .where(PageORM.revision_id == scope.revision_id)
                .order_by(PageORM.pdf_page_index.asc())
            ).scalars()
        )
        total = len(rows)
        window = rows[offset : offset + size]
        next_cursor = (
            pages_mod.encode_cursor(scope, offset + len(window)) if offset + len(window) < total
            else None
        )
        items = [_page_dto(scope, row) for row in window]
    return PageResult(items=items, next_cursor=next_cursor, total=total)


def get_blocks(scope: Scope, ids: List[str], *, ctx: Optional[CallContext] = None) -> List[Block]:
    if not ids:
        return []
    with session_scope() as db:
        _require_revision(db, scope)
        rows = list(
            db.execute(
                select(BlockORM).where(
                    BlockORM.revision_id == scope.revision_id,
                    BlockORM.id.in_(list(ids)),
                )
            ).scalars()
        )
        by_id = {r.id: r for r in rows}
        # 顺序严格按请求 ids；缺失视为不存在（由调用方判断）
        return [_block_dto(scope, by_id[i]) for i in ids if i in by_id]


def get_page(
    scope: Scope,
    pdf_page_no: int,
    *,
    ctx: Optional[CallContext] = None,
) -> PageContent:
    """路径物理页 1-based；超范围 404。"""
    if pdf_page_no < 1:
        raise not_found("页号必须 >= 1")
    index = pdf_page_no - 1
    with session_scope() as db:
        _require_revision(db, scope)
        page_row = db.execute(
            select(PageORM).where(
                PageORM.revision_id == scope.revision_id,
                PageORM.pdf_page_index == index,
            )
        ).scalars().first()
        if page_row is None:
            raise not_found(f"物理页 {pdf_page_no} 不存在")
        block_rows = list(
            db.execute(
                select(BlockORM)
                .where(BlockORM.revision_id == scope.revision_id, BlockORM.page_id == page_row.id)
                .order_by(BlockORM.ordinal.asc())
            ).scalars()
        )
        anchor_rows = list(
            db.execute(
                select(AnchorORM).where(AnchorORM.revision_id == scope.revision_id)
            ).scalars()
        )
        # DTO 必须在 session 内投影：session_scope 退出后 ORM 实例会 detached
        page = _page_dto(scope, page_row)
        blocks = [_block_dto(scope, r) for r in block_rows]
        anchors = [
            _anchor_dto(scope, r) for r in anchor_rows
            if any(seg.get("page_id") == page_row.id for seg in (r.segments or []))
        ]
    return PageContent(page=page, blocks=blocks, anchors=anchors)


def resolve_page_label(
    scope: Scope, label: str, *, ctx: Optional[CallContext] = None
) -> PageResolution:
    """解析印刷页标签；多义返回 ambiguous，绝不猜固定页差。"""
    with session_scope() as db:
        _require_revision(db, scope)
        rows = list(
            db.execute(
                select(PageLabelMappingORM)
                .join(PageORM, PageORM.id == PageLabelMappingORM.revision_id, isouter=True)
                .where(PageLabelMappingORM.revision_id == scope.revision_id)
            ).scalars()
        )
        mappings = [_label_dto(scope, r) for r in rows]
    return pages_mod.resolve_label(mappings, label)


def apply_page_overrides(
    scope: Scope,
    overrides: List[PageLabelOverride],
    ctx: Optional[CallContext] = None,
) -> ParseSummary:
    """只改 staging revision 的页码映射；源 hash 必须与被复核旧版一致。"""
    if not overrides:
        raise invalid_input("overrides 不能为空", field="overrides")

    with session_scope() as db:
        from app.modules.papers import repository as repo

        rev = repo.require_scope_revision(db, scope.paper_id, scope.revision_id)
        if rev.state != "staging":
            raise DomainError(
                ErrorCode.CONFLICT, "只允许修改 staging 修订版", retryable=False
            )
        source_hash = ""
        if rev.source_document_id:
            src = repo.get_source_row(db, rev.source_document_id)
            source_hash = (src.sha256 if src else "") or ""

        for override in overrides:
            if override.source_sha256 != source_hash:
                raise DomainError(
                    ErrorCode.REVISION_MISMATCH,
                    "override 的 source_sha256 与当前源文件不一致",
                    retryable=False,
                )
            db.add(
                PageLabelMappingORM(
                    id=_new_id(),
                    paper_id=scope.paper_id,
                    revision_id=scope.revision_id,
                    page_label=override.page_label,
                    pdf_page_index=override.pdf_page_index,
                    method="manual",
                    status="verified",
                    source_block_ids=[],
                    confidence=None,
                    review_id=override.review_id,
                )
            )
        db.flush()

        page_rows = list(
            db.execute(
                select(PageORM).where(PageORM.revision_id == scope.revision_id)
            ).scalars()
        )
        for override in overrides:
            for row in page_rows:
                if row.pdf_page_index == override.pdf_page_index:
                    row.page_label = override.page_label
                    row.label_status = "verified"
        db.flush()

        block_ids = [
            r.id
            for r in db.execute(
                select(BlockORM).where(BlockORM.revision_id == scope.revision_id)
            ).scalars()
        ]
        anchor_ids = [
            r.id
            for r in db.execute(
                select(AnchorORM).where(AnchorORM.revision_id == scope.revision_id)
            ).scalars()
        ]
        return ParseSummary(
            scope=scope,
            page_count=len(page_rows),
            block_ids=block_ids,
            anchor_ids=anchor_ids,
            media_candidates=[],
            raw_asset_ids=[],
            quality=rev.quality if rev.quality in ("complete", "partial", "source_only") else "source_only",
            warnings=[
                Warning(code="page_label_overridden", message="页码映射已按人工复核修订", stage="parse")
            ],
        )


# --------------------------------------------------------------- DTO 投影


def _page_dto(scope: Scope, row) -> Page:
    return Page(
        scope=scope,
        id=row.id,
        pdf_page_index=row.pdf_page_index,
        pdf_page_no=row.pdf_page_index + 1,
        page_label=row.page_label,
        label_status=row.label_status if row.label_status in
        ("verified", "candidate", "ambiguous", "unknown") else "unknown",
        width_pt=float(row.width_pt or 1.0),
        height_pt=float(row.height_pt or 1.0),
        rotation=row.rotation if row.rotation in (0, 90, 180, 270) else 0,
        cropbox_pdf=list(row.cropbox_pdf or [0.0, 0.0, 0.0, 0.0]),
        text=row.text or "",
        text_origin="source_extraction",
        preview_asset_id=row.preview_asset_id,
        extraction_quality=row.extraction_quality if row.extraction_quality in
        ("text", "ocr", "image_only", "empty") else "text",
    )


def _block_dto(scope: Scope, row) -> Block:
    from app.contracts.documents import RawRef

    raw_ref = None
    if row.raw_ref:
        try:
            raw_ref = RawRef(**row.raw_ref)
        except Exception:  # noqa: BLE001
            raw_ref = None
    return Block(
        scope=scope,
        id=row.id,
        page_id=row.page_id,
        ordinal=int(row.ordinal or 0),
        kind=row.kind if row.kind in (
            "heading", "paragraph", "caption", "table", "equation", "image",
            "header", "footer", "page_number", "other",
        ) else "other",
        text=row.text or "",
        origin="source_extraction",
        anchor_id=row.anchor_id,
        media_id=row.media_id,
        section_path=list(row.section_path or []),
        raw_ref=raw_ref,
        language=row.language or "",
        content_hash=row.content_hash,
    )


def _anchor_dto(scope: Scope, row) -> Anchor:
    from app.contracts.documents import AnchorSegment

    segments = []
    for seg in row.segments or []:
        try:
            segments.append(AnchorSegment(**seg))
        except Exception:  # noqa: BLE001
            continue
    return Anchor(
        scope=scope,
        id=row.id,
        source_document_id=row.source_document_id or "",
        precision=row.precision if row.precision in ("region", "page") else "page",
        segments=segments,
        transform=None,
        raw_ref=None,
        created_at=row.created_at,
    )


def _label_dto(scope: Scope, row) -> PageLabelMapping:
    return PageLabelMapping(
        scope=scope,
        id=row.id,
        page_label=row.page_label,
        pdf_page_index=row.pdf_page_index,
        method=row.method if row.method in ("pdf_metadata", "printed_ocr", "manual") else "printed_ocr",
        status=row.status if row.status in ("verified", "candidate", "ambiguous") else "candidate",
        source_block_ids=list(row.source_block_ids or []),
        confidence=row.confidence,
        review_id=row.review_id,
    )


def _require_revision(db, scope: Scope) -> None:
    from app.modules.papers import repository as repo

    repo.require_scope_revision(db, scope.paper_id, scope.revision_id)


def _new_id() -> str:
    return str(uuid.uuid4())


__all__ = [
    "parse",
    "persist",
    "get_pages",
    "get_blocks",
    "get_page",
    "resolve_page_label",
    "apply_page_overrides",
]
