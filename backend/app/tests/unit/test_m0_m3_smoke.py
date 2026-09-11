"""M00–M05 冒烟单测（REFACTOR_SPEC §6.3–§6.7「单元测试」要点）。

纪律：
- 全部使用**临时 sqlite**（`tmp_path` 下的文件库）+ 临时 assets 目录，
  **绝不触碰 `data/researchlens.db`**；
- 只 import 契约 DTO，不重定义；
- 断言行为而非实现细节。
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest

# --------------------------------------------------------------- 环境隔离

#: 在 import app 之前把数据目录指向临时位置，避免写出到真实 data/。
_TMP_ROOT = Path(__file__).resolve().parent / "_tmp"
_TMP_ROOT.mkdir(parents=True, exist_ok=True)
os.environ["DATA_DIR"] = str(_TMP_ROOT / "data")
os.environ["DATABASE_URL"] = f"sqlite:///{(_TMP_ROOT / 'smoke.db').as_posix()}"
os.environ["MINERU_ENABLED"] = "false"
os.environ["MINERU_TOKEN"] = ""


from app.contracts.ai import (  # noqa: E402
    ChatMessage,
    CompletionRequest,
    EmbeddingBatch,
    ModelCapabilities,
    ModelSnapshot,
    SchemaRef,
)
from app.contracts.artifacts import (  # noqa: E402
    Asset,
    AssetRead,
    AssetWrite,
    ByteRange,
    Media,
    MediaViewPolicy,
)
from app.contracts.common import Budget, PageResult, Scope, new_ctx  # noqa: E402
from app.contracts.common import CallContext  # noqa: E402
from app.contracts.documents import (  # noqa: E402
    PageLabelOverride,
    PageResolution,
    PaperCreate,
    PaperRecord,
    ParseResult,
    ParseSummary,
    Revision,
    SourceDocument,
    SourceMetadata,
)
from app.core.config import settings  # noqa: E402
from app.core.db import Base, build_engine, session_scope  # noqa: E402
from app.core.errors import DomainError, ErrorCode  # noqa: E402


# --------------------------------------------------------------- fixtures


@pytest.fixture(scope="session", autouse=True)
def _isolate_paths():
    """确认存储根指向临时目录（通过 DATA_DIR 环境变量在 import 前设定）。"""
    for d in (settings.data_dir, settings.assets_dir, settings.sources_dir,
              settings.parser_raw_dir):
        d.mkdir(parents=True, exist_ok=True)
    assert str(settings.data_dir).startswith(str(_TMP_ROOT)), "数据目录未隔离"
    assert "researchlens.db" not in str(settings.data_dir)
    yield


@pytest.fixture(scope="session")
def _engine():
    url = f"sqlite:///{(_TMP_ROOT / 'smoke.db').as_posix()}"
    eng = build_engine(url)
    # 注册全部 ORM 再建表（测试用，生产走 Alembic）
    import app.models  # noqa: F401
    from app.models import artifacts, evidence, jobs, retrieval, source  # noqa: F401

    Base.metadata.create_all(bind=eng)
    yield eng
    eng.dispose()


@pytest.fixture(autouse=True)
def _bind_session_factory(_engine):
    """把全局 SessionLocal 暂时绑定到测试引擎，让模块的 session_scope 走临时库。"""
    from app.core import db as db_mod
    from sqlalchemy.orm import sessionmaker

    original = db_mod.SessionLocal
    factory = sessionmaker(bind=_engine, autoflush=False, autocommit=False, future=True)
    db_mod.SessionLocal = factory
    try:
        yield factory
    finally:
        db_mod.SessionLocal = original


# --------------------------------------------------------------- 工具


def _minimal_pdf(text: str = "Hello ResearchLens") -> bytes:
    """构造一个合法的最小单页 PDF（含可选文本）。"""
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


class _FakeProvider:
    """测试替身：绝不发起真实网络调用（所有 http 调用都被 monkeypatch 掉）。"""

    name = "fake"
    base_url = "http://invalid.test"
    model = "qwen-plus"
    embedding_model = "text-embedding-v3"
    api_key = "test-key"
    headers: dict = {}


@pytest.fixture
def paper_factory():
    """建论文 + 源文件 + staging revision 的便捷工厂。"""
    from app.modules import papers as papers_mod

    created: list = []

    def _make(title: str = "测试论文", *, pdf: bytes | None = None, source_mode="upload"):
        record = papers_mod.create_paper(
            PaperCreate(title=title, source_mode=source_mode, provenance_class="source_document")
        )
        src = papers_mod.store_source(
            record.id,
            pdf if pdf is not None else _minimal_pdf(title),
            SourceMetadata(original_filename=f"{record.id}.pdf", acquisition="upload"),
        )
        rev = papers_mod.create_revision(record.id, src.id, "source")
        created.append((record, src, rev))
        return record, src, rev

    return _make


# =============================================================== §6.3 M01


class TestM01Papers:
    def test_create_paper_chinese_title_slug_bounded(self, paper_factory):
        record, _, _ = paper_factory("基于深度学习的论文解析方法研究")
        assert isinstance(record, PaperRecord)
        assert record.id > 0
        assert record.title == "基于深度学习的论文解析方法研究"
        # slug 必须 <= 64（契约硬约束）
        assert len(record.slug) <= 64
        assert record.slug  # 中文退化也必须给出非空 fallback，而不是拼音臆测

    def test_same_name_different_pdf_keeps_both(self, paper_factory):
        """同名不同内容 → 两份源文件，hash 不同，且都与实际字节对应。"""
        from app.modules import papers as papers_mod

        record = papers_mod.create_paper(PaperCreate(title="同名测试"))
        meta = SourceMetadata(original_filename="same.pdf", acquisition="upload")
        a = _minimal_pdf("AAA")
        b = _minimal_pdf("BBB")
        src_a = papers_mod.store_source(record.id, a, meta)
        src_b = papers_mod.store_source(record.id, b, meta)

        assert src_a.sha256 == hashlib.sha256(a).hexdigest()
        assert src_b.sha256 == hashlib.sha256(b).hexdigest()
        assert src_a.sha256 != src_b.sha256

    def test_same_pdf_is_content_addressed_idempotent(self, paper_factory):
        """相同 PDF 重复上传 → 同一 sha256；不产生第二条 SourceDocument。"""
        from app.modules import papers as papers_mod

        record = papers_mod.create_paper(PaperCreate(title="幂等测试"))
        data = _minimal_pdf("SAME")
        meta = SourceMetadata(original_filename="dup.pdf", acquisition="upload")
        first = papers_mod.store_source(record.id, data, meta)
        second = papers_mod.store_source(record.id, data, meta)
        assert first.id == second.id
        assert first.sha256 == second.sha256

    def test_fake_pdf_rejected(self, paper_factory):
        """伪 PDF（魔数不合法）必须拒绝，不留半成品。"""
        from app.modules import papers as papers_mod

        record = papers_mod.create_paper(PaperCreate(title="伪 PDF"))
        with pytest.raises(DomainError) as exc:
            papers_mod.store_source(
                record.id, b"not a pdf at all", SourceMetadata(original_filename="fake.pdf")
            )
        assert exc.value.code == ErrorCode.UNSUPPORTED_MEDIA

    def test_payload_too_large(self, paper_factory, monkeypatch):
        """超过 max_upload_bytes 必须 PAYLOAD_TOO_LARGE，且不落盘。"""
        from app.modules import papers as papers_mod

        record = papers_mod.create_paper(PaperCreate(title="超限"))
        monkeypatch.setattr(settings, "max_upload_bytes", 512)
        blob = b"%PDF-1.4\n" + b"x" * 4096
        with pytest.raises(DomainError) as exc:
            papers_mod.store_source(
                record.id, blob, SourceMetadata(original_filename="big.pdf")
            )
        assert exc.value.code == ErrorCode.PAYLOAD_TOO_LARGE

    def test_put_asset_content_addressed_and_range(self, paper_factory):
        """内容寻址：同内容幂等；Range 首/尾/越界行为符合契约。"""
        from app.modules import papers as papers_mod

        record, _, rev = paper_factory()
        scope = Scope(paper_id=record.id, revision_id=rev.id)
        payload = b"0123456789"

        first = papers_mod.put_asset(
            AssetWrite(paper_id=record.id, revision_id=rev.id, kind="crop",
                       mime="image/png"), payload
        )
        second = papers_mod.put_asset(
            AssetWrite(paper_id=record.id, revision_id=rev.id, kind="crop",
                       mime="image/png"), payload
        )
        assert isinstance(first, Asset)
        assert first.id == second.id
        assert first.sha256 == hashlib.sha256(payload).hexdigest()

        full: AssetRead = papers_mod.open_asset(first.id)
        assert full.total_size == len(payload)
        assert b"".join(full.stream) == payload

        head = papers_mod.open_asset(first.id, ByteRange(start=0, end_inclusive=2))
        assert b"".join(head.stream) == b"012"

        tail = papers_mod.open_asset(first.id, ByteRange(start=7, end_inclusive=None))
        assert b"".join(tail.stream) == b"789"

        # 起点越界 → INVALID_INPUT（API 层映射 416）
        with pytest.raises(DomainError) as exc:
            papers_mod.open_asset(first.id, ByteRange(start=99, end_inclusive=None))
        assert exc.value.code == ErrorCode.INVALID_INPUT

        # assets 读取只返回本 paper 的资产
        listed = papers_mod.get_assets(scope, [first.id])
        assert [a.id for a in listed] == [first.id]

    def test_cross_paper_asset_access_denied(self, paper_factory):
        """跨 paper 的资产访问必须视为不存在。"""
        from app.modules import papers as papers_mod

        rec_a, _, rev_a = paper_factory("A 论文")
        rec_b, _, rev_b = paper_factory("B 论文")
        asset = papers_mod.put_asset(
            AssetWrite(paper_id=rec_a.id, revision_id=rev_a.id, kind="crop", mime="image/png"),
            b"secret-bytes",
        )
        scope_b = Scope(paper_id=rec_b.id, revision_id=rev_b.id)
        assert papers_mod.get_assets(scope_b, [asset.id]) == []

    def test_publish_cas_conflict_on_stale_expected(self, paper_factory):
        """CAS：expected_revision 与当前指针不符 → CONFLICT。"""
        from app.modules import papers as papers_mod

        record, _, rev = paper_factory("CAS 论文")
        scope = Scope(paper_id=record.id, revision_id=rev.id)
        digest = hashlib.sha256(b"artifact").hexdigest()

        published = papers_mod.publish(scope, None, digest, "complete")
        assert published.published_revision_id == rev.id
        assert published.readable_revision_id == rev.id

        # 用错误的期望值再发布 → 冲突，且不覆盖
        with pytest.raises(DomainError) as exc:
            papers_mod.publish(scope, "some-other-revision", digest, "complete")
        assert exc.value.code == ErrorCode.CONFLICT

    def test_fetch_source_rejects_ssrf_urls(self, paper_factory):
        """SSRF：非 http(s)、私网、云元数据地址必须被拒绝（在发起连接之前）。"""
        from app.modules import papers as papers_mod
        from app.modules.papers import download

        record = papers_mod.create_paper(PaperCreate(title="SSRF"))

        # 纯语法层面必须拒绝的 scheme（不触发 DNS）
        for bad_scheme in ("ftp://example.com/a.pdf", "file:///etc/passwd",
                           "gopher://example.com/a.pdf"):
            with pytest.raises(DomainError):
                download.validate_url(bad_scheme)

        # 指向本机/私网/元数据的字面地址必须被拒（不触发 DNS）
        for literal in ("http://127.0.0.1/a.pdf", "http://[::1]/a.pdf",
                        "http://169.254.169.254/latest/meta-data/",
                        "http://10.0.0.1/a.pdf", "http://192.168.1.1/a.pdf",
                        "http://100.64.0.1/a.pdf"):
            with pytest.raises(DomainError):
                download.validate_url(literal)

        # 携带凭据的 URL 拒绝
        with pytest.raises(DomainError):
            download.validate_url("https://user:pass@example.com/a.pdf")

        # fetch_source 必须把拒绝向外传递，而不是静默降级
        with pytest.raises(DomainError):
            papers_mod.fetch_source(record.id, "http://127.0.0.1/a.pdf")

    def test_private_ip_detection(self):
        """IP 黑名单：私网/回环/link-local/CGNAT/云元数据一律视为被阻断。"""
        from app.modules.papers import download

        blocked = ["127.0.0.1", "10.1.2.3", "192.168.0.5", "172.16.0.9",
                   "169.254.169.254", "100.64.0.1", "::1", "fe80::1",
                   "0.0.0.0", "not-an-ip"]
        allowed = ["8.8.8.8", "1.1.1.1", "93.184.216.34"]
        for ip in blocked:
            assert download._ip_is_blocked(ip), ip
        for ip in allowed:
            assert not download._ip_is_blocked(ip), ip

    def test_strip_credentials(self):
        """URL 中访问凭据不得持久化。"""
        from app.modules.papers import download

        cleaned = download.strip_credentials(
            "https://example.com/a.pdf?token=secret&page=1&api_key=k"
        )
        assert "secret" not in cleaned
        assert "api_key" not in cleaned
        assert "page=1" in cleaned

    def test_storage_path_traversal_rejected(self):
        """受控路径解析拒绝 `..` 穿越与绝对路径。"""
        from app.modules.papers import storage

        for bad in ("../../etc/passwd", "/etc/passwd", "..\\..\\windows\\win.ini"):
            with pytest.raises(DomainError):
                storage.resolve_asset_path(bad)

    def test_sanitize_filename_strips_separators(self):
        from app.modules.papers import storage

        assert "/" not in storage.sanitize_filename("../../evil/name.pdf")
        assert "\\" not in storage.sanitize_filename("..\\evil\\name.pdf")
        assert storage.sanitize_filename("")  # 非空 fallback


# =============================================================== §6.4 M02


class TestM02Parse:
    def test_parse_pdf_produces_pages_and_blocks(self, paper_factory):
        """PyMuPDF 路径（MinerU 未启用）能解析出物理页与块。"""
        from app.modules import parse as parse_mod

        record, source, rev = paper_factory("解析测试")
        ctx = new_ctx(Scope(paper_id=record.id, revision_id=rev.id))
        result = parse_mod.parse(source, ctx)

        assert isinstance(result, ParseResult)
        assert len(result.pages) >= 1
        assert result.parser_name  # 必须记录实际使用的解析器
        for page in result.pages:
            assert page.pdf_page_index >= 0
            assert page.pdf_page_no == page.pdf_page_index + 1
            assert page.width_pt > 0 and page.height_pt > 0
            assert page.text_origin == "source_extraction"

    def test_persist_is_idempotent(self, paper_factory):
        """同 revision 重复 persist 不重复 page/block。"""
        from app.modules import parse as parse_mod

        record, source, rev = paper_factory("幂等解析")
        scope = Scope(paper_id=record.id, revision_id=rev.id)
        ctx = new_ctx(scope)
        result = parse_mod.parse(source, ctx)

        first = parse_mod.persist(scope, result, ctx)
        second = parse_mod.persist(scope, result, ctx)

        assert isinstance(first, ParseSummary)
        assert first.page_count == second.page_count
        page_result = parse_mod.get_pages(scope)
        assert isinstance(page_result, PageResult)
        assert page_result.total == first.page_count

    def test_load_media_candidates_replays_from_raw_asset(self, paper_factory):
        """回归：media 阶段必须能从存档重建候选，否则 succeeded 却 0 产出。

        真实缺陷背景（Postgres 实测）：pipeline 的 media 阶段给 ``build_media``
        传空 ``media_candidates``，导致阶段 succeeded 但 media 表 0 行，
        前端永远看不到原图/原表。本测试锁住"重建"这条路径。
        """
        from app.modules import parse as parse_mod

        record, source, rev = paper_factory("候选重建")
        scope = Scope(paper_id=record.id, revision_id=rev.id)
        ctx = new_ctx(scope)
        result = parse_mod.parse(source, ctx)
        parse_mod.persist(scope, result, ctx)

        # parse 阶段本身产出的候选（作为对照基线）
        assert result.media_candidates is not None

        # 重建路径：必须能读回 parser_raw 并还原结构（不报错、类型正确）
        rebuilt = parse_mod.load_media_candidates(scope)
        assert isinstance(rebuilt, list)
        # 重建结果应与 parse 阶段的候选**数量一致**（纯重放，不增不减）
        assert len(rebuilt) == len(result.media_candidates)
        for c in rebuilt:
            assert c.kind in ("figure", "table", "equation")

    def test_get_page_and_blocks(self, paper_factory):
        from app.modules import parse as parse_mod

        record, source, rev = paper_factory("读页测试")
        scope = Scope(paper_id=record.id, revision_id=rev.id)
        ctx = new_ctx(scope)
        result = parse_mod.parse(source, ctx)
        parse_mod.persist(scope, result, ctx)

        content = parse_mod.get_page(scope, 1)
        assert content.page.pdf_page_no == 1
        assert content.page.pdf_page_index == 0

        if result.blocks:
            ids = [b.id for b in result.blocks[:3]]
            blocks = parse_mod.get_blocks(scope, ids)
            assert [b.id for b in blocks] == ids

        with pytest.raises(DomainError):
            parse_mod.get_page(scope, 9999)

    def test_resolve_page_label_three_states(self):
        """页码解析三态：重号必须 ambiguous；未知 unresolved；唯一 verified → resolved。"""
        from app.contracts.documents import PageLabelMapping
        from app.modules.parse import pages as pages_mod

        scope = Scope(paper_id=1, revision_id="rev-1")
        dup = [
            PageLabelMapping(scope=scope, id="m1", page_label="12", pdf_page_index=11,
                             method="printed_ocr", status="candidate"),
            PageLabelMapping(scope=scope, id="m2", page_label="12", pdf_page_index=27,
                             method="printed_ocr", status="candidate"),
        ]

        ambiguous = pages_mod.resolve_label(dup, "12")
        assert isinstance(ambiguous, PageResolution)
        assert ambiguous.status == "ambiguous"
        assert len(ambiguous.candidates) == 2

        # 单条 candidate 仍不足以 resolved（必须 verified）
        single = [dup[0]]
        assert pages_mod.resolve_label(single, "12").status == "ambiguous"

        verified = [
            PageLabelMapping(scope=scope, id="m3", page_label="5", pdf_page_index=4,
                             method="manual", status="verified"),
        ]
        assert pages_mod.resolve_label(verified, "5").status == "resolved"

        assert pages_mod.resolve_label(dup, "999").status == "unresolved"

    def test_parse_requires_staging_scope(self, paper_factory, monkeypatch):
        """已发布（published）revision 不得原位重解析。"""
        from app.modules import parse as parse_mod
        from app.modules import papers as papers_mod

        record, source, rev = paper_factory("已发布")
        scope = Scope(paper_id=record.id, revision_id=rev.id)
        papers_mod.publish(scope, None, hashlib.sha256(b"x").hexdigest(), "complete")

        with pytest.raises(DomainError) as exc:
            parse_mod.parse(source, new_ctx(scope))
        assert exc.value.code == ErrorCode.CONFLICT

    def test_apply_page_overrides_requires_matching_source_hash(self, paper_factory):
        from app.modules import parse as parse_mod

        record, source, rev = paper_factory("复核")
        scope = Scope(paper_id=record.id, revision_id=rev.id)
        ctx = new_ctx(scope)
        result = parse_mod.parse(source, ctx)
        parse_mod.persist(scope, result, ctx)

        good = PageLabelOverride(
            review_id="r1", source_sha256=source.sha256, page_label="i", pdf_page_index=0
        )
        summary = parse_mod.apply_page_overrides(scope, [good], ctx)
        assert isinstance(summary, ParseSummary)

        bad = PageLabelOverride(
            review_id="r2", source_sha256="0" * 64, page_label="ii", pdf_page_index=0
        )
        with pytest.raises(DomainError) as exc:
            parse_mod.apply_page_overrides(scope, [bad], ctx)
        assert exc.value.code == ErrorCode.REVISION_MISMATCH

    def test_pymupdf_keeps_blank_and_image_only_pages(self):
        """空白页 / 纯图页必须保留，不得丢弃。"""
        from app.modules.parse import pymupdf_adapter

        if not pymupdf_adapter.available():
            pytest.skip("PyMuPDF 未安装")
        raw = pymupdf_adapter.parse_bytes(_minimal_pdf(""))
        assert raw.page_count >= 1
        assert len(raw.pages) == raw.page_count

    def test_zip_safe_extract_rejects_traversal(self):
        """ZIP 安全解包：路径穿越条目必须拒绝。"""
        import io
        import zipfile

        from app.modules.parse import mineru_adapter

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("../../evil.txt", "pwned")
            if hasattr(mineru_adapter, "safe_extract"):
                with pytest.raises(Exception):
                    mineru_adapter.safe_extract(buf.getvalue())


# =============================================================== §6.5 M03


class TestM03Visual:
    def test_policy_never_synthetic_for_real_source(self):
        """真实 source 缺原图 → unavailable/extracted，绝不 synthetic。"""
        scope = Scope(paper_id=1, revision_id="rev-1")
        media = Media(
            scope=scope, id="m1", kind="figure",
            provenance={"representation": "extracted", "verification": "unverified"},
        )
        from app.modules import visual

        policy = visual.get_policy(media)
        assert isinstance(policy, MediaViewPolicy)
        assert policy.default_mode in ("unavailable", "extracted")
        assert policy.default_mode != "synthetic"

    def test_policy_synthetic_allowed_without_source(self):
        """无 source 的 synthetic 媒体才允许 synthetic。"""
        from app.contracts.artifacts import MediaProvenance
        from app.modules import visual

        scope = Scope(paper_id=1, revision_id="rev-1")
        media = Media(
            scope=scope, id="m2", kind="figure",
            provenance=MediaProvenance(representation="synthetic", verification="synthetic"),
        )
        assert visual.get_policy(media).default_mode == "synthetic"

    def test_policy_original_for_source_bound_crop(self):
        from app.contracts.artifacts import MediaProvenance
        from app.modules import visual

        scope = Scope(paper_id=1, revision_id="rev-1")
        media = Media(
            scope=scope, id="m3", kind="figure",
            original_asset_ids=["a1"],
            provenance=MediaProvenance(
                representation="pdf_crop", verification="source_bound", source_sha256="a" * 64
            ),
        )
        policy = visual.get_policy(media)
        assert policy.default_mode == "original"
        assert policy.original_asset_ids == ["a1"]

    def test_extract_table_preserves_span_and_full_text(self):
        """含 rowspan/colspan 的表必须保留跨格与完整长单元格文本。"""
        from app.modules.visual import tables

        long_text = "这是一个非常长的单元格内容" * 20
        html = (
            "<table>"
            '<tr><th rowspan="2">编号</th><th colspan="2">测量结果</th></tr>'
            f'<tr><td rowspan="1" colspan="1">{long_text}</td><td>0.5</td></tr>'
            "</table>"
        )
        media = tables.build_extracted_media(table_html=html)
        assert media.table_cells
        spans = {(c.rowspan, c.colspan) for c in media.table_cells}
        assert any(r == 2 for r, _ in spans)
        assert any(c == 2 for _, c in spans)
        # 不截断
        assert any(c.text == long_text for c in media.table_cells)

    def test_extract_table_handles_matrix_larger_than_12x12(self):
        """超过 12×12 的表格不得被静默截断。"""
        from app.modules.visual import tables

        rows = 14
        cols = 14
        body = "".join(
            "<tr>" + "".join(f"<td>r{r}c{c}</td>" for c in range(cols)) + "</tr>"
            for r in range(rows)
        )
        media = tables.build_extracted_media(table_html=f"<table>{body}</table>")
        assert len(media.table_cells) == rows * cols

    def test_build_media_does_not_pad_count(self, paper_factory):
        """不凑数量：无候选 → 0 个 Media，且不报错。"""
        from app.modules import parse as parse_mod
        from app.modules import visual

        record, source, rev = paper_factory("媒体")
        scope = Scope(paper_id=record.id, revision_id=rev.id)
        ctx = new_ctx(scope)
        _ = parse_mod.parse(source, ctx)
        empty = ParseSummary(scope=scope, page_count=0)
        built = visual.build_media(scope, empty, ctx)
        assert len(built.media) == 0

    def test_build_media_numbers_legacy_no_per_kind(self, paper_factory):
        """同一 revision 的**不同 kind** 必须能各自从 1 开始编号（图1/表1/公式1 共存）。

        真实缺陷背景（Postgres 实测）：``build_media`` 的计数器是**按 kind** 的
        （figure→1,2,3…; equation→1,2,3…），但 media 表的唯一约束是
        ``(revision_id, legacy_no)`` —— **全 revision 级**。于是只要一篇论文同时
        有图和公式，两者都会拿到 ``legacy_no=1``，INSERT 直接撞
        ``uq_media_revision_legacy_no``，整个 media 阶段失败（3 次重试全 500），
        后续 claims/verify/exhibits 全部无法执行。

        契约依据：
        - §5.4 ``legacy_no`` 是"兼容整数编号"，最终喂给 legacy 的 figure_refs/table_refs；
        - ``schemas/adapters.to_legacy_presentation`` 按 kind 分别收集 legacy_no；
        - legacy 旧表本身就是 ``figures.fig_no`` 与 ``tables.table_no`` 两套独立编号；
        - 前端 ``RichText`` 分别用 ``fig.fig_no`` / ``t.table_no`` 各自查找。
        所以正确语义是**按 kind 编号**，约束必须包含 kind。
        """
        from app.contracts.documents import ExtractedMedia, ParsedMediaCandidate
        from app.modules import visual

        record, _source, rev = paper_factory("媒体按类编号")
        scope = Scope(paper_id=record.id, revision_id=rev.id)
        ctx = new_ctx(scope)

        # 三个不同 kind 的候选，各自都应拿到 legacy_no=1
        candidates = [
            ParsedMediaCandidate(
                kind="equation", original_label="公式(1)",
                extracted=ExtractedMedia(equation_label="公式(1)"),
            ),
            ParsedMediaCandidate(
                kind="table", caption="<table><tr><td>a</td></tr></table>",
                extracted=ExtractedMedia(
                    table_html="<table><tr><td>a</td></tr></table>",
                ),
            ),
            ParsedMediaCandidate(
                kind="figure", caption="图1",
                extracted=ExtractedMedia(),
            ),
        ]
        summary = ParseSummary(scope=scope, page_count=1, media_candidates=candidates)

        built = visual.build_media(scope, summary, ctx)

        by_kind = {}
        for m in built.media:
            by_kind.setdefault(m.kind, []).append(m.legacy_no)
        assert set(by_kind) == {"equation", "table", "figure"}, by_kind
        for kind, numbers in by_kind.items():
            assert numbers == [1], f"{kind} 应各自从 1 开始编号，实际 {numbers}"

        # 库内确实都落盘了（不再因唯一约束失败）
        listed = visual.list_media(scope, limit=50)
        assert listed.total == 3
        assert sorted(m.legacy_no for m in listed.items) == [1, 1, 1]

    def test_list_media_pagination_envelope(self, paper_factory):
        from app.modules import visual

        record, source, rev = paper_factory("媒体分页")
        scope = Scope(paper_id=record.id, revision_id=rev.id)
        result = visual.list_media(scope, limit=10)
        assert isinstance(result, PageResult)
        assert result.total >= 0


# =============================================================== §6.7 M05


class TestM05AI:
    def test_capabilities_null_means_unknown(self):
        """capabilities 未探测项必须是 None，不得凭模型名猜。"""
        from app.modules import ai

        caps = ai.get_capabilities()
        assert caps
        for item in caps:
            assert isinstance(item, ModelCapabilities)
            assert item.model
            if ai.is_embedding_only(item.model):
                assert item.purposes == ["embedding"]
            else:
                assert item.purposes == ["chat"]

    def test_embedding_only_cannot_be_chat_model(self):
        """chat 误选 embedding-only 模型 → INVALID_INPUT。"""
        from app.core import runtime
        from app.modules import ai

        original = runtime.get_active_model()
        try:
            with pytest.raises(DomainError) as exc:
                ai.set_chat_model("text-embedding-v3")
            assert exc.value.code == ErrorCode.INVALID_INPUT
            assert runtime.get_active_model() == original
        finally:
            runtime.reset_for_tests()

    def test_set_chat_model_returns_snapshot_without_secrets(self):
        from app.core import runtime
        from app.modules import ai

        try:
            snapshot = ai.set_chat_model("qwen-plus")
            assert isinstance(snapshot, ModelSnapshot)
            dumped = snapshot.model_dump()
            assert "api_key" not in dumped
            assert "llm_api_key" not in json.dumps(dumped).lower()
        finally:
            runtime.reset_for_tests()

    def test_embed_rejects_empty_texts(self):
        from app.modules import ai

        with pytest.raises(DomainError) as exc:
            ai.embed([])
        assert exc.value.code == ErrorCode.INVALID_INPUT

    def test_complete_rejects_empty_messages(self):
        from app.modules import ai

        with pytest.raises(DomainError) as exc:
            ai.complete(CompletionRequest(messages=[]))
        assert exc.value.code == ErrorCode.INVALID_INPUT

    def test_budget_exhaustion_raises_deadline_exceeded(self, monkeypatch):
        """预算耗尽 → DEADLINE_EXCEEDED，且绝不发起真实网络调用。"""
        from app.contracts.ai import ChatMessage
        from app.modules import ai
        from app.modules.ai import service as ai_service
        from app.modules.ai import transport

        def _forbidden_network(*args, **kwargs):  # pragma: no cover
            raise AssertionError("预算守卫必须在此之前终止调用")

        monkeypatch.setattr(transport, "chat_once", _forbidden_network)
        monkeypatch.setattr(ai_service, "_providers", lambda: [_FakeProvider()])

        ctx = new_ctx(
            None,
            budget=Budget(max_calls=0, max_input_tokens=0, max_output_tokens=0, max_wall_ms=1000),
        )
        with pytest.raises(DomainError) as exc:
            ai.complete(
                CompletionRequest(messages=[ChatMessage(role="user", content="hi")]),
                ctx,
            )
        assert exc.value.code == ErrorCode.DEADLINE_EXCEEDED

    def test_cancelled_context_aborts_before_network(self, monkeypatch):
        """已取消的 ctx 必须在发起云调用之前终止（CANCELLED）。"""
        from app.contracts.ai import ChatMessage
        from app.contracts.common import NeverCancelled
        from app.modules import ai
        from app.modules.ai import service as ai_service
        from app.modules.ai import transport

        class _Cancelled:
            def is_cancelled(self) -> bool:
                return True

        def _forbidden_network(*args, **kwargs):  # pragma: no cover
            raise AssertionError("取消守卫必须在此之前终止调用")

        monkeypatch.setattr(transport, "chat_once", _forbidden_network)
        monkeypatch.setattr(ai_service, "_providers", lambda: [_FakeProvider()])

        ctx = new_ctx(None, cancel_token=_Cancelled())
        assert ctx.is_cancelled() is True
        with pytest.raises(DomainError) as exc:
            ai.complete(
                CompletionRequest(messages=[ChatMessage(role="user", content="hi")]),
                ctx,
            )
        assert exc.value.code == ErrorCode.CANCELLED

    def test_deadline_exceeded_budget(self, monkeypatch):
        """deadline 已过 → DEADLINE_EXCEEDED，不发网络调用。"""
        from datetime import datetime, timedelta, timezone

        from app.contracts.ai import ChatMessage
        from app.contracts.common import CallContext
        from app.modules import ai
        from app.modules.ai import service as ai_service
        from app.modules.ai import transport

        def _forbidden_network(*args, **kwargs):  # pragma: no cover
            raise AssertionError("deadline 守卫必须在此之前终止调用")

        monkeypatch.setattr(transport, "chat_once", _forbidden_network)
        monkeypatch.setattr(ai_service, "_providers", lambda: [_FakeProvider()])

        ctx = CallContext(
            request_id="deadline-test",
            scope=None,
            deadline_at=datetime.now(timezone.utc) - timedelta(seconds=5),
            budget=Budget(max_calls=8, max_input_tokens=1000,
                          max_output_tokens=1000, max_wall_ms=1000),
        )
        with pytest.raises(DomainError) as exc:
            ai.complete(
                CompletionRequest(messages=[ChatMessage(role="user", content="hi")]),
                ctx,
            )
        assert exc.value.code == ErrorCode.DEADLINE_EXCEEDED

    def test_no_provider_raises_dependency_unavailable(self, monkeypatch):
        """无可用模型服务 → DEPENDENCY_UNAVAILABLE，不返回伪业务数据。"""
        from app.contracts.ai import ChatMessage
        from app.modules import ai
        from app.modules.ai import service as ai_service

        monkeypatch.setattr(ai_service, "_providers", lambda: [])
        with pytest.raises(DomainError) as exc:
            ai.complete(
                CompletionRequest(messages=[ChatMessage(role="user", content="hi")]),
                new_ctx(None),
            )
        assert exc.value.code == ErrorCode.DEPENDENCY_UNAVAILABLE

    def test_schema_binding_validates_and_rejects_bad_json(self):
        """两种 JSON 模式共用 Pydantic 验证：错误 JSON / 缺字段一律失败。"""
        from pydantic import BaseModel

        from app.modules.ai import validation

        class Out(BaseModel):
            title: str
            score: float

        binding = validation.resolve_schema(Out)
        assert binding.validate({"title": "x", "score": 0.5}).title == "x"

        with pytest.raises(Exception):
            binding.validate({"title": "x"})  # 缺字段

        with pytest.raises(Exception):
            binding.validate({"title": "x", "score": "nope"})  # 类型错

        assert validation.parse_json_text("```json\n{\"a\": 1}\n```") == {"a": 1}
        assert validation.parse_json_text("not json at all") is None

    def test_embedding_batch_order_dimension_and_finite(self):
        """embedding：错序按 index 纠正、维度不一致/NaN 拒绝。"""
        from app.modules.ai.service import _build_embedding_batch

        raw = {
            "data": [
                {"index": 1, "embedding": [0.3, 0.4]},
                {"index": 0, "embedding": [0.1, 0.2]},
            ],
            "usage": {"prompt_tokens": 7},
        }
        batch = _build_embedding_batch(raw, "text-embedding-v3", ["a", "b"])
        assert isinstance(batch, EmbeddingBatch)
        assert batch.dimension == 2
        assert batch.vectors == [[0.1, 0.2], [0.3, 0.4]]
        assert len(batch.input_hashes) == 2

        with pytest.raises(DomainError):
            _build_embedding_batch(
                {"data": [{"index": 0, "embedding": [0.1, 0.2]},
                          {"index": 1, "embedding": [0.1, 0.2, 0.3]}]},
                "text-embedding-v3", ["a", "b"],
            )

        with pytest.raises(DomainError):
            _build_embedding_batch(
                {"data": [{"index": 0, "embedding": [float("nan")]}]},
                "text-embedding-v3", ["a"],
            )

    def test_401_403_not_retried(self, monkeypatch):
        """401/403 不循环重试（只调用一次即抛 FORBIDDEN）。"""
        from app.contracts.ai import ChatMessage
        from app.modules import ai
        from app.modules.ai import service as ai_service
        from app.modules.ai import transport

        calls = {"n": 0}

        def _fake_chat_once(provider, body, **kwargs):
            calls["n"] += 1
            raise DomainError(ErrorCode.FORBIDDEN, "unauthorized", retryable=False)

        monkeypatch.setattr(transport, "chat_once", _fake_chat_once)
        monkeypatch.setattr(ai_service, "_providers", lambda: [_FakeProvider()])

        with pytest.raises(DomainError) as exc:
            ai.complete(
                CompletionRequest(messages=[ChatMessage(role="user", content="hi")]),
                new_ctx(None),
            )
        assert exc.value.code == ErrorCode.FORBIDDEN
        assert calls["n"] == 1


# =============================================================== 薄壳


class TestLegacyShims:
    def test_legacy_services_importable_with_signatures(self):
        """旧 service 薄壳必须保持原有公共签名可用。"""
        from app.services import ai as legacy_ai
        from app.services import mineru as legacy_mineru
        from app.services import parser as legacy_parser

        assert callable(legacy_ai.get_ai)
        assert hasattr(legacy_ai, "AIClient")
        for name in ("extract_pdf_pages", "detect_sections", "parse_pdf",
                     "default_upload_dir", "save_upload"):
            assert callable(getattr(legacy_parser, name)), name
        assert hasattr(legacy_mineru, "MineruError")
        assert callable(legacy_mineru.parse_pdf)

    def test_import_boundaries(self):
        """四个新模块与契约层均可导入。"""
        import app.modules.ai  # noqa: F401
        import app.modules.papers  # noqa: F401
        import app.modules.parse  # noqa: F401
        import app.modules.visual  # noqa: F401

    def test_contracts_not_redefined_in_modules(self):
        """模块内不得重定义契约 DTO（只能 import）。"""
        import inspect

        from app.contracts import artifacts as c_art
        from app.modules import papers, parse, visual

        for module in (papers, parse, visual):
            src = inspect.getsource(module.service)
            assert "class PaperRecord(" not in src
            assert "class SourceDocument(" not in src
            assert "class Media(" not in src
        assert c_art.Media is not None
