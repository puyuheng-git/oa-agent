"""Extend agent_export_file for upload registry columns.

Revision ID: 0013_upload_file
Revises: 0012_export_file
Create Date: 2026-11-06
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0013_upload_file"
down_revision = "0012_export_file"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "agent_export_file",
        sa.Column("origin", sa.String(16), nullable=False, server_default="export"),
    )
    op.add_column(
        "agent_export_file",
        sa.Column("sha256", sa.String(64), nullable=True),
    )
    op.add_column(
        "agent_export_file",
        sa.Column("media_kind", sa.String(16), nullable=True),
    )
    op.add_column(
        "agent_export_file",
        sa.Column("in_message", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.create_index(
        "ix_export_origin",
        "agent_export_file",
        ["tenant_id", "origin", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_export_origin", table_name="agent_export_file")
    op.drop_column("agent_export_file", "in_message")
    op.drop_column("agent_export_file", "media_kind")
    op.drop_column("agent_export_file", "sha256")
    op.drop_column("agent_export_file", "origin")
