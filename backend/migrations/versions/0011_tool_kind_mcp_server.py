"""agent_tool 扩展 kind / builtin / mcp 字段；新增 agent_mcp_server；补 ops.mcp.manage 权限种子。

Revision ID: 0011_tool_kind_mcp_server
Revises: 0010_employee_memory
Create Date: 2026-10-27
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

revision = "0011_tool_kind_mcp_server"
down_revision = "0010_employee_memory"
branch_labels = None
depends_on = None

BIGINT = sa.BigInteger().with_variant(sa.Integer(), "sqlite")
DT = sa.DateTime().with_variant(mysql.DATETIME(fsp=3), "mysql")
MYSQL_OPTS = {"mysql_charset": "utf8mb4", "mysql_collate": "utf8mb4_unicode_ci", "mysql_engine": "InnoDB"}

PERM_CODE = "ops.mcp.manage"
SUPER_ADMIN_ROLE = "super_admin"


def upgrade() -> None:
    op.add_column("agent_tool", sa.Column("kind", sa.String(16), nullable=False, server_default="office"))
    op.add_column("agent_tool", sa.Column("builtin_id", sa.String(64), nullable=True))
    op.add_column("agent_tool", sa.Column("mcp_server_id", sa.BigInteger(), nullable=True))
    op.add_column("agent_tool", sa.Column("mcp_tool_name", sa.String(128), nullable=True))
    op.add_column("agent_tool", sa.Column("sandbox_policy_json", sa.JSON(), nullable=True))

    op.create_table(
        "agent_mcp_server",
        sa.Column("id", BIGINT, primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.String(32), nullable=False, server_default="dscpa"),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("display_name", sa.String(128), nullable=False, server_default=""),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("transport", sa.String(16), nullable=False),
        sa.Column("command", sa.String(255), nullable=True),
        sa.Column("args_json", sa.JSON(), nullable=True),
        sa.Column("env_json", sa.JSON(), nullable=True),
        sa.Column("url", sa.String(512), nullable=True),
        sa.Column("headers_secret_ref", sa.String(128), nullable=True),
        sa.Column("timeout_seconds", sa.Integer(), nullable=False, server_default="30"),
        sa.Column("tool_prefix", sa.String(32), nullable=False, server_default=""),
        sa.Column("last_sync_at", DT, nullable=True),
        sa.Column("last_sync_result", sa.String(16), nullable=True),
        sa.Column("last_sync_error", sa.Text(), nullable=True),
        sa.Column("created_by", sa.String(64), nullable=False, server_default=""),
        sa.Column("created_at", DT, nullable=False),
        sa.Column("updated_at", DT, nullable=False),
        sa.UniqueConstraint("tenant_id", "name", name="uk_mcp_server_name"),
        **MYSQL_OPTS,
    )

    # 幂等：仅给内置 super_admin 角色补权限行（权限目录以 auth/perms.py 为准）
    bind = op.get_bind()
    role_ids = [
        r[0]
        for r in bind.execute(
            sa.text("SELECT id FROM agent_admin_role WHERE code = :code"), {"code": SUPER_ADMIN_ROLE}
        )
    ]
    for rid in role_ids:
        exists = bind.execute(
            sa.text("SELECT 1 FROM agent_admin_role_perm WHERE role_id = :rid AND perm_code = :perm"),
            {"rid": rid, "perm": PERM_CODE},
        ).first()
        if exists is None:
            bind.execute(
                sa.text("INSERT INTO agent_admin_role_perm (role_id, perm_code) VALUES (:rid, :perm)"),
                {"rid": rid, "perm": PERM_CODE},
            )


def downgrade() -> None:
    op.get_bind().execute(
        sa.text("DELETE FROM agent_admin_role_perm WHERE perm_code = :perm"), {"perm": PERM_CODE}
    )
    op.drop_table("agent_mcp_server")
    with op.batch_alter_table("agent_tool") as batch:
        batch.drop_column("sandbox_policy_json")
        batch.drop_column("mcp_tool_name")
        batch.drop_column("mcp_server_id")
        batch.drop_column("builtin_id")
        batch.drop_column("kind")
