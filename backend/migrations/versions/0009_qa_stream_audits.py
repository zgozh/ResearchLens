"""新增 qa_stream_audits：流式问答审计（M7）

Revision ID: 0009
Revises: 0008
Create Date: 2026-09-13

## 为什么加

用户报"三条默认问题都显示本次回答被中断"，但用同样的请求复现时服务端**每次都有 final** ——
线上却没有**任何对账数据**：终结事件到底发出去没有、客户端是否断开，事后查不到。
本表把每次流式回答的生命周期落一行（事件类型序列 + 终结类型 + 错误码 + 耗时）。

## 安全性

纯 expand：只新增表与索引，不改任何既有列；全部业务字段可空。
`terminal='none'` 表示服务端没发出终结事件 —— 这是"前端被中断"的对账口径。
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "qa_stream_audits",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("paper_id", sa.Integer(), nullable=False),
        sa.Column("revision_id", sa.String(length=64), nullable=True),
        sa.Column("answer_id", sa.String(length=64), nullable=True),
        sa.Column("mode", sa.String(length=32), nullable=True),
        sa.Column("events", sa.JSON(), nullable=True),
        sa.Column("terminal", sa.String(length=16), nullable=False, server_default="none"),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("exception_type", sa.String(length=64), nullable=True),
        sa.Column("elapsed_ms", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_qa_audit_paper_created", "qa_stream_audits", ["paper_id", "created_at"])
    op.create_index("ix_qa_audit_answer", "qa_stream_audits", ["answer_id"])


def downgrade() -> None:
    op.drop_index("ix_qa_audit_answer", table_name="qa_stream_audits")
    op.drop_index("ix_qa_audit_paper_created", table_name="qa_stream_audits")
    op.drop_table("qa_stream_audits")
