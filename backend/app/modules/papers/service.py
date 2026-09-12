"""M01 — 论文、原文件与资产存储（REFACTOR_SPEC §5.10 M01、§6.3）。

公共入口统一为 ``service.method(inputs, ctx: CallContext) -> Output``：

- ``create_paper(input, ctx)``            → PaperRecord
- ``store_source(paper_id, stream, metadata, ctx)`` → SourceDocument
- ``fetch_source(paper_id, url, ctx)``    → SourceDocument（worker 中执行）
- ``create_revision(paper_id, source_id, kind, ctx)`` → Revision
- ``get_paper(paper_id)``                 → PaperRecord
- ``get_revision(scope)``                 → Revision
- ``put_asset(input, stream, ctx)``       → Asset
- ``open_asset(asset_id, range)``         → AssetRead
- ``publish(scope, expected_revision, digest, quality, ctx)`` → PaperRecord
- ``get_metadata(paper_id)``              → LegacyPaperMetadata
- ``list_papers(source_modes)``           → PaperRecord[]
- ``get_source(scope)``                   → SourceDocument
- ``get_assets(scope, ids)``              → Asset[]

跨模块**不传 Session**：每个公共函数内部用 ``session_scope()`` 开短事务。
云调用（URL 下载）绝不持有写事务——先短事务读、再下载、再短事务写。
"""
from __future__ import annotations

from typing import Any, Iterable, List, Optional

from app.contracts.artifacts import Asset, AssetRead, AssetWrite, ByteRange
from app.contracts.common import CallContext, PaperId, RevisionId, Scope
from app.contracts.documents import (
    LegacyPaperMetadata,
    PaperCreate,
    PaperRecord,
    Revision,
    SourceDocument,
    SourceMetadata,
)
from app.core.config import settings
from app.core.db import session_scope
from app.core.errors import ErrorCode, DomainError, invalid_input, not_found, unsupported_media
from app.core.logging import get_logger

from . import download as download_mod
from . import repository as repo
from . import storage

log = get_logger(__name__)

_ACQUISITION = ("upload", "url", "seed")


# --------------------------------------------------------------- DTO 投影


