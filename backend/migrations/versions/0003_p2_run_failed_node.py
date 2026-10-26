"""P2：运行主表记录失败节点，便于列表与错误排行直接定位。

Revision ID: 0003_p2_run_failed_node
Revises: 0002_p1_run_event
Create Date: 2026-10-09
"""

from alembic import op
import sqlalchemy as sa

revision = "0003_p2_run_failed_node"
down_revision = "0002_p1_run_event"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("agent_run") as batch:
        batch.add_column(sa.Column("failed_node", sa.String(64), nullable=True))
        batch.create_index("ix_run_error", ["tenant_id", "error_code", "started_at"])
    op.execute(
        "UPDATE agent_run SET failed_node = ("
        " SELECT e.node_name FROM agent_run_event e"
        " WHERE e.run_id = agent_run.run_id AND e.event_type = 'run_end' AND e.node_name IS NOT NULL"
        " ORDER BY e.seq DESC LIMIT 1"
        ") WHERE failed_node IS NULL AND error_code IS NOT NULL"
    )


def downgrade() -> None:
    with op.batch_alter_table("agent_run") as batch:
        batch.drop_index("ix_run_error")
        batch.drop_column("failed_node")
