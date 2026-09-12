"""图表「图片字节」：MinerU 提取的图必须落成 asset 并挂到 media（ADR-0024）。

真实缺陷（2026-09-12 实测）：前端拿到的"图"其实是 **JSON**。
- ``assets`` 表里图/裁剪类资产 **0 条**，74 条 media 全部指向 3 个 ``parser_raw``；
- ``GET /api/papers/3/media/{figure}`` → ``GET /api/assets/{id}`` 返回
  ``content-type: application/json``、161KB（就是 content_list 存档）。

成因链：
1. ``mineru_adapter.safe_extract`` 把 ZIP 里的 ``images/`` 收进 ``archive.images``，
   但 ``to_raw_document`` **不把它交给出来**，``img_path`` 也只进 ``RawPage.image_blocks``
   这个旁路字典，而 ``build_media_candidates`` 读的是 ``RawBlock`` —— 两边对不上；
2. ``normalize.build_media_candidates`` 于是用 ``embedded_asset_id=raw_asset_id``
   （= ``parser_raw`` 那份 JSON）顶替"MinerU 提取图"；
3. ``visual/service.py`` 把它写进 ``Media.original_asset_ids`` 并标 ``mineru_crop``。

修复方向：适配器只做纯数据（``RawBlock.img_path`` + ``RawDocument.images``），
由 ``parse()``（有 scope、能落库）把图字节存成 ``kind="image"`` 的 asset，
并把 asset id 写回 block；``build_media_candidates`` 只用**真实图资产**，
**绝不**再拿 ``parser_raw`` JSON 冒充图片。
"""
from __future__ import annotations

import os

import pytest

os.environ["LLM_API_KEY"] = ""
os.environ["LLM_API_KEY"] = ""

from app.contracts.common import Scope  # noqa: E402
from app.contracts.documents import PaperCreate, SourceMetadata  # noqa: E402


def _uniq(prefix: str) -> str:
    import uuid

    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def _minimal_pdf(text: str = "Hi") -> bytes:
    content = f"BT /F1 18 Tf 72 720 Td ({text}) Tj ET".encode("latin-1", "replace")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        b"<< /Length " + str(len(content)).encode() + b" >>\nstream\n" + content + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for i, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + body + b"\nendobj\n"
    xref_pos = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode()
    out += b"0000000000 65535 f \n"
    for off in offsets[1:]:
        out += f"{off:010d} 00000 n \n".encode()
    out += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref_pos}\n%%EOF\n"
    ).encode()
    return bytes(out)


#: 1x1 PNG（最小合法图），用于验证字节被原样落盘
_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
    "890000000a49444154789c6360000002000100ffff03000006000557bfabd400"
    "00000049454e44ae426082"
)


def _archive(items, images=None):
    from app.modules.parse.mineru_adapter import SafeArchive

    return SafeArchive(content_list=list(items), images=dict(images or {}),
                       markdown="# doc", total_bytes=0)


def _image_item(page_idx=0, img_path="images/fig1.jpg", caption="图 1 框架"):
    return {
        "type": "image", "page_idx": page_idx, "img_path": img_path,
        "image_caption": [caption], "bbox": [10, 20, 300, 400],
    }


@pytest.fixture
def world():
    from app.modules import papers as papers_mod

    paper = papers_mod.create_paper(
        PaperCreate(title="图片资产测试", source_mode="upload",
                    provenance_class="source_document")
    )
    source = papers_mod.store_source(
        paper.id, _minimal_pdf("img"), SourceMetadata(original_filename="i.pdf")
    )
    revision = papers_mod.create_revision(paper.id, source.id, "source")
    return {
        "paper": paper, "source": source, "revision": revision,
        "scope": Scope(paper_id=paper.id, revision_id=revision.id),
    }


@pytest.fixture
def page(world):
    from app.contracts.documents import Page

    return Page(scope=world["scope"], id=_uniq("pg"), pdf_page_index=0,
                pdf_page_no=1, width_pt=595.0, height_pt=842.0)


class TestAdapterCarriesImageData:
    def test_image_block_carries_img_path(self):
        """``img_path`` 必须落到 ``RawBlock``（而不是只进旁路 image_blocks）。"""
        from app.modules.parse import mineru_adapter

        doc = mineru_adapter.to_raw_document(_archive([_image_item()]))
        block = doc.pages[0].blocks[0]

        assert block.kind == "image"
        assert block.img_path == "images/fig1.jpg", f"实际 {block.img_path!r}"

    def test_raw_document_carries_zip_images(self):
        """适配器必须把解包出的图片字节交出来（否则 parse 无从落库）。"""
        from app.modules.parse import mineru_adapter

        doc = mineru_adapter.to_raw_document(
            _archive([_image_item()], images={"fig1.jpg": _PNG})
        )

        assert doc.images == {"fig1.jpg": _PNG}, "图片字节未随 RawDocument 传出"


