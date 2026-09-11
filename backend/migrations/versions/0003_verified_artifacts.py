"""verified artifacts：陈述 / 证据 / 校验 / 绑定 / 结构与方法产物

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-10

对应检查点 B（全局 Evidence Gate 与真实阅读器）。
"""
from __future__ import annotations

from alembic import op

from migrations.helpers import VERIFIED_TABLES, ensure_tables

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    ensure_tables(VERIFIED_TABLES, bind)


def downgrade() -> None:
    pass
