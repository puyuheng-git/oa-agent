"""员工历史会话容器 agent_chat_thread（可选从对话消息回填）。

Revision ID: 0008_chat_thread
Revises: 0007_conversation_log
Create Date: 2026-10-23
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

revision = "0008_chat_thread"
down_revision = "0007_conversation_log"
branch_labels = None
depends_on = None

BIGINT = sa.BigInteger().with_variant(sa.Integer(), "sqlite")
DT = sa.DateTime().with_variant(mysql.DATETIME(fsp=3), "mysql")
MYSQL_OPTS = {"mysql_charset": "utf8mb4", "mysql_collate": "utf8mb4_unicode_ci", "mysql_engine": "InnoDB"}

TITLE_MAX = 40


def _truncate_title(content: str) -> str:
    text = (content or "").replace("\r", " ").replace("\n", " ").strip()
    if len(text) <= TITLE_MAX:
        return text
    return text[:TITLE_MAX]


def _backfill_from_conversation(conn) -> None:
    inspector = sa.inspect(conn)
    if "agent_conversation_message" not in inspector.get_table_names():
        return

    rows = conn.execute(
        sa.text(
            "SELECT thread_id, tenant_id, oa, channel, role, content, created_at "
            "FROM agent_conversation_message "
            "ORDER BY thread_id, created_at, id"
        )
    ).fetchall()
    if not rows:
        return

    threads: dict[str, dict] = {}
    for row in rows:
        tid = row.thread_id
        if tid not in threads:
            threads[tid] = {
                "thread_id": tid,
                "tenant_id": row.tenant_id,
                "oa": row.oa,
                "created_channel": row.channel or "",
                "last_channel": row.channel or "",
                "title": "",
                "created_at": row.created_at,
                "updated_at": row.created_at,
                "last_message_at": row.created_at,
            }
        else:
            entry = threads[tid]
            entry["last_channel"] = row.channel or ""
            entry["last_message_at"] = row.created_at
            entry["updated_at"] = row.created_at

        if row.role == "user" and not threads[tid]["title"]:
            threads[tid]["title"] = _truncate_title(row.content)

    insert = sa.text(
        "INSERT INTO agent_chat_thread ("
        "thread_id, tenant_id, oa, created_channel, last_channel, title, status, pinned, "
        "metadata_json, created_at, updated_at, last_message_at"
        ") VALUES ("
        ":thread_id, :tenant_id, :oa, :created_channel, :last_channel, :title, 'active', 0, "
        "NULL, :created_at, :updated_at, :last_message_at"
        ")"
    )
    for entry in threads.values():
        conn.execute(insert, entry)


def upgrade() -> None:
    op.create_table(
        "agent_chat_thread",
        sa.Column("id", BIGINT, primary_key=True, autoincrement=True),
        sa.Column("thread_id", sa.String(40), nullable=False),
        sa.Column("tenant_id", sa.String(32), nullable=False, server_default="dscpa"),
        sa.Column("oa", sa.String(64), nullable=False),
        sa.Column("created_channel", sa.String(16), nullable=False, server_default=""),
        sa.Column("last_channel", sa.String(16), nullable=False, server_default=""),
        sa.Column("title", sa.String(200), nullable=False, server_default=""),
        sa.Column("status", sa.String(16), nullable=False, server_default="active"),
        sa.Column("pinned", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("metadata_json", sa.JSON, nullable=True),
        sa.Column("created_at", DT, nullable=False),
        sa.Column("updated_at", DT, nullable=False),
        sa.Column("last_message_at", DT, nullable=True),
        sa.UniqueConstraint("thread_id", name="uk_chat_thread_id"),
        **MYSQL_OPTS,
    )
    op.create_index(
        "ix_chat_thread_oa_status_msg",
        "agent_chat_thread",
        ["tenant_id", "oa", "status", "last_message_at"],
    )

    conn = op.get_bind()
    _backfill_from_conversation(conn)


def downgrade() -> None:
    op.drop_index("ix_chat_thread_oa_status_msg", table_name="agent_chat_thread")
    op.drop_table("agent_chat_thread")
