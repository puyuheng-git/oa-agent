"""LLM 能力/规模、路由池与全局默认。

Revision ID: 0017_llm_model_routing
Revises: 0016_skill_market_review
Create Date: 2026-11-17
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

revision = "0017_llm_model_routing"
down_revision = "0016_skill_market_review"
branch_labels = None
depends_on = None

BIGINT = sa.BigInteger().with_variant(sa.Integer(), "sqlite")
DT = sa.DateTime().with_variant(mysql.DATETIME(fsp=3), "mysql")
MYSQL_OPTS = {"mysql_charset": "utf8mb4", "mysql_collate": "utf8mb4_unicode_ci", "mysql_engine": "InnoDB"}


def upgrade() -> None:
    conn = op.get_bind()
    cols = {c["name"] for c in sa.inspect(conn).get_columns("agent_llm_model")}
    if "capabilities" not in cols:
        op.add_column(
            "agent_llm_model",
            sa.Column("capabilities", sa.JSON(), nullable=True),
        )
    if "model_tier" not in cols:
        op.add_column(
            "agent_llm_model",
            sa.Column("model_tier", sa.String(16), nullable=False, server_default="large"),
        )
    # 回填 capabilities 空值
    conn.execute(sa.text(
        "UPDATE agent_llm_model SET capabilities = :cap WHERE capabilities IS NULL"
    ), {"cap": '["text"]'})

    if "agent_llm_route" not in sa.inspect(conn).get_table_names():
        op.create_table(
            "agent_llm_route",
            sa.Column("id", BIGINT, primary_key=True, autoincrement=True),
            sa.Column("tenant_id", sa.String(32), nullable=False, server_default="dscpa"),
            sa.Column("capability", sa.String(32), nullable=False),
            sa.Column("model_tier", sa.String(16), nullable=False),
            sa.Column("model_ids", sa.JSON, nullable=True),
            sa.Column("enabled", sa.Boolean, nullable=False, server_default=sa.true()),
            sa.Column("updated_by", sa.String(64), nullable=False, server_default=""),
            sa.Column("created_at", DT, nullable=False),
            sa.Column("updated_at", DT, nullable=False),
            sa.UniqueConstraint("tenant_id", "capability", "model_tier", name="uk_llm_route_cap_tier"),
            **MYSQL_OPTS,
        )

    if "agent_llm_defaults" not in sa.inspect(conn).get_table_names():
        op.create_table(
            "agent_llm_defaults",
            sa.Column("id", BIGINT, primary_key=True, autoincrement=True),
            sa.Column("tenant_id", sa.String(32), nullable=False, server_default="dscpa"),
            sa.Column("global_default_model_id", BIGINT, nullable=True),
            sa.Column("max_failover", sa.Integer, nullable=False, server_default="3"),
            sa.Column("updated_by", sa.String(64), nullable=False, server_default=""),
            sa.Column("updated_at", DT, nullable=False),
            sa.UniqueConstraint("tenant_id", name="uk_llm_defaults_tenant"),
            **MYSQL_OPTS,
        )

    # 每租户：无 defaults 行则插入；global 为空则种子第一个启用模型
    tenants = [r[0] for r in conn.execute(sa.text(
        "SELECT DISTINCT tenant_id FROM agent_llm_model"
    )).fetchall()]
    if not tenants:
        tenants = ["dscpa"]
    for tid in tenants:
        row = conn.execute(sa.text(
            "SELECT id, global_default_model_id FROM agent_llm_defaults WHERE tenant_id = :t"
        ), {"t": tid}).first()
        # 优先带 intent 标签的启用模型（保持升级前行为），否则取 ID 最小的启用模型
        mid = conn.execute(sa.text(
            "SELECT id FROM agent_llm_model WHERE tenant_id = :t AND enabled = 1 "
            "AND purpose_tags LIKE '%\"intent\"%' ORDER BY id LIMIT 1"
        ), {"t": tid}).scalar()
        if mid is None:
            mid = conn.execute(sa.text(
                "SELECT id FROM agent_llm_model WHERE tenant_id = :t AND enabled = 1 "
                "ORDER BY id LIMIT 1"
            ), {"t": tid}).scalar()
        if row is None:
            conn.execute(sa.text(
                "INSERT INTO agent_llm_defaults "
                "(tenant_id, global_default_model_id, max_failover, updated_by, updated_at) "
                "VALUES (:t, :m, 3, 'migration', CURRENT_TIMESTAMP)"
            ), {"t": tid, "m": mid})
        elif row[1] is None and mid is not None:
            conn.execute(sa.text(
                "UPDATE agent_llm_defaults SET global_default_model_id = :m "
                "WHERE tenant_id = :t AND global_default_model_id IS NULL"
            ), {"t": tid, "m": mid})


def downgrade() -> None:
    op.drop_table("agent_llm_defaults")
    op.drop_table("agent_llm_route")
    conn = op.get_bind()
    cols = {c["name"] for c in sa.inspect(conn).get_columns("agent_llm_model")}
    if "model_tier" in cols:
        op.drop_column("agent_llm_model", "model_tier")
    if "capabilities" in cols:
        op.drop_column("agent_llm_model", "capabilities")
