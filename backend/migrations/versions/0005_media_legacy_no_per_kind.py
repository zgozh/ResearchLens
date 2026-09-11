"""media.legacy_no 唯一约束改为按 kind：(revision_id, kind, legacy_no)

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-11

## 为什么改

``legacy_no`` 是**按 kind** 的兼容编号：图1/图2、表1/表2、公式1 各自独立。
契约依据：

- §5.4：``legacy_no:int|null`` 是"兼容整数编号"，最终喂给 legacy 的
  ``figure_refs`` / ``table_refs``；
- ``schemas/adapters.to_legacy_presentation``：按 ``kind`` 分别收集两个 refs 数组；
- legacy 旧表：``figures.fig_no`` 与 ``tables.table_no`` 本就是两套独立编号；
- 前端 ``RichText.tsx``：分别用 ``fig.fig_no`` / ``t.table_no`` 查找。

原约束 ``(revision_id, legacy_no)`` 是**全 revision 级**，与上述语义矛盾：
``build_media`` 的计数器按 kind 递增，于是同 revision 的第一张图与第一个公式
都取 ``legacy_no=1`` → 撞 ``uq_media_revision_legacy_no`` → 整个 media 阶段
失败（Postgres 实测 3 次重试全 500），claims/verify/exhibits 全部无法执行。

## 安全性

新约束比旧约束**更宽松**（旧成立 ⇒ 新必成立），因此现存数据不需要回填或去重，
迁移可原地完成、不会失败。

## 跨方言

SQLite 不支持独立的 ALTER 约束，统一用 ``batch_alter_table``（SQLite 走表重建、
Postgres 走原生 ALTER）。每步都先探测存在性，保证幂等可重跑。
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

OLD_NAME = "uq_media_revision_legacy_no"
NEW_NAME = "uq_media_revision_kind_legacy_no"


def _constraint_names(bind, table: str) -> set:
    """列出该表的唯一约束名（含 SQLite 以唯一索引实现的情况）。"""
    insp = sa.inspect(bind)
    names: set = set()
    try:
        for uc in insp.get_unique_constraints(table):
            if uc.get("name"):
                names.add(str(uc["name"]))
    except NotImplementedError:  # 某些方言不提供
        pass
    try:
        for ix in insp.get_indexes(table):
            if ix.get("unique") and ix.get("name"):
                names.add(str(ix["name"]))
    except NotImplementedError:
        pass
    return names


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if "media" not in set(insp.get_table_names()):
        return

    cols = {c["name"] for c in insp.get_columns("media")}
    if not {"revision_id", "kind", "legacy_no"} <= cols:
        return

    names = _constraint_names(bind, "media")
    if NEW_NAME in names:
        return  # 已是新约束（或由 helpers 首次建库时直接建成了新约束）

    if OLD_NAME in names:
        with op.batch_alter_table("media") as batch:
            batch.drop_constraint(OLD_NAME, type_="unique")

    with op.batch_alter_table("media") as batch:
        batch.create_unique_constraint(
            NEW_NAME, ["revision_id", "kind", "legacy_no"]
        )


def downgrade() -> None:
    """回退到全 revision 级唯一约束。

    注意：若库内**已存在**同 revision 同 kind 之外的重号（即新约束才允许的数据，
    例如图1 与公式1 共存），回退会失败——这是数据事实，不能静默丢数据。
    此时应先清理重号再回退。
    """
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if "media" not in set(insp.get_table_names()):
        return

    names = _constraint_names(bind, "media")
    if OLD_NAME in names:
        return

    if NEW_NAME in names:
        with op.batch_alter_table("media") as batch:
            batch.drop_constraint(NEW_NAME, type_="unique")

    with op.batch_alter_table("media") as batch:
        batch.create_unique_constraint(
            OLD_NAME, ["revision_id", "legacy_no"]
        )
