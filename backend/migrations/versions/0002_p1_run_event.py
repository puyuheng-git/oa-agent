"""P1：运行记录与事件。

Revision ID: 0002_p1_run_event
Revises: 0001_p0_init
Create Date: 2026-10-09
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

revision = "0002_p1_run_event"
down_revision = "0001_p0_init"
branch_labels = None
depends_on = None

BIGINT = sa.BigInteger().with_variant(sa.Integer(), "sqlite")
DT = sa.DateTime().with_variant(mysql.DATETIME(fsp=3), "mysql")
MYSQL_OPTS = {"mysql_charset": "utf8mb4", "mysql_collate": "utf8mb4_unicode_ci", "mysql_engine": "InnoDB"}


def upgrade() -> None:
    op.create_table(
        "agent_run",
        sa.Column("id", BIGINT, primary_key=True, autoincrement=True),
        sa.Column("run_id", sa.String(40), nullable=False),
        sa.Column("thread_id", sa.String(40), nullable=False),
        sa.Column("tenant_id", sa.String(32), nullable=False, server_default="dscpa"),
        sa.Column("oa", sa.String(64), nullable=False),
        sa.Column("channel", sa.String(16), nullable=False),
        sa.Column("agent_id", sa.String(64), nullable=False),
        sa.Column("workflow_id", sa.String(64), nullable=False),
        sa.Column("workflow_version", sa.String(32), nullable=False),
        sa.Column("config_release_id", sa.String(40), nullable=True),
        sa.Column("run_status", sa.String(24), nullable=False),
        sa.Column("started_at", DT, nullable=False),
        sa.Column("ended_at", DT, nullable=True),
        sa.Column("duration_ms", sa.Integer, nullable=True),
        sa.Column("last_event_at", DT, nullable=True),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.Column("error_summary", sa.Text, nullable=True),
        sa.Column("tool_call_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("model_call_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("usage_json", sa.JSON, nullable=True),
        sa.Column("business_type", sa.String(64), nullable=True),
        sa.Column("business_record_id", sa.String(64), nullable=True),
        sa.Column("business_status_snapshot", sa.String(255), nullable=True),
        sa.UniqueConstraint("run_id", name="uk_run_id"),
        **MYSQL_OPTS,
    )
    op.create_index("ix_run_started", "agent_run", ["tenant_id", "started_at"])
    op.create_index("ix_run_status", "agent_run", ["tenant_id", "run_status"])
    op.create_index("ix_run_thread", "agent_run", ["thread_id"])
    op.create_index("ix_run_oa", "agent_run", ["tenant_id", "oa"])

    op.create_table(
        "agent_run_event",
        sa.Column("id", BIGINT, primary_key=True, autoincrement=True),
        sa.Column("event_id", sa.String(40), nullable=False),
        sa.Column("run_id", sa.String(40), nullable=False),
        sa.Column("seq", sa.Integer, nullable=False),
        sa.Column("event_type", sa.String(32), nullable=False),
        sa.Column("node_name", sa.String(64), nullable=True),
        sa.Column("status", sa.String(16), nullable=True),
        sa.Column("occurred_at", DT, nullable=False),
        sa.Column("duration_ms", sa.Integer, nullable=True),
        sa.Column("tool_name", sa.String(128), nullable=True),
        sa.Column("tool_version", sa.String(32), nullable=True),
        sa.Column("correlation_id", sa.String(64), nullable=True),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.Column("error_summary", sa.Text, nullable=True),
        sa.Column("input_summary", sa.Text, nullable=True),
        sa.Column("output_summary", sa.Text, nullable=True),
        sa.Column("retry_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("operator_id", sa.String(64), nullable=True),
        sa.Column("metadata_json", sa.JSON, nullable=True),
        sa.UniqueConstraint("event_id", name="uk_run_event_id"),
        sa.UniqueConstraint("run_id", "seq", name="uk_run_event_seq"),
        **MYSQL_OPTS,
    )
    op.create_index("ix_run_event_type", "agent_run_event", ["event_type", "occurred_at"])


def downgrade() -> None:
    op.drop_table("agent_run_event")
    op.drop_table("agent_run")
