"""artifact_blobs.kind 加宽到 128：装得下 page_preview 缓存键

Revision ID: 0007
Revises: 0006
Create Date: 2026-09-12

## 为什么改

``visual.ensure_page_preview`` 用 ``f"page_preview:{cache_key}"`` 当
``artifact_blobs.kind``，而 ``cache_key`` 是 ``preview_cache_key()`` 返回的
**64 位 sha256 hex** —— ``13 + 1 + 64 = 78`` 字符，远超原来的 ``varchar(32)``。
Postgres 直接报：

    DataError: value too long for type character varying(32)
    INSERT INTO artifact_blobs (... kind ...) VALUES (... 'page_preview:7a9f70d3...')

后果：``/api/papers/{id}/pages/{n}/preview`` **全部 500**（渲染成功但缓存写入失败、
异常逃逸）；阅读器的页面图因此完全不可用。

**为什么长期没被发现**：SQLite **不校验 VARCHAR 长度**，而单测跑在 SQLite 上，
只有 Postgres 会拒绝。回归测试 ``test_page_preview_cache.py`` 用
"组合出的 kind 长度 ≤ 列声明长度"的断言，把这一类缺陷变成 SQLite 也能拦住的测试。

## 安全性

**加宽**是纯 expand 操作：新长度比旧长度更宽松（旧值必然仍合法），
现存行无需回填，Postgres 下是元数据变更、不重写表。
``uq_artifact_revision_kind`` 唯一约束不受影响（列变宽不改变取值比较语义）。
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None

TABLE = "artifact_blobs"
COLUMN = "kind"
OLD_LENGTH = 32
NEW_LENGTH = 128


def _current_length(bind) -> int | None:
    insp = sa.inspect(bind)
    if TABLE not in set(insp.get_table_names()):
        return None
    for col in insp.get_columns(TABLE):
        if col["name"] == COLUMN:
            length = getattr(col["type"], "length", None)
            return int(length) if length is not None else None
    return None


def upgrade() -> None:
    bind = op.get_bind()
    length = _current_length(bind)
    if length is None or length >= NEW_LENGTH:
        return  # 表不存在、列不存在，或已加宽（helpers 首建时已是 128）——幂等
    with op.batch_alter_table(TABLE) as batch:
        batch.alter_column(
            COLUMN,
            existing_type=sa.String(length=length),
            type_=sa.String(length=NEW_LENGTH),
            existing_nullable=False,
        )


def downgrade() -> None:
    bind = op.get_bind()
    length = _current_length(bind)
    if length is None or length <= OLD_LENGTH:
        return
    with op.batch_alter_table(TABLE) as batch:
        batch.alter_column(
            COLUMN,
            existing_type=sa.String(length=length),
            type_=sa.String(length=OLD_LENGTH),
            existing_nullable=False,
        )
