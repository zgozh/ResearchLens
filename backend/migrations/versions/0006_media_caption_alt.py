"""media.caption_alt：中英双语 caption 无损拆分（列）

Revision ID: 0006
Revises: 0005
Create Date: 2026-09-11

## 为什么加

MinerU 的 ``image_caption`` / ``table_caption`` 是**数组**，适配层用 ``" ".join``
整串拼接，于是**同一对象的中英双语 caption 被粘成一条**（3 篇真实论文实测 10 行），
例如 paper 1 图 7：

    (f) HH 分量 Fig.1 Comparison of the original image and stego images ... 图 1 原图像、各种隐写算法...

``Media`` 原本只有一个 ``caption`` 字段，因此"去重"必然**丢掉一种语言**。
本迁移加一个 ``caption_alt`` 列，把另一语言**无损**留在库里：展示只渲染主语言
（文档主导语言），另一种仍可审计/切换，符合 REFACTOR_SPEC「不丢原始信息」。

## 安全性

纯**新增可空列**（``NULL`` 允许、``server_default=''``），是标准的 expand 阶段：
- 不重写、不删除任何既有列；
- 既有行自动取默认空串，不需要回填；
- 读侧全部走 ``.get``/默认值，旧数据不会因此失败。

## 跨方言

用 ``batch_alter_table``（SQLite 走表重建、Postgres 走原生 ALTER），
并先探测列是否已存在，保证**幂等可重跑**（helpers 首次建库时已直接建成该列）。
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None

TABLE = "media"
COLUMN = "caption_alt"


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if TABLE not in set(insp.get_table_names()):
        return
    if COLUMN in {c["name"] for c in insp.get_columns(TABLE)}:
        return  # 已存在（helpers 首建或本迁移重复执行）
    with op.batch_alter_table(TABLE) as batch:
        batch.add_column(
            sa.Column(COLUMN, sa.Text(), nullable=False, server_default="")
        )


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if TABLE not in set(insp.get_table_names()):
        return
    if COLUMN not in {c["name"] for c in insp.get_columns(TABLE)}:
        return
    with op.batch_alter_table(TABLE) as batch:
        batch.drop_column(COLUMN)