def _paper_record(row) -> PaperRecord:
    return PaperRecord(
        id=int(row.id),
        slug=row.slug,
        title=row.title,
        source_mode=row.source_mode if row.source_mode in ("demo", "real", "upload") else "upload",
        provenance_class=(
            row.provenance_class
            if row.provenance_class in ("synthetic", "source_document")
            else "synthetic"
        ),
        status=row.status if row.status in ("pending", "processing", "ready", "failed") else "pending",
        published_revision_id=row.published_revision_id,
        readable_revision_id=row.readable_revision_id,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _source_dto(row) -> SourceDocument:
    return SourceDocument(
        id=row.id,
        paper_id=int(row.paper_id),
        sha256=row.sha256,
        asset_id=row.asset_id or "",
        byte_size=int(row.byte_size or 0),
        mime=row.mime or "application/pdf",
        page_count=int(row.page_count or 0),
        source_url=row.source_url or None,
        original_filename=row.original_filename or None,
        acquisition=row.acquisition if row.acquisition in _ACQUISITION else "upload",
        created_at=row.created_at,
    )


def _revision_dto(row) -> Revision:
    return Revision(
        id=row.id,
        paper_id=int(row.paper_id),
        source_document_id=row.source_document_id,
        kind=row.kind,
        state=row.state,
        parser_name=row.parser_name or "",
        parser_version=row.parser_version or "",
        normalizer_version=row.normalizer_version or "",
        prompt_version=row.prompt_version or "",
        model_snapshot_id=row.model_snapshot_id,
        artifact_digest=row.artifact_digest,
        quality=row.quality if row.quality in ("complete", "partial", "source_only") else "source_only",
        warnings=list(row.warnings or []),
        created_at=row.created_at,
    )


def snapshot_for_revision(scope: Scope) -> Optional[Any]:
    """该 revision **固定的**模型快照（缺失则回退当前运行时快照）。

    为什么必须有它（真实缺陷）：``/papers/{id}/qa`` 与 ``/qa/stream`` 此前用
    ``new_ctx(scope)``，而 ``new_ctx`` 的 ``snapshot`` 默认 ``None`` —— 于是 QA
    永远走不到模型：``qa/service.py`` 因 ``not snapshot_id`` 直接判
    ``llm_unavailable``、``mode=abstained``，前端只拿到空气泡 + "无证据支持"。
    而 revision 明明已经 pin 了 ``model_snapshot_id``。

    返回完整的 ``contracts.ai.ModelSnapshot``：``CallContext.model_snapshot`` 必须是
    它（``new_ctx`` 会归一化），而 ``CompletionRequest`` / 重排请求也要求这个类型。
    此前这里返回 ``ModelSnapshotLike``，导致下游请求校验失败 →
    ``qa/service._llm_draft`` 抛异常 → 降级抽取 → 为空 → **问答恒拒答**（空气泡）。
    """
    from app.contracts.ai import ModelSnapshot
    from app.models.source import ModelSnapshotORM, RevisionORM

    if scope.paper_id <= 0 or not scope.revision_id:
        return _runtime_snapshot()
    with session_scope() as db:
        row = db.get(RevisionORM, scope.revision_id)
        if row is None or not row.model_snapshot_id:
            return _runtime_snapshot()
        snap = db.get(ModelSnapshotORM, row.model_snapshot_id)
        if snap is None:
            # 历史数据：revision 指向的快照行缺失。退回运行时快照，
            # 好过让问答直接降级成拒答。
            return _runtime_snapshot()
        return ModelSnapshot(
            id=snap.id,
            provider=snap.provider if snap.provider == "dashscope" else "dashscope",
            base_url=snap.base_url or "",
            chat_model=snap.chat_model or "",
            embedding_model=snap.embedding_model,
            embedding_dimension=snap.embedding_dimension,
            capability_version=snap.capability_version or "rl.capabilities/1",
            temperature=float(snap.temperature or 0.2),
            created_at=snap.created_at,
        )


def _runtime_snapshot() -> Optional[Any]:
    """当前进程的运行时模型快照；取不到返回 ``None``（调用方据此降级，不伪造）。"""
    try:
        from app.modules.ai import capabilities as capabilities_mod

        return capabilities_mod.get_snapshot()
    except Exception:  # noqa: BLE001 - 快照缺失不得把请求变成 500
        return None


def _asset_dto(row) -> Asset:
    return Asset(
        id=row.id,
        paper_id=int(row.paper_id),
        revision_id=row.revision_id,
        sha256=row.sha256,
        mime=row.mime,
        byte_size=int(row.byte_size or 0),
        width_px=row.width_px,
        height_px=row.height_px,
        kind=row.kind,
        url=asset_url(row.id),
        created_at=row.created_at,
    )


def asset_url(asset_id: str) -> str:
    """后端受控资源地址，不暴露磁盘路径。"""
    return f"/api/assets/{asset_id}"


# --------------------------------------------------------------- 写入


def create_paper(input: PaperCreate, ctx: Optional[CallContext] = None) -> PaperRecord:
    """建立稳定 paper_id；幂等键命中时返回既有论文（不重复建、不删除重建）。"""
    title = (input.title or "").strip()
    if not title:
        raise invalid_input("论文标题不能为空", field="title")

    with session_scope() as db:
        if input.idempotency_key:
            from app.models.models import Paper
            from sqlalchemy import select

            stmt = select(Paper).where(Paper.slug == repo.make_slug(input.idempotency_key))
            existing = db.execute(stmt).scalars().first()
            if existing is not None:
                return _paper_record(existing)

        slug = repo.unique_slug(db, repo.make_slug(title, fallback=input.idempotency_key or "paper"))
        row = repo.insert_paper(
            db,
            title=title,
            slug=slug,
            source_mode=input.source_mode,
            provenance_class=input.provenance_class,
            status="pending",
        )
        return _paper_record(row)


def store_source(
    paper_id: PaperId,
    stream: Any,
    metadata: SourceMetadata,
    ctx: Optional[CallContext] = None,
) -> SourceDocument:
    """保存上传/seed 的源字节。相同内容不重复落盘（内容寻址）；不同步跑解析。"""
    filename = metadata.original_filename
    acquisition = metadata.acquisition if metadata.acquisition in _ACQUISITION else "upload"

    with session_scope() as db:
        repo.require_paper(db, paper_id)

    stored = storage.store_stream_sync(
        stream,
        kind_dir="sources",
        filename=filename,
        max_bytes=None,  # 用 settings.max_upload_bytes
    )

    head = storage.head_of(stored.abs_path)
    if not storage.looks_like_pdf(head):
        _cleanup(stored)
        raise unsupported_media("文件不是有效 PDF（魔数校验失败）")
    page_count = _probe_pdf_pages(stored.abs_path)

    with session_scope() as db:
        repo.require_paper(db, paper_id)

        existing = repo.find_source_by_hash(db, paper_id, stored.sha256)
        if existing is not None:
            return _source_dto(existing)

        asset = repo.find_asset_by_content(db, paper_id, stored.sha256, "source_pdf")
        if asset is None:
            asset = repo.insert_asset(
                db,
                paper_id=paper_id,
                revision_id=None,
                sha256=stored.sha256,
                mime="application/pdf",
                byte_size=stored.byte_size,
                rel_path=stored.rel_path,
                kind="source_pdf",
            )

        row = repo.insert_source_document(
            db,
            paper_id=paper_id,
            sha256=stored.sha256,
            asset_id=asset.id,
            byte_size=stored.byte_size,
            mime="application/pdf",
            page_count=page_count,
            source_url=download_mod.strip_credentials(metadata.source_url) or "",
            original_filename=storage.sanitize_filename(filename) if filename else "",
            acquisition=acquisition,
        )
        repo.update_paper_fields(db, paper_id, status="processing")
        return _source_dto(row)


def fetch_source(
    paper_id: PaperId,
    url: str,
    ctx: Optional[CallContext] = None,
) -> SourceDocument:
    """在 **worker 中** 执行受控下载（SSRF 防护）并保存为 SourceDocument。

    顺序：短事务读 paper → 云调用下载（无写事务）→ 短事务写入源文件。
    """
    with session_scope() as db:
        repo.require_paper(db, paper_id)

    result = download_mod.fetch(url)
    if not storage.looks_like_pdf(result.content[:2048]):
        raise unsupported_media("下载内容不是有效 PDF（魔数校验失败）")
    page_count = _probe_pdf_pages_bytes(result.content)

    stored = storage.store_stream_sync(
        result.content,
        kind_dir="sources",
        filename=_filename_from_url(result.final_url) or "downloaded.pdf",
        max_bytes=None,
    )
    if stored.sha256 != _sha256_of(result.content):
        _cleanup(stored)
        raise DomainError(ErrorCode.INTERNAL_ERROR, "下载内容 hash 不一致", retryable=False)

    with session_scope() as db:
        repo.require_paper(db, paper_id)
        existing = repo.find_source_by_hash(db, paper_id, stored.sha256)
        if existing is not None:
            return _source_dto(existing)

        asset = repo.find_asset_by_content(db, paper_id, stored.sha256, "source_pdf")
        if asset is None:
            asset = repo.insert_asset(
                db,
                paper_id=paper_id,
                revision_id=None,
                sha256=stored.sha256,
                mime="application/pdf",
                byte_size=stored.byte_size,
                rel_path=stored.rel_path,
                kind="source_pdf",
            )
        row = repo.insert_source_document(
            db,
            paper_id=paper_id,
            sha256=stored.sha256,
            asset_id=asset.id,
            byte_size=stored.byte_size,
            mime="application/pdf",
            page_count=page_count,
            source_url=download_mod.strip_credentials(result.final_url) or "",
            original_filename=_filename_from_url(result.final_url) or "",
            acquisition="url",
        )
        repo.update_paper_fields(db, paper_id, status="processing")
        return _source_dto(row)


def create_revision(
    paper_id: PaperId,
    source_id: Optional[str],
    kind: str,
    ctx: Optional[CallContext] = None,
) -> Revision:
    """新建 staging 修订版；source_id 必须属于该 paper。"""
    if kind not in ("source", "legacy", "synthetic"):
        raise invalid_input("kind 必须是 source/legacy/synthetic", field="kind")

    snapshot_id = None
    if ctx is not None and ctx.model_snapshot is not None:
        snap = ctx.model_snapshot
        data = snap.model_dump() if hasattr(snap, "model_dump") else dict(snap)
        with session_scope() as db:
            snapshot_id = repo.find_or_create_snapshot(db, data).id

    with session_scope() as db:
        repo.require_paper(db, paper_id)
        if source_id:
            src = repo.require_source(db, source_id)
            if int(src.paper_id) != int(paper_id):
                raise DomainError(ErrorCode.REVISION_MISMATCH, "源文件与论文不一致")
            quality = "source_only"
        else:
            if kind == "source":
                raise invalid_input("source 类型修订版必须提供源文件", field="source_id")
            quality = "source_only"

        row = repo.insert_revision(
            db,
            paper_id=paper_id,
            source_document_id=source_id,
            kind=kind,
            state="staging",
            model_snapshot_id=snapshot_id,
            quality=quality,
        )
        return _revision_dto(row)


def put_asset(
    input: AssetWrite,
    stream: Any,
    ctx: Optional[CallContext] = None,
) -> Asset:
    """内容寻址写入资产：临时文件 → sha256 → 原子 rename；同名不覆盖。"""
    with session_scope() as db:
        repo.require_paper(db, input.paper_id)
        if input.revision_id:
            repo.require_scope_revision(db, input.paper_id, input.revision_id)

    max_bytes = settings.max_upload_bytes
    stored = storage.store_stream_sync(stream, kind_dir="assets", filename=None, max_bytes=max_bytes)

    with session_scope() as db:
        repo.require_paper(db, input.paper_id)
        existing = repo.find_asset_by_content(db, input.paper_id, stored.sha256, input.kind)
        if existing is not None:
            return _asset_dto(existing)
        row = repo.insert_asset(
            db,
            paper_id=input.paper_id,
            revision_id=input.revision_id,
            sha256=stored.sha256,
            mime=input.mime or "application/octet-stream",
            byte_size=stored.byte_size,
            rel_path=stored.rel_path,
            kind=input.kind,
            width_px=input.width_px,
            height_px=input.height_px,
        )
        return _asset_dto(row)


# --------------------------------------------------------------- 读取


def get_paper(paper_id: PaperId) -> PaperRecord:
    with session_scope() as db:
        return _paper_record(repo.require_paper(db, paper_id))


def get_revision(scope: Scope) -> Revision:
    with session_scope() as db:
        row = repo.require_scope_revision(db, scope.paper_id, scope.revision_id)
        return _revision_dto(row)


def get_source(scope: Scope) -> SourceDocument:
    """读取 scope 对应的源文件；无源 NOT_FOUND。"""
    with session_scope() as db:
        rev = repo.require_scope_revision(db, scope.paper_id, scope.revision_id)
        if rev.source_document_id:
            src = repo.get_source_row(db, rev.source_document_id)
            if src is not None:
                return _source_dto(src)
        src = repo.get_source_for_paper(db, scope.paper_id)
        if src is None:
            raise not_found("该论文没有可用源文件")
        return _source_dto(src)


def get_assets(scope: Scope, ids: List[str]) -> List[Asset]:
    """批量读取资产；跨 paper 的资产一律视为不存在（不泄露他人资产）。"""
    with session_scope() as db:
        repo.require_scope_revision(db, scope.paper_id, scope.revision_id)
        rows = repo.get_assets_for_paper(db, scope.paper_id, ids or None)
        return [_asset_dto(r) for r in rows]


def list_papers(source_modes: Optional[List[str]] = None) -> List[PaperRecord]:
    with session_scope() as db:
        rows = repo.list_paper_rows(db, source_modes)
        return [_paper_record(r) for r in rows]


def _coerce_legacy_method_steps(raw: Any) -> List[dict]:
    """把旧库 ``method_steps`` 收敛为 LegacyMethodStep 可校验的 dict 列表。

    为什么需要（§5.11 明确要求）：
    旧库的 ``method_steps`` 是 Any 型 JSON，历史真实论文里存的是
    ``{"label", "phase", "detail", "color"}``，**没有 id**；而新契约
    ``LegacyMethodStep.id`` 是必填 ``str``。若直接透传，pydantic 校验失败会让
    整个 ``/api/papers/{id}/manifest``（以及任何走 ``get_metadata`` 的接口）
    返回 500 —— 即规格禁止的"以新 DTO 验证导致整个旧详情 500"。

    做法：字段缺失只做**可逆的占位补齐**（``legacy-step-{i}``），不猜测内容、
    不改写已有值；非 dict 的脏条目降级为最小结构而非丢弃，保持旧响应的
    条目数不变（§5.11 逐项保留）。
    """
    steps: List[dict] = []
    for i, item in enumerate(raw or []):
        if isinstance(item, dict):
            step = dict(item)
        else:
            # 非 dict 脏项：降级为最小结构，保留位置与可读文本
            step = {"id": str(item), "label": str(item)}
        # id 缺失/非字符串 → 按序号补稳定占位（同一输入必然得到同一 id）
        if not isinstance(step.get("id"), str) or not step["id"]:
            step["id"] = f"legacy-step-{i}"
        if not isinstance(step.get("label"), str):
            step["label"] = str(step.get("label") or "")
        # figure_ref 必须是 int|null；旧数据可能是字符串，不猜数字则置 None
        fr = step.get("figure_ref")
        if fr is not None and not isinstance(fr, int):
            step["figure_ref"] = None
        # 其余可选字段收敛为 str|null
        for key in ("phase", "detail", "text", "color"):
            val = step.get(key)
            if val is not None and not isinstance(val, str):
                step[key] = str(val)
        steps.append(step)
    return steps


def get_metadata(paper_id: PaperId) -> LegacyPaperMetadata:
    """旧详情元数据投影（不含可变 ORM 实例穿越）。"""
    with session_scope() as db:
        row = repo.require_paper(db, paper_id)
        steps = _coerce_legacy_method_steps(row.method_steps)
        return LegacyPaperMetadata(
            subtitle=row.subtitle or "",
            authors=list(row.authors or []),
            year=int(row.year or 2026),
            domain=row.domain or "general",
            abstract=row.abstract or "",
            tags=list(row.tags or []),
            map_summary=dict(row.map_summary or {}),
            pdf_url=row.pdf_url or "",
            method_steps=steps,
        )


def open_asset(asset_id: str, range: Optional[ByteRange] = None) -> AssetRead:
    """打开资产字节；**每次重新校验访问权限**与路径边界。

    Range 越界抛 INVALID_INPUT（API 层映射 416）。
    """
    with session_scope() as db:
        row = repo.require_asset(db, asset_id)
        asset = _asset_dto(row)
        rel_path = row.rel_path

    path = storage.resolve_asset_path(rel_path)
    total = path.stat().st_size

    if range is None:
        return AssetRead(
            asset=asset,
            stream=storage.iter_file_range(path, 0, None),
            total_size=total,
            range=None,
        )

    start = int(range.start)
    if start < 0:
        raise invalid_input("Range 起点必须 >= 0", field="Range")
    end = range.end_inclusive if range.end_inclusive is not None else total - 1
    if end < start:
        raise invalid_input("Range 终点小于起点", field="Range")
    if start >= total:
        raise invalid_input(
            f"Range 起点 {start} 超出资产长度 {total}", field="Range"
        )
    effective_end = min(end, total - 1)
    return AssetRead(
        asset=asset,
        stream=storage.iter_file_range(path, start, effective_end),
        total_size=total,
        range=ByteRange(start=start, end_inclusive=effective_end),
    )


# --------------------------------------------------------------- 发布


def publish(
    scope: Scope,
    expected_revision: Optional[RevisionId],
    digest: str,
    quality: str,
    ctx: Optional[CallContext] = None,
) -> PaperRecord:
    """CAS 发布：``expected_revision`` 与当前指针不符则 CONFLICT。

    仅接受 gate 完整性清单（``digest`` 必填、quality 受控），不覆盖他人发布。
    """
    if quality not in ("complete", "partial", "source_only"):
        raise invalid_input("quality 必须是 complete/partial/source_only", field="quality")
    if not digest:
        raise invalid_input("发布必须提供产物 digest", field="digest")

    with session_scope() as db:
        repo.require_scope_revision(db, scope.paper_id, scope.revision_id)
        row = repo.cas_publish(
            db,
            scope.paper_id,
            expected_revision=expected_revision,
            new_revision_id=scope.revision_id,
            quality=quality,
        )
        # 发布成功即成为可读版本（解析完成即可设置 readable，见 §5.8）
        if not row.readable_revision_id:
            row.readable_revision_id = scope.revision_id
            db.flush()
        return _paper_record(row)


def set_readable(scope: Scope, ctx: Optional[CallContext] = None) -> PaperRecord:
    """仅解析完成可设置 readable_revision_id，允许用户看原件。"""
    with session_scope() as db:
        repo.require_scope_revision(db, scope.paper_id, scope.revision_id)
        row = repo.update_paper_fields(
            db, scope.paper_id, readable_revision_id=scope.revision_id
        )
        return _paper_record(row)


# --------------------------------------------------------------- 内部辅助


def _cleanup(stored: storage.StoredBytes) -> None:
    try:
        stored.abs_path.unlink()
    except OSError:
        pass


def _sha256_of(data: bytes) -> str:
    import hashlib

    return hashlib.sha256(data).hexdigest()


def _probe_pdf_pages(path) -> int:
    try:
        import pymupdf  # type: ignore

        doc = pymupdf.open(str(path))
        try:
            return int(doc.page_count)
        finally:
            doc.close()
    except Exception:  # noqa: BLE001
        return 0


def _probe_pdf_pages_bytes(data: bytes) -> int:
    try:
        import pymupdf  # type: ignore

        doc = pymupdf.open(stream=data, filetype="pdf")
        try:
            return int(doc.page_count)
        finally:
            doc.close()
    except Exception:  # noqa: BLE001
        return 0


def _filename_from_url(url: str) -> Optional[str]:
    from urllib.parse import urlparse

    path = urlparse(url).path
    if not path or path.endswith("/"):
        return None
    return storage.sanitize_filename(path.rsplit("/", 1)[-1])


__all__ = [
    "create_paper",
    "store_source",
    "fetch_source",
    "create_revision",
    "get_paper",
    "get_revision",
    "get_source",
    "get_assets",
    "list_papers",
    "get_metadata",
    "put_asset",
    "open_asset",
    "publish",
    "set_readable",
    "asset_url",
]
