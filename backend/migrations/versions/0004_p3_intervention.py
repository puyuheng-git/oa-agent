"""P3：人工介入任务；运行记录重试链路。

Revision ID: 0004_p3_intervention
Revises: 0003_p2_run_failed_node
Create Date: 2026-10-09
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

revision = "0004_p3_intervention"
down_revision = "0003_p2_run_failed_node"
branch_labels = None
depends_on = None

BIGINT = sa.BigInteger().with_variant(sa.Integer(), "sqlite")
DT = sa.DateTime().with_variant(mysql.DATETIME(fsp=3), "mysql")
MYSQL_OPTS = {"mysql_charset": "utf8mb4", "mysql_collate": "utf8mb4_unicode_ci", "mysql_engine": "InnoDB"}


def upgrade() -> None:
    with op.batch_alter_table("agent_run") as batch:
        batch.add_column(sa.Column("parent_run_id", sa.String(40), nullable=True))

    op.create_table(
        "agent_intervention_task",
        sa.Column("id", BIGINT, primary_key=True, autoincrement=True),
        sa.Column("task_id", sa.String(40), nullable=False),
        sa.Column("tenant_id", sa.String(32), nullable=False, server_default="dscpa"),
        sa.Column("run_id", sa.String(40), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("reason", sa.String(255), nullable=False, server_default=""),
        sa.Column("node_name", sa.String(64), nullable=True),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.Column("confirm_token_hash", sa.String(64), nullable=True),
        sa.Column("binding_snapshot_json", sa.JSON, nullable=True),
        sa.Column("expire_at", DT, nullable=True),
        sa.Column("created_at", DT, nullable=False),
        sa.Column("handled_by", sa.String(64), nullable=True),
        sa.Column("handled_at", DT, nullable=True),
        sa.Column("result", sa.String(32), nullable=True),
        sa.Column("handle_note", sa.String(255), nullable=True),
        sa.Column("version", sa.Integer, nullable=False, server_default="1"),
        sa.UniqueConstraint("task_id", name="uk_intervention_task_id"),
        **MYSQL_OPTS,
    )
    op.create_index("ix_intervention_status", "agent_intervention_task", ["tenant_id", "status", "created_at"])
    op.create_index("ix_intervention_run", "agent_intervention_task", ["run_id"])


def downgrade() -> None:
    op.drop_table("agent_intervention_task")
    with op.batch_alter_table("agent_run") as batch:
        batch.drop_column("parent_run_id")
