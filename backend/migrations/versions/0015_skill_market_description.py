"""Add marketplace description on agent_skill_market_listing.

Revision ID: 0015_skill_market_description
Revises: 0014_skill_packs
Create Date: 2026-11-13
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0015_skill_market_description"
down_revision = "0014_skill_packs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "agent_skill_market_listing",
        sa.Column("description", sa.String(1024), nullable=False, server_default=""),
    )


def downgrade() -> None:
    op.drop_column("agent_skill_market_listing", "description")
