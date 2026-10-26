"""员工长期记忆 agent_employee_memory。

Revision ID: 0010_employee_memory
Revises: 0009_skill_visibility
Create Date: 2026-10-23
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

revision = "0010_employee_memory"
down_revision = "0009_skill_visibility"
branch_labels = None
depends_on = None

BIGINT = sa.BigInteger().with_variant(sa.Integer(), "sqlite")
DT = sa.DateTime().with_variant(mysql.DATETIME(fsp=3), "mysql")
MYSQL_OPTS = {"mysql_charset": "utf8mb4", "mysql_collate": "utf8mb4_unicode_ci", "mysql_engine": "InnoDB"}


def upgrade() -> None:
    op.create_table(
        "agent_employee_memory",
        sa.Column("id", BIGINT, primary_key=True, autoincrement=True),
        sa.Column("memory_id", sa.String(40), nullable=False),
        sa.Column("tenant_id", sa.String(32), nullable=False, server_default="dscpa"),
        sa.Column("oa", sa.String(64), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("text", sa.String(200), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="active"),
        sa.Column("source_thread_id", sa.String(40), nullable=True),
        sa.Column("created_at", DT, nullable=False),
        sa.Column("updated_at", DT, nullable=False),
        sa.UniqueConstraint("memory_id", name="uk_employee_memory_id"),
        **MYSQL_OPTS,
    )
    op.create_index(
        "ix_employee_memory_oa_status_upd",
        "agent_employee_memory",
        ["tenant_id", "oa", "status", "updated_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_employee_memory_oa_status_upd", table_name="agent_employee_memory")
    op.drop_table("agent_employee_memory")
