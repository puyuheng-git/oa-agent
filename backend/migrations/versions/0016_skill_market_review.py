"""Skill 市场：模型审查 + 管理员审核字段。

Revision ID: 0016_skill_market_review
Revises: 0015_skill_market_description
Create Date: 2026-11-16
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0016_skill_market_review"
down_revision = "0015_skill_market_description"
branch_labels = None
depends_on = None

_TABLE = "agent_skill_market_listing"
# MySQL TEXT 不能带 DEFAULT；其余字符串列可带 server_default
_COLUMNS = (
    ("model_review_status", sa.Column("model_review_status", sa.String(16), nullable=False, server_default="")),
    ("model_review_summary", sa.Column("model_review_summary", sa.Text(), nullable=True)),
    ("model_review_recommend", sa.Column("model_review_recommend", sa.String(16), nullable=False, server_default="")),
    ("model_reviewed_at", sa.Column("model_reviewed_at", sa.DateTime(), nullable=True)),
    ("admin_note", sa.Column("admin_note", sa.String(512), nullable=False, server_default="")),
    ("admin_reviewer", sa.Column("admin_reviewer", sa.String(64), nullable=False, server_default="")),
    ("admin_reviewed_at", sa.Column("admin_reviewed_at", sa.DateTime(), nullable=True)),
)


def upgrade() -> None:
    # 幂等：上次半成功迁移可能已加了部分列
    conn = op.get_bind()
    existing = {c["name"] for c in sa.inspect(conn).get_columns(_TABLE)}
    for name, col in _COLUMNS:
        if name not in existing:
            op.add_column(_TABLE, col)


def downgrade() -> None:
    conn = op.get_bind()
    existing = {c["name"] for c in sa.inspect(conn).get_columns(_TABLE)}
    for name, _ in reversed(_COLUMNS):
        if name in existing:
            op.drop_column(_TABLE, name)
