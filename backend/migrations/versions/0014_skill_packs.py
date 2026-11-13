"""Agent Skill packs (SKILL.md), user library, and tenant marketplace.

Revision ID: 0014_skill_packs
Revises: 0013_upload_file
Create Date: 2026-11-13
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0014_skill_packs"
down_revision = "0013_upload_file"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agent_skill_pack",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("tenant_id", sa.String(32), nullable=False),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("display_name", sa.String(128), nullable=False, server_default=""),
        sa.Column("description", sa.String(1024), nullable=False, server_default=""),
        sa.Column("kind", sa.String(16), nullable=False, server_default="user"),
        sa.Column("source", sa.String(16), nullable=False, server_default="editor"),
        sa.Column("source_url", sa.String(512), nullable=False, server_default=""),
        sa.Column("owner_oa", sa.String(64), nullable=True),
        sa.Column("enabled_default", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("current_version_id", sa.BigInteger(), nullable=True),
        sa.Column("bundle_hash", sa.String(64), nullable=False, server_default=""),
        sa.Column("invoke_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_by", sa.String(64), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "name", name="uk_skill_pack_name"),
    )
    op.create_table(
        "agent_skill_pack_version",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("pack_id", sa.BigInteger(), nullable=False),
        sa.Column("version_no", sa.Integer(), nullable=False),
        sa.Column("skill_md", sa.Text(), nullable=False),
        sa.Column("bundle_meta", sa.JSON(), nullable=True),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("storage_path", sa.String(512), nullable=False, server_default=""),
        sa.Column("created_by", sa.String(64), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("pack_id", "version_no", name="uk_skill_pack_version_no"),
    )
    op.create_table(
        "agent_user_skill",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("tenant_id", sa.String(32), nullable=False),
        sa.Column("oa", sa.String(64), nullable=False),
        sa.Column("pack_id", sa.BigInteger(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("origin", sa.String(16), nullable=False, server_default="created"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "oa", "pack_id", name="uk_user_skill_pack"),
    )
    op.create_index("ix_user_skill_oa", "agent_user_skill", ["tenant_id", "oa"])
    op.create_table(
        "agent_skill_market_listing",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("tenant_id", sa.String(32), nullable=False),
        sa.Column("pack_id", sa.BigInteger(), nullable=False),
        sa.Column("publisher_oa", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="published"),
        sa.Column("invoke_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "pack_id", name="uk_skill_market_pack"),
    )
    op.create_index(
        "ix_skill_market_hot",
        "agent_skill_market_listing",
        ["tenant_id", "status", "invoke_count"],
    )


def downgrade() -> None:
    op.drop_index("ix_skill_market_hot", table_name="agent_skill_market_listing")
    op.drop_table("agent_skill_market_listing")
    op.drop_index("ix_user_skill_oa", table_name="agent_user_skill")
    op.drop_table("agent_user_skill")
    op.drop_table("agent_skill_pack_version")
    op.drop_table("agent_skill_pack")