class TestPersistMediaImages:
    def test_stores_image_asset_and_links_block(self, world, page):
        """``_persist_media_images`` 要把图字节存成 image asset 并写回 block。"""
        from app.core.db import session_scope
        from app.models.source import AssetORM
        from app.modules.parse import mineru_adapter, service as parse_service

        raw = mineru_adapter.to_raw_document(
            _archive([_image_item()], images={"fig1.jpg": _PNG})
        )
        stored = parse_service._persist_media_images(world["scope"], raw)
        block = raw.pages[0].blocks[0]

        assert stored == 1, f"应存下 1 张图，实际 {stored}"
        assert block.image_asset_id, "block 必须拿到 image asset id"
        with session_scope() as db:
            asset = db.get(AssetORM, block.image_asset_id)
            assert asset is not None
            # 契约 AssetKind 里表示图像字节的取值是 "crop"（与 pdf_crop 同类）
            assert asset.kind == "crop", f"asset kind 应为 crop，实际 {asset.kind}"
            assert asset.mime.startswith("image/"), f"mime 应为 image/*，实际 {asset.mime}"
            assert asset.byte_size == len(_PNG)

    def test_is_idempotent_on_rerun(self, world):
        """同图重复落库必须复用同一 asset（按 paper+sha256+kind 去重）。"""
        from app.modules.parse import mineru_adapter, service as parse_service

        first = mineru_adapter.to_raw_document(
            _archive([_image_item()], images={"fig1.jpg": _PNG})
        )
        parse_service._persist_media_images(world["scope"], first)
        second = mineru_adapter.to_raw_document(
            _archive([_image_item()], images={"fig1.jpg": _PNG})
        )
        parse_service._persist_media_images(world["scope"], second)

        assert first.pages[0].blocks[0].image_asset_id == \
            second.pages[0].blocks[0].image_asset_id

    def test_missing_image_bytes_is_skipped_without_crash(self, world):
        """ZIP 里没有对应图片时不得崩、也不得伪造 asset id。"""
        from app.modules.parse import mineru_adapter, service as parse_service

        raw = mineru_adapter.to_raw_document(_archive([_image_item()], images={}))
        stored = parse_service._persist_media_images(world["scope"], raw)

        assert stored == 0
        assert raw.pages[0].blocks[0].image_asset_id is None


class TestCandidateUsesRealImage:
    def _candidates(self, world, page, *, block_image_asset, raw_asset_id="raw-json-asset"):
        from app.modules.parse import normalize
        from app.modules.parse.mineru_adapter import RawBlock, RawDocument, RawPage

        block = RawBlock(kind="image", text="图 1 框架", bbox=[10, 20, 300, 400],
                         bbox_units="normalized", ordinal=0,
                         img_path="images/fig1.jpg")
        block.image_asset_id = block_image_asset
        raw = RawDocument(pages=[RawPage(pdf_page_index=0, width_pt=595.0,
                                        height_pt=842.0, blocks=[block])],
                          page_count=1)
        return normalize.build_media_candidates(
            world["scope"], raw, pages=[page], blocks=[], page_index_by_id={},
            raw_asset_id=raw_asset_id,
        )

    def test_candidate_uses_real_image_asset(self, world, page):
        (cand,) = self._candidates(world, page, block_image_asset="img-asset-1")

        assert cand.kind == "figure"
        assert cand.embedded_asset_id == "img-asset-1", (
            f"应挂真实图资产，实际 {cand.embedded_asset_id!r}"
        )

    def test_figure_never_falls_back_to_parser_raw_json(self, world, page):
        """**核心回归**：没有真图时 ``embedded_asset_id`` 必须为 None，
        绝不能拿 ``parser_raw`` 那份 JSON 冒充图片（前端会把它当图渲染）。"""
        (cand,) = self._candidates(world, page, block_image_asset=None)

        assert cand.embedded_asset_id is None, (
            f"不得把 parser_raw JSON 当图，实际 {cand.embedded_asset_id!r}"
        )


class TestReplayParity:
    def test_raw_payload_roundtrip_keeps_image_asset_id(self, world):
        """重放路径必须还原 ``image_asset_id``，否则重放出的候选又会丢图。"""
        import json

        from app.modules import papers as papers_mod
        from app.modules.parse import mineru_adapter, service as parse_service

        raw = mineru_adapter.to_raw_document(
            _archive([_image_item()], images={"fig1.jpg": _PNG})
        )
        parse_service._persist_media_images(world["scope"], raw)
        asset_id = raw.pages[0].blocks[0].image_asset_id

        raw_asset_id = parse_service._persist_raw_asset(
            world["scope"], raw, b"zip-bytes", mineru_adapter.ADAPTER_NAME
        )
        assert raw_asset_id
        read = papers_mod.open_asset(raw_asset_id)
        payload = json.loads(b"".join(read.stream or []).decode("utf-8"))

        restored = parse_service._raw_document_from_payload(payload)

        assert restored.pages[0].blocks[0].img_path == "images/fig1.jpg"
        assert restored.pages[0].blocks[0].image_asset_id == asset_id, (
            "重放后 image_asset_id 丢失 → 重放出的媒体候选又会指向空"
        )
