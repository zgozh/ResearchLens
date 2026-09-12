"""页预览缓存：``artifact_blobs.kind`` 的长度契约（ADR-0023）。

真实缺陷（2026-09-12 实测）：``/api/papers/{id}/pages/{n}/preview`` **全部 500**。

``ensure_page_preview`` 用 ``f"page_preview:{cache_key}"`` 当 ``artifact_blobs.kind``，
而 ``cache_key`` 是 ``preview_cache_key()`` 返回的 **64 位 sha256 hex** ——
``13 + 1 + 64 = 78`` 字符，远超列的 ``varchar(32)``：

    DataError: value too long for type character varying(32)
    INSERT INTO artifact_blobs (... kind ...) VALUES (... 'page_preview:7a9f70d3...')

为什么一直没被发现：**SQLite 不校验 VARCHAR 长度**，而单测跑在 SQLite 上；
只有 Postgres 会报错。渲染本身是成功的，只是**缓存写入失败后异常逃逸成 500**，
于是每次请求都重新渲染再失败（``assets`` 里能攒下 ``page_preview`` 行，但缓存永不命中）。

本文件把"kind 必须装得下"变成**可在 SQLite 上跑的长度断言**，
让这一整类"列太窄 + 只有生产库报错"的缺陷能被单测拦住。
"""
from __future__ import annotations

import os

os.environ.setdefault("LLM_API_KEY", "")


def _declared_kind_length() -> int:
    from app.models.artifacts import ArtifactBlobORM

    length = ArtifactBlobORM.__table__.c.kind.type.length
    assert length is not None, "artifact_blobs.kind 必须有显式长度"
    return int(length)


def _composed_preview_kind() -> str:
    """复刻 ``ensure_page_preview`` 组合 kind 的方式（13 + 1 + 64）。"""
    from app.modules.visual import crops

    cache_key = crops.preview_cache_key("a" * 64, 0, crops.DEFAULT_PREVIEW_DPI)
    return f"page_preview:{cache_key}"


class TestArtifactBlobKindContract:
    def test_preview_cache_kind_fits_column(self):
        """**回归**：页预览缓存 kind 必须装得进 ``artifact_blobs.kind``。"""
        declared = _declared_kind_length()
        kind = _composed_preview_kind()

        assert len(kind) <= declared, (
            f"页预览缓存 kind 长 {len(kind)} 字符，超过 artifact_blobs.kind 的 "
            f"{declared} —— Postgres 会报 StringDataRightTruncation 并让 "
            f"/pages/{{n}}/preview 直接 500（SQLite 不校验，故单测此前发现不了）。"
            f"实际 kind={kind!r}"
        )

    def test_real_preview_asset_insert_roundtrip(self):
        """真写一次：插入该 kind 的 blob 必须成功（验证组合与模型一致）。"""
        from app.core.db import session_scope
        from app.models.artifacts import ArtifactBlobORM
        from app.modules import papers as papers_mod
        from app.contracts.documents import PaperCreate

        paper = papers_mod.create_paper(
            PaperCreate(title="页预览契约", source_mode="upload",
                        provenance_class="source_document")
        )
        kind = _composed_preview_kind()
        blob_id = f"blob-preview-contract-{paper.id}"
        with session_scope() as db:
            db.add(ArtifactBlobORM(
                id=blob_id, paper_id=paper.id, revision_id="rev-preview-contract",
                kind=kind, payload={"asset_id": "x", "pdf_page_index": 0, "dpi": 110},
            ))
        with session_scope() as db:
            row = db.get(ArtifactBlobORM, blob_id)
            assert row is not None and row.kind == kind
            db.delete(row)
