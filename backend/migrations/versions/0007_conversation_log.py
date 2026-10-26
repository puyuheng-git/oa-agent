"""完整对话记录与模型调用记录（查看与训练导出）。

Revision ID: 0007_conversation_log
Revises: 0006_p5_config_release
Create Date: 2026-10-10
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

revision = "0007_conversation_log"
down_revision = "0006_p5_config_release"
branch_labels = None
depends_on = None

BIGINT = sa.BigInteger().with_variant(sa.Integer(), "sqlite")
DT = sa.DateTime().with_variant(mysql.DATETIME(fsp=3), "mysql")
LONGTEXT = sa.Text().with_variant(mysql.LONGTEXT(), "mysql")
MYSQL_OPTS = {"mysql_charset": "utf8mb4", "mysql_collate": "utf8mb4_unicode_ci", "mysql_engine": "InnoDB"}


def upgrade() -> None:
    op.create_table(
        "agent_conversation_message",
        sa.Column("id", BIGINT, primary_key=True, autoincrement=True),
        sa.Column("message_id", sa.String(40), nullable=False),
        sa.Column("tenant_id", sa.String(32), nullable=False, server_default="dscpa"),
        sa.Column("thread_id", sa.String(40), nullable=False),
        sa.Column("run_id", sa.String(40), nullable=False),
        sa.Column("oa", sa.String(64), nullable=False),
        sa.Column("channel", sa.String(16), nullable=False, server_default=""),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("content", LONGTEXT, nullable=False),
        sa.Column("reply_type", sa.String(16), nullable=True),
        sa.Column("data_json", sa.JSON, nullable=True),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.Column("created_at", DT, nullable=False),
        sa.UniqueConstraint("message_id", name="uk_conversation_message_id"),
        **MYSQL_OPTS,
    )
    op.create_index("ix_conversation_thread", "agent_conversation_message", ["tenant_id", "thread_id", "id"])
    op.create_index("ix_conversation_time", "agent_conversation_message", ["tenant_id", "created_at"])
    op.create_index("ix_conversation_run", "agent_conversation_message", ["run_id"])
    op.create_table(
        "agent_model_call_log",
        sa.Column("id", BIGINT, primary_key=True, autoincrement=True),
        sa.Column("call_id", sa.String(40), nullable=False),
        sa.Column("tenant_id", sa.String(32), nullable=False, server_default="dscpa"),
        sa.Column("run_id", sa.String(40), nullable=False),
        sa.Column("thread_id", sa.String(40), nullable=False),
        sa.Column("oa", sa.String(64), nullable=False),
        sa.Column("node_name", sa.String(64), nullable=False, server_default=""),
        sa.Column("provider", sa.String(64), nullable=False, server_default=""),
        sa.Column("model", sa.String(128), nullable=False, server_default=""),
        sa.Column("messages_json", sa.JSON, nullable=False),
        sa.Column("output_text", LONGTEXT, nullable=True),
        sa.Column("parsed_json", sa.JSON, nullable=True),
        sa.Column("usage_json", sa.JSON, nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("error_summary", sa.Text, nullable=True),
        sa.Column("duration_ms", sa.Integer, nullable=True),
        sa.Column("created_at", DT, nullable=False),
        sa.UniqueConstraint("call_id", name="uk_model_call_id"),
        **MYSQL_OPTS,
    )
    op.create_index("ix_model_call_run", "agent_model_call_log", ["run_id"])
    op.create_index("ix_model_call_time", "agent_model_call_log", ["tenant_id", "created_at"])


def downgrade() -> None:
    for table in ("agent_model_call_log", "agent_conversation_message"):
        op.drop_table(table)
