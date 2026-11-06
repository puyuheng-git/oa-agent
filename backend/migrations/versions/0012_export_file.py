"""导出文件登记 agent_export_file；补 ops.file.view 权限种子。

Revision ID: 0012_export_file
Revises: 0011_tool_kind_mcp_server
Create Date: 2026-11-05
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

revision = "0012_export_file"
down_revision = "0011_tool_kind_mcp_server"
branch_labels = None
depends_on = None

BIGINT = sa.BigInteger().with_variant(sa.Integer(), "sqlite")
DT = sa.DateTime().with_variant(mysql.DATETIME(fsp=3), "mysql")
MYSQL_OPTS = {"mysql_charset": "utf8mb4", "mysql_collate": "utf8mb4_unicode_ci", "mysql_engine": "InnoDB"}

PERM_CODE = "ops.file.view"
SUPER_ADMIN_ROLE = "super_admin"


def upgrade() -> None:
    op.create_table(
        "agent_export_file",
        sa.Column("id", BIGINT, primary_key=True, autoincrement=True),
        sa.Column("file_id", sa.String(40), nullable=False),
        sa.Column("tenant_id", sa.String(32), nullable=False, server_default="dscpa"),
        sa.Column("ticket", sa.String(64), nullable=False),
        sa.Column("oa", sa.String(64), nullable=False),
        sa.Column("thread_id", sa.String(40), nullable=True),
        sa.Column("run_id", sa.String(40), nullable=True),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("content_type", sa.String(128), nullable=False),
        sa.Column("storage", sa.String(16), nullable=False),
        sa.Column("object_key", sa.String(512), nullable=False),
        sa.Column("created_at", DT, nullable=False),
        sa.UniqueConstraint("file_id", name="uk_export_file_id"),
        sa.UniqueConstraint("ticket", name="uk_export_ticket"),
        **MYSQL_OPTS,
    )
    op.create_index("ix_export_created", "agent_export_file", ["tenant_id", "created_at"])
    op.create_index("ix_export_oa_created", "agent_export_file", ["tenant_id", "oa", "created_at"])
    op.create_index("ix_export_thread", "agent_export_file", ["tenant_id", "thread_id"])

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
    op.drop_index("ix_export_thread", table_name="agent_export_file")
    op.drop_index("ix_export_oa_created", table_name="agent_export_file")
    op.drop_index("ix_export_created", table_name="agent_export_file")
    op.drop_table("agent_export_file")
