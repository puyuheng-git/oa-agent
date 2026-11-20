"""MCP 连接对员工开放标记。

Revision ID: 0018_mcp_employee_open
Revises: 0017_llm_model_routing
Create Date: 2026-11-20
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0018_mcp_employee_open"
down_revision = "0017_llm_model_routing"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    cols = {c["name"] for c in sa.inspect(conn).get_columns("agent_mcp_server")}
    if "employee_open" not in cols:
        op.add_column(
            "agent_mcp_server",
            sa.Column("employee_open", sa.Boolean(), nullable=False, server_default=sa.false()),
        )


def downgrade() -> None:
    with op.batch_alter_table("agent_mcp_server") as batch:
        batch.drop_column("employee_open")
