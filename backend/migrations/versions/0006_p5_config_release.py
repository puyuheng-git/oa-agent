"""P5：Agent 定义、Workflow 配置版本与发布记录。

Revision ID: 0006_p5_config_release
Revises: 0005_p4_tool_skill
Create Date: 2026-10-09
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

revision = "0006_p5_config_release"
down_revision = "0005_p4_tool_skill"
branch_labels = None
depends_on = None

BIGINT = sa.BigInteger().with_variant(sa.Integer(), "sqlite")
DT = sa.DateTime().with_variant(mysql.DATETIME(fsp=3), "mysql")
MYSQL_OPTS = {"mysql_charset": "utf8mb4", "mysql_collate": "utf8mb4_unicode_ci", "mysql_engine": "InnoDB"}


def upgrade() -> None:
    op.create_table(
        "agent_definition",
        sa.Column("id", BIGINT, primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.String(32), nullable=False, server_default="dscpa"),
        sa.Column("agent_id", sa.String(64), nullable=False),
        sa.Column("name", sa.String(128), nullable=False, server_default=""),
        sa.Column("workflow_id", sa.String(64), nullable=False),
        sa.Column("created_at", DT, nullable=False),
        sa.UniqueConstraint("tenant_id", "agent_id", name="uk_agent_definition"),
        **MYSQL_OPTS,
    )
    op.create_table(
        "agent_workflow_version",
        sa.Column("id", BIGINT, primary_key=True, autoincrement=True),
        sa.Column("version_id", sa.String(40), nullable=False),
        sa.Column("tenant_id", sa.String(32), nullable=False, server_default="dscpa"),
        sa.Column("workflow_id", sa.String(64), nullable=False),
        sa.Column("version_no", sa.Integer, nullable=True),
        sa.Column("content_json", sa.JSON, nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("validation_json", sa.JSON, nullable=True),
        sa.Column("validated_hash", sa.String(64), nullable=True),
        sa.Column("created_by", sa.String(64), nullable=False, server_default=""),
        sa.Column("created_at", DT, nullable=False),
        sa.Column("updated_by", sa.String(64), nullable=False, server_default=""),
        sa.Column("updated_at", DT, nullable=False),
        sa.Column("published_at", DT, nullable=True),
        sa.UniqueConstraint("version_id", name="uk_workflow_version_id"),
        **MYSQL_OPTS,
    )
    op.create_index("ix_workflow_version", "agent_workflow_version", ["tenant_id", "workflow_id", "status"])
    op.create_table(
        "agent_config_release",
        sa.Column("id", BIGINT, primary_key=True, autoincrement=True),
        sa.Column("release_id", sa.String(40), nullable=False),
        sa.Column("tenant_id", sa.String(32), nullable=False, server_default="dscpa"),
        sa.Column("workflow_id", sa.String(64), nullable=False),
        sa.Column("workflow_version_id", sa.String(40), nullable=False),
        sa.Column("version_no", sa.Integer, nullable=False),
        sa.Column("release_type", sa.String(16), nullable=False),
        sa.Column("reason", sa.String(255), nullable=False, server_default=""),
        sa.Column("previous_release_id", sa.String(40), nullable=True),
        sa.Column("released_by", sa.String(64), nullable=False, server_default=""),
        sa.Column("released_at", DT, nullable=False),
        sa.UniqueConstraint("release_id", name="uk_config_release_id"),
        **MYSQL_OPTS,
    )
    op.create_index("ix_config_release", "agent_config_release", ["tenant_id", "workflow_id", "id"])


def downgrade() -> None:
    for table in ("agent_config_release", "agent_workflow_version", "agent_definition"):
        op.drop_table(table)
