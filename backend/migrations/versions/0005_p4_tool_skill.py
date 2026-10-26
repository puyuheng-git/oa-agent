"""P4：Tool / Skill 注册表与版本。

Revision ID: 0005_p4_tool_skill
Revises: 0004_p3_intervention
Create Date: 2026-10-09
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

revision = "0005_p4_tool_skill"
down_revision = "0004_p3_intervention"
branch_labels = None
depends_on = None

BIGINT = sa.BigInteger().with_variant(sa.Integer(), "sqlite")
DT = sa.DateTime().with_variant(mysql.DATETIME(fsp=3), "mysql")
MYSQL_OPTS = {"mysql_charset": "utf8mb4", "mysql_collate": "utf8mb4_unicode_ci", "mysql_engine": "InnoDB"}


def _sync_columns() -> list:
    return [
        sa.Column("last_sync_at", DT, nullable=True),
        sa.Column("last_sync_result", sa.String(16), nullable=True),
        sa.Column("last_sync_error", sa.Text, nullable=True),
        sa.Column("updated_by", sa.String(64), nullable=False, server_default=""),
        sa.Column("updated_at", DT, nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "agent_tool",
        sa.Column("id", BIGINT, primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.String(32), nullable=False, server_default="dscpa"),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("source_file", sa.String(255), nullable=False, server_default=""),
        sa.Column("summary", sa.String(255), nullable=False, server_default=""),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default=sa.text("1")),
        sa.Column("spec_enabled", sa.Boolean, nullable=False, server_default=sa.text("0")),
        sa.Column("risk_level", sa.String(16), nullable=False, server_default="low"),
        sa.Column("requires_confirmation", sa.Boolean, nullable=False, server_default=sa.text("0")),
        sa.Column("current_version_id", sa.BigInteger, nullable=True),
        sa.Column("pending_version_id", sa.BigInteger, nullable=True),
        *_sync_columns(),
        sa.UniqueConstraint("tenant_id", "name", name="uk_tool_name"),
        **MYSQL_OPTS,
    )
    op.create_table(
        "agent_tool_version",
        sa.Column("id", BIGINT, primary_key=True, autoincrement=True),
        sa.Column("tool_id", sa.BigInteger, nullable=False),
        sa.Column("version_no", sa.Integer, nullable=False),
        sa.Column("spec_version", sa.String(32), nullable=False, server_default=""),
        sa.Column("schema_json", sa.JSON, nullable=False),
        sa.Column("schema_hash", sa.String(64), nullable=False),
        sa.Column("compat_level", sa.String(16), nullable=False),
        sa.Column("diff_json", sa.JSON, nullable=True),
        sa.Column("created_by", sa.String(64), nullable=False, server_default=""),
        sa.Column("created_at", DT, nullable=False),
        sa.UniqueConstraint("tool_id", "version_no", name="uk_tool_version_no"),
        **MYSQL_OPTS,
    )
    op.create_table(
        "agent_skill",
        sa.Column("id", BIGINT, primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.String(32), nullable=False, server_default="dscpa"),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("display_name", sa.String(128), nullable=False, server_default=""),
        sa.Column("source_file", sa.String(255), nullable=False, server_default=""),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default=sa.text("1")),
        sa.Column("current_version_id", sa.BigInteger, nullable=True),
        sa.Column("validation_status", sa.String(16), nullable=False, server_default="unknown"),
        sa.Column("validation_errors", sa.JSON, nullable=True),
        *_sync_columns(),
        sa.UniqueConstraint("tenant_id", "name", name="uk_skill_name"),
        **MYSQL_OPTS,
    )
    op.create_table(
        "agent_skill_version",
        sa.Column("id", BIGINT, primary_key=True, autoincrement=True),
        sa.Column("skill_id", sa.BigInteger, nullable=False),
        sa.Column("version_no", sa.Integer, nullable=False),
        sa.Column("spec_version", sa.String(32), nullable=False, server_default=""),
        sa.Column("content_json", sa.JSON, nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("created_by", sa.String(64), nullable=False, server_default=""),
        sa.Column("created_at", DT, nullable=False),
        sa.UniqueConstraint("skill_id", "version_no", name="uk_skill_version_no"),
        **MYSQL_OPTS,
    )


def downgrade() -> None:
    for table in ("agent_skill_version", "agent_skill", "agent_tool_version", "agent_tool"):
        op.drop_table(table)
