"""jobs / retrieval / audit：任务状态机、检索索引、审计与回填旧数据

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-10

包含「回填 legacy revision 与来源类别」：旧论文按 source_mode 标注 provenance_class，
并为每篇旧论文建立一条 ``legacy``/``synthetic`` 可读 revision。**不猜测物理页码**，
不回填任何 evidence 定位；历史记录一律保持 unverified。
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

import sqlalchemy as sa
from alembic import op

from migrations.helpers import OPS_TABLES, ensure_tables

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def _backfill_legacy_revisions(bind) -> None:  # noqa: C901
    insp = sa.inspect(bind)
    names = set(insp.get_table_names())
    if "papers" not in names or "revisions" not in names:
        return
    cols = {c["name"] for c in insp.get_columns("papers")}
    if "provenance_class" not in cols:
        return

    now = datetime.now(timezone.utc).isoformat()
    rows = bind.execute(
        sa.text(
            "SELECT id, source_mode, pdf_url, readable_revision_id, created_at "
            "FROM papers"
        )
    ).fetchall()

    for row in rows:
        paper_id, source_mode, pdf_url, readable_rev, created_at = (
            row[0], row[1], row[2], row[3], row[4],
        )
        # 1) 来源类别
        pclass = "synthetic" if (source_mode or "demo") == "demo" else "source_document"
        bind.execute(
            sa.text(
                "UPDATE papers SET provenance_class = :pc, updated_at = COALESCE(updated_at, :ts) "
                "WHERE id = :pid"
            ),
            {"pc": pclass, "ts": created_at or now, "pid": paper_id},
        )

        # 2) 缺省 readable revision
        if readable_rev:
            continue
        kind = "synthetic" if pclass == "synthetic" else "legacy"
        warnings = json.dumps(
            [
                {
                    "code": "legacy_migration",
                    "message": "由重构迁移回填的历史修订，未验证原文定位与页码。",
                    "stage": "migrate",
                }
            ],
            ensure_ascii=False,
        )
        rev_id = str(uuid.uuid4())
        bind.execute(
            sa.text(
                "INSERT INTO revisions (id, paper_id, source_document_id, kind, state, "
                "parser_name, parser_version, normalizer_version, prompt_version, "
                "model_snapshot_id, artifact_digest, quality, warnings, created_at, updated_at) "
                "VALUES (:id, :pid, NULL, :kind, 'readable', 'legacy', 'v1', 'legacy/1', "
                "'legacy/1', NULL, NULL, 'source_only', :warnings, :ts, :ts)"
            ),
            {"id": rev_id, "pid": paper_id, "kind": kind, "warnings": warnings, "ts": now},
        )
        bind.execute(
            sa.text("UPDATE papers SET readable_revision_id = :rid WHERE id = :pid"),
            {"rid": rev_id, "pid": paper_id},
        )


def upgrade() -> None:
    bind = op.get_bind()
    ensure_tables(OPS_TABLES, bind)
    _backfill_legacy_revisions(bind)


def downgrade() -> None:
    pass
