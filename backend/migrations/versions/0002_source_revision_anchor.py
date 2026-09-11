"""source revision anchor：源文件 / 修订版 / 资产 / 页块坐标 / 原件媒体

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-10

对应检查点 A（仅源文件/页码/原件及旧接口兼容）。
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from migrations.helpers import SOURCE_TABLES, ensure_columns, ensure_tables

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

_PAPER_COLUMNS = {
    "provenance_class": sa.String(24),
    "published_revision_id": sa.String(36),
    "readable_revision_id": sa.String(36),
    "updated_at": sa.DateTime(),
}


def upgrade() -> None:
    bind = op.get_bind()
    ensure_tables(SOURCE_TABLES, bind)
    ensure_columns(bind, "papers", _PAPER_COLUMNS)


def downgrade() -> None:
    # 保留新增列与表：回滚以切回旧读投影为主，不做破坏性 downgrade（§5.14）。
    pass
