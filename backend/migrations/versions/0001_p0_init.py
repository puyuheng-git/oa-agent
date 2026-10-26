"""P0：后台账号/角色/权限、配置、密钥、LLM、审计。

Revision ID: 0001_p0_init
Revises:
Create Date: 2026-10-09
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

revision = "0001_p0_init"
down_revision = None
branch_labels = None
depends_on = None

BIGINT = sa.BigInteger().with_variant(sa.Integer(), "sqlite")
DT = sa.DateTime().with_variant(mysql.DATETIME(fsp=3), "mysql")
MYSQL_OPTS = {"mysql_charset": "utf8mb4", "mysql_collate": "utf8mb4_unicode_ci", "mysql_engine": "InnoDB"}

P0_PERMS = [
    "ops.run.view",
    "ops.run.view_sensitive",
    "ops.run.operate",
    "ops.intervention.handle",
    "ops.tool.manage",
    "ops.skill.manage",
    "ops.config.edit",
    "ops.config.publish",
    "ops.config.rollback",
    "sys.setting.view",
    "sys.setting.edit",
    "sys.account.manage",
    "ops.audit.view",
]


def _pk():
    return sa.Column("id", BIGINT, primary_key=True, autoincrement=True)


def _tenant():
    return sa.Column("tenant_id", sa.String(32), nullable=False, server_default="dscpa")


def upgrade() -> None:
    op.create_table(
        "agent_admin_user",
        _pk(),
        _tenant(),
        sa.Column("username", sa.String(64), nullable=False),
        sa.Column("display_name", sa.String(64), nullable=False, server_default=""),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="active"),
        sa.Column("failed_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("locked_until", DT, nullable=True),
        sa.Column("last_login_at", DT, nullable=True),
        sa.Column("password_changed_at", DT, nullable=True),
        sa.Column("created_at", DT, nullable=False),
        sa.Column("updated_at", DT, nullable=False),
        sa.UniqueConstraint("tenant_id", "username", name="uk_admin_user_username"),
        **MYSQL_OPTS,
    )
    role = op.create_table(
        "agent_admin_role",
        _pk(),
        _tenant(),
        sa.Column("code", sa.String(64), nullable=False),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("description", sa.String(255), nullable=False, server_default=""),
        sa.Column("is_builtin", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("created_at", DT, nullable=False),
        sa.Column("updated_at", DT, nullable=False),
        sa.UniqueConstraint("tenant_id", "code", name="uk_admin_role_code"),
        **MYSQL_OPTS,
    )
    role_perm = op.create_table(
        "agent_admin_role_perm",
        sa.Column("role_id", BIGINT, sa.ForeignKey("agent_admin_role.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("perm_code", sa.String(64), primary_key=True),
        **MYSQL_OPTS,
    )
    op.create_table(
        "agent_admin_user_role",
        sa.Column("user_id", BIGINT, sa.ForeignKey("agent_admin_user.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("role_id", BIGINT, sa.ForeignKey("agent_admin_role.id", ondelete="CASCADE"), primary_key=True),
        **MYSQL_OPTS,
    )
    op.create_table(
        "agent_setting",
        _pk(),
        _tenant(),
        sa.Column("setting_group", sa.String(32), nullable=False),
        sa.Column("setting_key", sa.String(64), nullable=False),
        sa.Column("value_json", sa.JSON, nullable=True),
        sa.Column("version", sa.Integer, nullable=False, server_default="1"),
        sa.Column("updated_by", sa.String(64), nullable=False, server_default=""),
        sa.Column("updated_at", DT, nullable=False),
        sa.UniqueConstraint("tenant_id", "setting_group", "setting_key", name="uk_setting_group_key"),
        **MYSQL_OPTS,
    )
    op.create_table(
        "agent_secret",
        _pk(),
        _tenant(),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("ciphertext", sa.LargeBinary, nullable=False),
        sa.Column("nonce", sa.LargeBinary(16), nullable=False),
        sa.Column("key_hint", sa.String(8), nullable=False, server_default=""),
        sa.Column("version", sa.Integer, nullable=False, server_default="1"),
        sa.Column("updated_by", sa.String(64), nullable=False, server_default=""),
        sa.Column("updated_at", DT, nullable=False),
        sa.UniqueConstraint("tenant_id", "name", name="uk_secret_name"),
        **MYSQL_OPTS,
    )
    op.create_table(
        "agent_llm_provider",
        _pk(),
        _tenant(),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("provider_type", sa.String(32), nullable=False, server_default="openai_compatible"),
        sa.Column("base_url", sa.String(255), nullable=False),
        sa.Column("secret_ref", sa.String(128), nullable=True),
        sa.Column("timeout_seconds", sa.Integer, nullable=False, server_default="60"),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("updated_by", sa.String(64), nullable=False, server_default=""),
        sa.Column("created_at", DT, nullable=False),
        sa.Column("updated_at", DT, nullable=False),
        sa.UniqueConstraint("tenant_id", "name", name="uk_llm_provider_name"),
        **MYSQL_OPTS,
    )
    op.create_table(
        "agent_llm_model",
        _pk(),
        _tenant(),
        sa.Column("provider_id", BIGINT, sa.ForeignKey("agent_llm_provider.id"), nullable=False),
        sa.Column("model_name", sa.String(128), nullable=False),
        sa.Column("display_name", sa.String(128), nullable=False, server_default=""),
        sa.Column("params_json", sa.JSON, nullable=True),
        sa.Column("purpose_tags", sa.JSON, nullable=True),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("updated_by", sa.String(64), nullable=False, server_default=""),
        sa.Column("created_at", DT, nullable=False),
        sa.Column("updated_at", DT, nullable=False),
        sa.UniqueConstraint("provider_id", "model_name", name="uk_llm_model_provider_name"),
        **MYSQL_OPTS,
    )
    op.create_table(
        "agent_audit_log",
        _pk(),
        sa.Column("audit_id", sa.String(40), nullable=False),
        sa.Column("actor_type", sa.String(16), nullable=False),
        sa.Column("actor_id", sa.String(64), nullable=False),
        _tenant(),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("resource_type", sa.String(32), nullable=False, server_default=""),
        sa.Column("resource_id", sa.String(128), nullable=False, server_default=""),
        sa.Column("before_summary", sa.Text, nullable=True),
        sa.Column("after_summary", sa.Text, nullable=True),
        sa.Column("result", sa.String(16), nullable=False),
        sa.Column("reason", sa.String(255), nullable=False, server_default=""),
        sa.Column("occurred_at", DT, nullable=False),
        sa.Column("request_id", sa.String(64), nullable=False, server_default=""),
        sa.Column("source_ip", sa.String(64), nullable=False, server_default=""),
        sa.Column("correlation_id", sa.String(64), nullable=False, server_default=""),
        sa.UniqueConstraint("audit_id", name="uk_audit_id"),
        **MYSQL_OPTS,
    )
    op.create_index("ix_audit_occurred", "agent_audit_log", ["tenant_id", "occurred_at"])
    op.create_index("ix_audit_actor", "agent_audit_log", ["actor_type", "actor_id"])
    op.create_index("ix_audit_resource", "agent_audit_log", ["resource_type", "resource_id"])

    from datetime import UTC, datetime

    now = datetime.now(UTC).replace(tzinfo=None)
    op.bulk_insert(
        role,
        [
            {
                "id": 1,
                "tenant_id": "dscpa",
                "code": "super_admin",
                "name": "超级管理员",
                "description": "内置角色，拥有全部权限点（含后续新增）",
                "is_builtin": True,
                "created_at": now,
                "updated_at": now,
            }
        ],
    )
    op.bulk_insert(role_perm, [{"role_id": 1, "perm_code": p} for p in P0_PERMS])


def downgrade() -> None:
    for t in (
        "agent_audit_log",
        "agent_llm_model",
        "agent_llm_provider",
        "agent_secret",
        "agent_setting",
        "agent_admin_user_role",
        "agent_admin_role_perm",
        "agent_admin_role",
        "agent_admin_user",
    ):
        op.drop_table(t)
