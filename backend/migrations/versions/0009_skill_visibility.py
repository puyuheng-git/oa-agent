"""Skill 可见性规则 agent_skill_visibility_rule。

Revision ID: 0009_skill_visibility
Revises: 0008_chat_thread
Create Date: 2026-10-23
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

revision = "0009_skill_visibility"
down_revision = "0008_chat_thread"
branch_labels = None
depends_on = None

BIGINT = sa.BigInteger().with_variant(sa.Integer(), "sqlite")
DT = sa.DateTime().with_variant(mysql.DATETIME(fsp=3), "mysql")
MYSQL_OPTS = {"mysql_charset": "utf8mb4", "mysql_collate": "utf8mb4_unicode_ci", "mysql_engine": "InnoDB"}


def upgrade() -> None:
    op.create_table(
        "agent_skill_visibility_rule",
        sa.Column("id", BIGINT, primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.String(32), nullable=False, server_default="dscpa"),
        sa.Column("skill_id", sa.BigInteger, nullable=False),
        sa.Column("effect", sa.String(8), nullable=False),
        sa.Column("principal_type", sa.String(16), nullable=False),
        sa.Column("principal_value", sa.String(128), nullable=False, server_default=""),
        sa.Column("created_by", sa.String(64), nullable=False, server_default=""),
        sa.Column("created_at", DT, nullable=False),
        sa.Column("updated_at", DT, nullable=False),
        sa.UniqueConstraint(
            "tenant_id",
            "skill_id",
            "effect",
            "principal_type",
            "principal_value",
            name="uk_skill_vis_rule",
        ),
        **MYSQL_OPTS,
    )
    op.create_index(
        "ix_skill_vis_tenant_skill",
        "agent_skill_visibility_rule",
        ["tenant_id", "skill_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_skill_vis_tenant_skill", table_name="agent_skill_visibility_rule")
    op.drop_table("agent_skill_visibility_rule")
