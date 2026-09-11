"""legacy baseline：固化重构前的旧表结构（不删除任何列/表）

Revision ID: 0001
Revises:
Create Date: 2026-09-10

说明：旧库可能已经由 ``Base.metadata.create_all`` 建过表，因此这里全部使用
``checkfirst=True``，只补缺失的表；**不做**无条件 stamp。
"""
from __future__ import annotations

from alembic import op

from migrations.helpers import LEGACY_TABLES, ensure_tables

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    ensure_tables(LEGACY_TABLES, bind)


def downgrade() -> None:
    # baseline 不提供破坏性回滚：旧数据是迁移期唯一来源，禁止隐式删除。
    pass
