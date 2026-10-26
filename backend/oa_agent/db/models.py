"""agent_ops P0 表（设计 §8）。表结构变更须同步新建 Alembic 迁移。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from oa_agent.db.types import BigIntPK, UtcDateTime, utcnow

DEFAULT_TENANT = "dscpa"


class Base(DeclarativeBase):
    pass


class AdminUser(Base):
    __tablename__ = "agent_admin_user"
    __table_args__ = (sa.UniqueConstraint("tenant_id", "username", name="uk_admin_user_username"),)

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(sa.String(32), default=DEFAULT_TENANT)
    username: Mapped[str] = mapped_column(sa.String(64))
    display_name: Mapped[str] = mapped_column(sa.String(64), default="")
    password_hash: Mapped[str] = mapped_column(sa.String(255))
    status: Mapped[str] = mapped_column(sa.String(16), default="active")
    failed_count: Mapped[int] = mapped_column(sa.Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    last_login_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    password_changed_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow, onupdate=utcnow)


class AdminRole(Base):
    __tablename__ = "agent_admin_role"
    __table_args__ = (sa.UniqueConstraint("tenant_id", "code", name="uk_admin_role_code"),)

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(sa.String(32), default=DEFAULT_TENANT)
    code: Mapped[str] = mapped_column(sa.String(64))
    name: Mapped[str] = mapped_column(sa.String(64))
    description: Mapped[str] = mapped_column(sa.String(255), default="")
    is_builtin: Mapped[bool] = mapped_column(sa.Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow, onupdate=utcnow)


class AdminRolePerm(Base):
    __tablename__ = "agent_admin_role_perm"

    role_id: Mapped[int] = mapped_column(
        BigIntPK, sa.ForeignKey("agent_admin_role.id", ondelete="CASCADE"), primary_key=True
    )
    perm_code: Mapped[str] = mapped_column(sa.String(64), primary_key=True)


class AdminUserRole(Base):
    __tablename__ = "agent_admin_user_role"

    user_id: Mapped[int] = mapped_column(
        BigIntPK, sa.ForeignKey("agent_admin_user.id", ondelete="CASCADE"), primary_key=True
    )
    role_id: Mapped[int] = mapped_column(
        BigIntPK, sa.ForeignKey("agent_admin_role.id", ondelete="CASCADE"), primary_key=True
    )


class Setting(Base):
    __tablename__ = "agent_setting"
    __table_args__ = (
        sa.UniqueConstraint("tenant_id", "setting_group", "setting_key", name="uk_setting_group_key"),
    )

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(sa.String(32), default=DEFAULT_TENANT)
    setting_group: Mapped[str] = mapped_column(sa.String(32))
    setting_key: Mapped[str] = mapped_column(sa.String(64))
    value_json: Mapped[Any] = mapped_column(sa.JSON, nullable=True)
    version: Mapped[int] = mapped_column(sa.Integer, default=1)
    updated_by: Mapped[str] = mapped_column(sa.String(64), default="")
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow, onupdate=utcnow)


class Secret(Base):
    __tablename__ = "agent_secret"
    __table_args__ = (sa.UniqueConstraint("tenant_id", "name", name="uk_secret_name"),)

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(sa.String(32), default=DEFAULT_TENANT)
    name: Mapped[str] = mapped_column(sa.String(128))
    ciphertext: Mapped[bytes] = mapped_column(sa.LargeBinary)
    nonce: Mapped[bytes] = mapped_column(sa.LargeBinary(16))
    key_hint: Mapped[str] = mapped_column(sa.String(8), default="")
    version: Mapped[int] = mapped_column(sa.Integer, default=1)
    updated_by: Mapped[str] = mapped_column(sa.String(64), default="")
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow, onupdate=utcnow)


class LlmProvider(Base):
    __tablename__ = "agent_llm_provider"
    __table_args__ = (sa.UniqueConstraint("tenant_id", "name", name="uk_llm_provider_name"),)

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(sa.String(32), default=DEFAULT_TENANT)
    name: Mapped[str] = mapped_column(sa.String(64))
    provider_type: Mapped[str] = mapped_column(sa.String(32), default="openai_compatible")
    base_url: Mapped[str] = mapped_column(sa.String(255))
    secret_ref: Mapped[str | None] = mapped_column(sa.String(128), nullable=True)
    timeout_seconds: Mapped[int] = mapped_column(sa.Integer, default=60)
    enabled: Mapped[bool] = mapped_column(sa.Boolean, default=True)
    updated_by: Mapped[str] = mapped_column(sa.String(64), default="")
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow, onupdate=utcnow)


class LlmModel(Base):
    __tablename__ = "agent_llm_model"
    __table_args__ = (sa.UniqueConstraint("provider_id", "model_name", name="uk_llm_model_provider_name"),)

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(sa.String(32), default=DEFAULT_TENANT)
    provider_id: Mapped[int] = mapped_column(BigIntPK, sa.ForeignKey("agent_llm_provider.id"))
    model_name: Mapped[str] = mapped_column(sa.String(128))
    display_name: Mapped[str] = mapped_column(sa.String(128), default="")
    params_json: Mapped[dict] = mapped_column(sa.JSON, default=dict)
    purpose_tags: Mapped[list] = mapped_column(sa.JSON, default=list)
    enabled: Mapped[bool] = mapped_column(sa.Boolean, default=True)
    updated_by: Mapped[str] = mapped_column(sa.String(64), default="")
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow, onupdate=utcnow)


class Run(Base):
    """每次用户消息一次运行（设计 §8 / §10）。状态只经 RunService.transition 修改。"""

    __tablename__ = "agent_run"
    __table_args__ = (
        sa.UniqueConstraint("run_id", name="uk_run_id"),
        sa.Index("ix_run_started", "tenant_id", "started_at"),
        sa.Index("ix_run_status", "tenant_id", "run_status"),
        sa.Index("ix_run_thread", "thread_id"),
        sa.Index("ix_run_oa", "tenant_id", "oa"),
        sa.Index("ix_run_error", "tenant_id", "error_code", "started_at"),
    )

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(sa.String(40))
    thread_id: Mapped[str] = mapped_column(sa.String(40))
    tenant_id: Mapped[str] = mapped_column(sa.String(32), default=DEFAULT_TENANT)
    oa: Mapped[str] = mapped_column(sa.String(64))
    channel: Mapped[str] = mapped_column(sa.String(16))
    agent_id: Mapped[str] = mapped_column(sa.String(64))
    workflow_id: Mapped[str] = mapped_column(sa.String(64))
    workflow_version: Mapped[str] = mapped_column(sa.String(32))
    config_release_id: Mapped[str | None] = mapped_column(sa.String(40), nullable=True)
    run_status: Mapped[str] = mapped_column(sa.String(24))
    started_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)
    ended_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    last_event_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    error_code: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)
    error_summary: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    failed_node: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)
    parent_run_id: Mapped[str | None] = mapped_column(sa.String(40), nullable=True)
    tool_call_count: Mapped[int] = mapped_column(sa.Integer, default=0)
    model_call_count: Mapped[int] = mapped_column(sa.Integer, default=0)
    usage_json: Mapped[Any] = mapped_column(sa.JSON, nullable=True)
    business_type: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)
    business_record_id: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)
    business_status_snapshot: Mapped[str | None] = mapped_column(sa.String(255), nullable=True)


class RunEvent(Base):
    __tablename__ = "agent_run_event"
    __table_args__ = (
        sa.UniqueConstraint("event_id", name="uk_run_event_id"),
        sa.UniqueConstraint("run_id", "seq", name="uk_run_event_seq"),
        sa.Index("ix_run_event_type", "event_type", "occurred_at"),
    )

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    event_id: Mapped[str] = mapped_column(sa.String(40))
    run_id: Mapped[str] = mapped_column(sa.String(40))
    seq: Mapped[int] = mapped_column(sa.Integer)
    event_type: Mapped[str] = mapped_column(sa.String(32))
    node_name: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)
    status: Mapped[str | None] = mapped_column(sa.String(16), nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)
    duration_ms: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    tool_name: Mapped[str | None] = mapped_column(sa.String(128), nullable=True)
    tool_version: Mapped[str | None] = mapped_column(sa.String(32), nullable=True)
    correlation_id: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)
    error_code: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)
    error_summary: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    input_summary: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    output_summary: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    retry_count: Mapped[int] = mapped_column(sa.Integer, default=0)
    operator_id: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)
    metadata_json: Mapped[Any] = mapped_column(sa.JSON, nullable=True)


LongText = sa.Text().with_variant(mysql.LONGTEXT(), "mysql")


class ConversationMessage(Base):
    """完整对话记录（员工原话与系统回复原文），不随事件保留期清理，供查看与训练导出。"""

    __tablename__ = "agent_conversation_message"
    __table_args__ = (
        sa.UniqueConstraint("message_id", name="uk_conversation_message_id"),
        sa.Index("ix_conversation_thread", "tenant_id", "thread_id", "id"),
        sa.Index("ix_conversation_time", "tenant_id", "created_at"),
        sa.Index("ix_conversation_run", "run_id"),
    )

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    message_id: Mapped[str] = mapped_column(sa.String(40))
    tenant_id: Mapped[str] = mapped_column(sa.String(32), default=DEFAULT_TENANT)
    thread_id: Mapped[str] = mapped_column(sa.String(40))
    run_id: Mapped[str] = mapped_column(sa.String(40))
    oa: Mapped[str] = mapped_column(sa.String(64))
    channel: Mapped[str] = mapped_column(sa.String(16), default="")
    role: Mapped[str] = mapped_column(sa.String(16))  # user / assistant
    content: Mapped[str] = mapped_column(LongText)
    reply_type: Mapped[str | None] = mapped_column(sa.String(16), nullable=True)
    data_json: Mapped[Any] = mapped_column(sa.JSON, nullable=True)
    error_code: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)


class ChatThread(Base):
    """员工可见的会话容器（历史列表与续聊）。"""

    __tablename__ = "agent_chat_thread"
    __table_args__ = (
        sa.UniqueConstraint("thread_id", name="uk_chat_thread_id"),
        sa.Index("ix_chat_thread_oa_status_msg", "tenant_id", "oa", "status", "last_message_at"),
    )

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    thread_id: Mapped[str] = mapped_column(sa.String(40))
    tenant_id: Mapped[str] = mapped_column(sa.String(32), default=DEFAULT_TENANT)
    oa: Mapped[str] = mapped_column(sa.String(64))
    created_channel: Mapped[str] = mapped_column(sa.String(16), default="")
    last_channel: Mapped[str] = mapped_column(sa.String(16), default="")
    title: Mapped[str] = mapped_column(sa.String(200), default="")
    status: Mapped[str] = mapped_column(sa.String(16), default="active")  # active|archived|deleted
    pinned: Mapped[bool] = mapped_column(sa.Boolean, default=False)
    metadata_json: Mapped[Any] = mapped_column(sa.JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)
    last_message_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)


class EmployeeMemory(Base):
    """员工跨会话长期记忆（preference / constraint / note）。"""

    __tablename__ = "agent_employee_memory"
    __table_args__ = (
        sa.UniqueConstraint("memory_id", name="uk_employee_memory_id"),
        sa.Index("ix_employee_memory_oa_status_upd", "tenant_id", "oa", "status", "updated_at"),
    )

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    memory_id: Mapped[str] = mapped_column(sa.String(40))
    tenant_id: Mapped[str] = mapped_column(sa.String(32), default=DEFAULT_TENANT)
    oa: Mapped[str] = mapped_column(sa.String(64))
    kind: Mapped[str] = mapped_column(sa.String(32))  # preference|constraint|note
    text: Mapped[str] = mapped_column(sa.String(200))
    status: Mapped[str] = mapped_column(sa.String(16), default="active")  # active|deleted
    source_thread_id: Mapped[str | None] = mapped_column(sa.String(40), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow, onupdate=utcnow)


class ModelCallLog(Base):
    """每次模型调用的完整请求消息与最终输出（不含推理链）。"""

    __tablename__ = "agent_model_call_log"
    __table_args__ = (
        sa.UniqueConstraint("call_id", name="uk_model_call_id"),
        sa.Index("ix_model_call_run", "run_id"),
        sa.Index("ix_model_call_time", "tenant_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    call_id: Mapped[str] = mapped_column(sa.String(40))
    tenant_id: Mapped[str] = mapped_column(sa.String(32), default=DEFAULT_TENANT)
    run_id: Mapped[str] = mapped_column(sa.String(40))
    thread_id: Mapped[str] = mapped_column(sa.String(40))
    oa: Mapped[str] = mapped_column(sa.String(64))
    node_name: Mapped[str] = mapped_column(sa.String(64), default="")
    provider: Mapped[str] = mapped_column(sa.String(64), default="")
    model: Mapped[str] = mapped_column(sa.String(128), default="")
    messages_json: Mapped[Any] = mapped_column(sa.JSON)
    output_text: Mapped[str | None] = mapped_column(LongText, nullable=True)
    parsed_json: Mapped[Any] = mapped_column(sa.JSON, nullable=True)
    usage_json: Mapped[Any] = mapped_column(sa.JSON, nullable=True)
    status: Mapped[str] = mapped_column(sa.String(16))
    error_summary: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)


class AuditLog(Base):
    """仅追加。应用账号对此表只授予 INSERT/SELECT。"""

    __tablename__ = "agent_audit_log"
    __table_args__ = (
        sa.UniqueConstraint("audit_id", name="uk_audit_id"),
        sa.Index("ix_audit_occurred", "tenant_id", "occurred_at"),
        sa.Index("ix_audit_actor", "actor_type", "actor_id"),
        sa.Index("ix_audit_resource", "resource_type", "resource_id"),
    )

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    audit_id: Mapped[str] = mapped_column(sa.String(40))
    actor_type: Mapped[str] = mapped_column(sa.String(16))
    actor_id: Mapped[str] = mapped_column(sa.String(64))
    tenant_id: Mapped[str] = mapped_column(sa.String(32), default=DEFAULT_TENANT)
    action: Mapped[str] = mapped_column(sa.String(64))
    resource_type: Mapped[str] = mapped_column(sa.String(32), default="")
    resource_id: Mapped[str] = mapped_column(sa.String(128), default="")
    before_summary: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    after_summary: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    result: Mapped[str] = mapped_column(sa.String(16))
    reason: Mapped[str] = mapped_column(sa.String(255), default="")
    occurred_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)
    request_id: Mapped[str] = mapped_column(sa.String(64), default="")
    source_ip: Mapped[str] = mapped_column(sa.String(64), default="")
    correlation_id: Mapped[str] = mapped_column(sa.String(64), default="")


# ---------------- P3 人工介入 ----------------

class InterventionTask(Base):
    """人工介入任务。kind=admin 由管理员处理；kind=user_confirm 只能由员工本人凭确认令牌处理。"""

    __tablename__ = "agent_intervention_task"
    __table_args__ = (
        sa.UniqueConstraint("task_id", name="uk_intervention_task_id"),
        sa.Index("ix_intervention_status", "tenant_id", "status", "created_at"),
        sa.Index("ix_intervention_run", "run_id"),
    )

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    task_id: Mapped[str] = mapped_column(sa.String(40))
    tenant_id: Mapped[str] = mapped_column(sa.String(32), default=DEFAULT_TENANT)
    run_id: Mapped[str] = mapped_column(sa.String(40))
    kind: Mapped[str] = mapped_column(sa.String(16))
    status: Mapped[str] = mapped_column(sa.String(16), default="pending")
    reason: Mapped[str] = mapped_column(sa.String(255), default="")
    node_name: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)
    error_code: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)
    confirm_token_hash: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)
    binding_snapshot_json: Mapped[Any] = mapped_column(sa.JSON, nullable=True)
    expire_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)
    handled_by: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)
    handled_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    result: Mapped[str | None] = mapped_column(sa.String(32), nullable=True)
    handle_note: Mapped[str | None] = mapped_column(sa.String(255), nullable=True)
    version: Mapped[int] = mapped_column(sa.Integer, default=1)


# ---------------- P4 Tool / Skill ----------------

class Tool(Base):
    __tablename__ = "agent_tool"
    __table_args__ = (sa.UniqueConstraint("tenant_id", "name", name="uk_tool_name"),)

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(sa.String(32), default=DEFAULT_TENANT)
    name: Mapped[str] = mapped_column(sa.String(128))
    source_file: Mapped[str] = mapped_column(sa.String(255), default="")
    summary: Mapped[str] = mapped_column(sa.String(255), default="")
    enabled: Mapped[bool] = mapped_column(sa.Boolean, default=True)
    spec_enabled: Mapped[bool] = mapped_column(sa.Boolean, default=False)
    risk_level: Mapped[str] = mapped_column(sa.String(16), default="low")
    requires_confirmation: Mapped[bool] = mapped_column(sa.Boolean, default=False)
    current_version_id: Mapped[int | None] = mapped_column(sa.BigInteger, nullable=True)
    pending_version_id: Mapped[int | None] = mapped_column(sa.BigInteger, nullable=True)
    last_sync_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    last_sync_result: Mapped[str | None] = mapped_column(sa.String(16), nullable=True)
    last_sync_error: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    updated_by: Mapped[str] = mapped_column(sa.String(64), default="")
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow, onupdate=utcnow)


class ToolVersion(Base):
    __tablename__ = "agent_tool_version"
    __table_args__ = (sa.UniqueConstraint("tool_id", "version_no", name="uk_tool_version_no"),)

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    tool_id: Mapped[int] = mapped_column(sa.BigInteger)
    version_no: Mapped[int] = mapped_column(sa.Integer)
    spec_version: Mapped[str] = mapped_column(sa.String(32), default="")
    schema_json: Mapped[Any] = mapped_column(sa.JSON)
    schema_hash: Mapped[str] = mapped_column(sa.String(64))
    compat_level: Mapped[str] = mapped_column(sa.String(16))
    diff_json: Mapped[Any] = mapped_column(sa.JSON, nullable=True)
    created_by: Mapped[str] = mapped_column(sa.String(64), default="")
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)


class Skill(Base):
    __tablename__ = "agent_skill"
    __table_args__ = (sa.UniqueConstraint("tenant_id", "name", name="uk_skill_name"),)

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(sa.String(32), default=DEFAULT_TENANT)
    name: Mapped[str] = mapped_column(sa.String(128))
    display_name: Mapped[str] = mapped_column(sa.String(128), default="")
    source_file: Mapped[str] = mapped_column(sa.String(255), default="")
    enabled: Mapped[bool] = mapped_column(sa.Boolean, default=True)
    current_version_id: Mapped[int | None] = mapped_column(sa.BigInteger, nullable=True)
    validation_status: Mapped[str] = mapped_column(sa.String(16), default="unknown")
    validation_errors: Mapped[Any] = mapped_column(sa.JSON, nullable=True)
    last_sync_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    last_sync_result: Mapped[str | None] = mapped_column(sa.String(16), nullable=True)
    last_sync_error: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    updated_by: Mapped[str] = mapped_column(sa.String(64), default="")
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow, onupdate=utcnow)


class SkillVersion(Base):
    __tablename__ = "agent_skill_version"
    __table_args__ = (sa.UniqueConstraint("skill_id", "version_no", name="uk_skill_version_no"),)

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    skill_id: Mapped[int] = mapped_column(sa.BigInteger)
    version_no: Mapped[int] = mapped_column(sa.Integer)
    spec_version: Mapped[str] = mapped_column(sa.String(32), default="")
    content_json: Mapped[Any] = mapped_column(sa.JSON)
    content_hash: Mapped[str] = mapped_column(sa.String(64))
    created_by: Mapped[str] = mapped_column(sa.String(64), default="")
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)


class SkillVisibilityRule(Base):
    __tablename__ = "agent_skill_visibility_rule"
    __table_args__ = (
        sa.Index("ix_skill_vis_tenant_skill", "tenant_id", "skill_id"),
        sa.UniqueConstraint(
            "tenant_id",
            "skill_id",
            "effect",
            "principal_type",
            "principal_value",
            name="uk_skill_vis_rule",
        ),
    )

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(sa.String(32), default=DEFAULT_TENANT)
    skill_id: Mapped[int] = mapped_column(sa.BigInteger)
    effect: Mapped[str] = mapped_column(sa.String(8))  # allow|deny
    principal_type: Mapped[str] = mapped_column(sa.String(16))  # all|oa|tag
    principal_value: Mapped[str] = mapped_column(sa.String(128), default="")
    created_by: Mapped[str] = mapped_column(sa.String(64), default="")
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow, onupdate=utcnow)


# ---------------- P5 配置版本 ----------------

class AgentDefinition(Base):
    __tablename__ = "agent_definition"
    __table_args__ = (sa.UniqueConstraint("tenant_id", "agent_id", name="uk_agent_definition"),)

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(sa.String(32), default=DEFAULT_TENANT)
    agent_id: Mapped[str] = mapped_column(sa.String(64))
    name: Mapped[str] = mapped_column(sa.String(128), default="")
    workflow_id: Mapped[str] = mapped_column(sa.String(64))
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)


class WorkflowVersion(Base):
    """status：draft（可改）→ validated → published（不可改）。"""

    __tablename__ = "agent_workflow_version"
    __table_args__ = (
        sa.UniqueConstraint("version_id", name="uk_workflow_version_id"),
        sa.Index("ix_workflow_version", "tenant_id", "workflow_id", "status"),
    )

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    version_id: Mapped[str] = mapped_column(sa.String(40))
    tenant_id: Mapped[str] = mapped_column(sa.String(32), default=DEFAULT_TENANT)
    workflow_id: Mapped[str] = mapped_column(sa.String(64))
    version_no: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    content_json: Mapped[Any] = mapped_column(sa.JSON)
    content_hash: Mapped[str] = mapped_column(sa.String(64))
    status: Mapped[str] = mapped_column(sa.String(16))
    validation_json: Mapped[Any] = mapped_column(sa.JSON, nullable=True)
    validated_hash: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)
    created_by: Mapped[str] = mapped_column(sa.String(64), default="")
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)
    updated_by: Mapped[str] = mapped_column(sa.String(64), default="")
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow, onupdate=utcnow)
    published_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)


class ConfigRelease(Base):
    __tablename__ = "agent_config_release"
    __table_args__ = (
        sa.UniqueConstraint("release_id", name="uk_config_release_id"),
        sa.Index("ix_config_release", "tenant_id", "workflow_id", "id"),
    )

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    release_id: Mapped[str] = mapped_column(sa.String(40))
    tenant_id: Mapped[str] = mapped_column(sa.String(32), default=DEFAULT_TENANT)
    workflow_id: Mapped[str] = mapped_column(sa.String(64))
    workflow_version_id: Mapped[str] = mapped_column(sa.String(40))
    version_no: Mapped[int] = mapped_column(sa.Integer)
    release_type: Mapped[str] = mapped_column(sa.String(16))
    reason: Mapped[str] = mapped_column(sa.String(255), default="")
    previous_release_id: Mapped[str | None] = mapped_column(sa.String(40), nullable=True)
    released_by: Mapped[str] = mapped_column(sa.String(64), default="")
    released_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)
