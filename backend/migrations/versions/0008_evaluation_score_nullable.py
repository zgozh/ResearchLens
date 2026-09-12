"""evaluations.overall_score 放宽为可空：未评估时是**真 null**，不是 0

Revision ID: 0008
Revises: 0007
Create Date: 2026-09-12

## 为什么改

规格与产品纪律都写着：核心指标（含人工真值的 `support_precision` 等）不可测时
`overall_score` **必须是 null，不得用 0 冒充**。canonical 报告确实返回 `None`，
但旧的 legacy 投影为了迁就 `evaluations.overall_score` 的 ``NOT NULL`` 列，
**把 null 投影成 0.0**（`evaluation/legacy.py` 与 `schemas/adapters.py` 两处），
只靠 ``metrics["overall_score_available"]=false`` 提示。

实测后果：``curl /api/papers/1/evaluation`` 顶层直接返回 ``"overall_score": 0.0``
——任何只读这个字段的消费者（包括人肉验收）都会以为"评了 0 分"。
前端恰好有 flag 保护，但**契约本身在教人误读**，这属于"以假数字冒充"。

## 安全性

放宽 ``NOT NULL`` 是纯 expand 操作：现存行（含既有的 0.0）全部合法，无需回填；
SQLite 走 ``batch_alter_table`` 重建表，Postgres 是元数据变更。
downgrade 会把 NULL 回填成 0.0 再收回 NOT NULL（**有损**：无法区分"真 0"与"未评估"，
所以 downgrade 只在确实需要回退时用）。
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None

TABLE = "evaluations"
COLUMN = "overall_score"


def _is_nullable(bind) -> bool | None:
    insp = sa.inspect(bind)
    if TABLE not in set(insp.get_table_names()):
        return None
    for col in insp.get_columns(TABLE):
        if col["name"] == COLUMN:
            return bool(col.get("nullable", True))
    return None


def upgrade() -> None:
    bind = op.get_bind()
    nullable = _is_nullable(bind)
    if nullable is None or nullable:
        return  # 表/列不存在，或已可空（helpers 首建时即按模型建为可空）——幂等
    with op.batch_alter_table(TABLE) as batch:
        batch.alter_column(
            COLUMN,
            existing_type=sa.Float(),
            nullable=True,
            existing_nullable=False,
        )


def downgrade() -> None:
    bind = op.get_bind()
    nullable = _is_nullable(bind)
    if nullable is None or not nullable:
        return
    op.execute(sa.text(f"UPDATE {TABLE} SET {COLUMN} = 0.0 WHERE {COLUMN} IS NULL"))
    with op.batch_alter_table(TABLE) as batch:
        batch.alter_column(
            COLUMN,
            existing_type=sa.Float(),
            nullable=False,
            existing_nullable=True,
        )
