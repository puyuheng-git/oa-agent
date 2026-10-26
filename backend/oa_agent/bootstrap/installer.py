"""安装向导的数据库与初始化步骤（设计 §5.1）。"""

from __future__ import annotations

import time

import sqlalchemy as sa
from sqlalchemy.orm import Session

from oa_agent.auth.passwords import check_strength, hash_password
from oa_agent.auth.perms import SUPER_ADMIN_ROLE
from oa_agent.bootstrap.files import DbParams
from oa_agent.db.engine import DB_NAME_RE, make_engine, make_sessionmaker
from oa_agent.db.migrate import upgrade_head
from oa_agent.db.models import AdminRole, AdminUser, AdminUserRole
from oa_agent.errors import AppError
from oa_agent.observability.audit import AuditMeta, AuditService
from oa_agent.observability.redact import redact


def validate_params(db: DbParams, allow_sqlite: bool) -> None:
    if db.driver == "sqlite":
        if not allow_sqlite:
            raise AppError(422, "VALIDATION_ERROR", "仅支持 MySQL")
        return
    if db.driver != "mysql":
        raise AppError(422, "VALIDATION_ERROR", "仅支持 MySQL")
    if not DB_NAME_RE.match(db.database):
        raise AppError(422, "VALIDATION_ERROR", "数据库名只能包含字母、数字、下划线")


def check_db(db: DbParams) -> dict:
    """连接服务器（不指定库），报告版本与目标库是否存在。"""
    started = time.perf_counter()
    try:
        if db.driver == "sqlite":
            engine = make_engine(db)
            with engine.connect() as conn:
                version = conn.execute(sa.text("select sqlite_version()")).scalar()
            engine.dispose()
            return {"ok": True, "server_version": f"sqlite {version}", "database_exists": True,
                    "latency_ms": int((time.perf_counter() - started) * 1000)}
        engine = make_engine(db, with_database=False)
        with engine.connect() as conn:
            version = conn.execute(sa.text("select version()")).scalar()
            exists = conn.execute(
                sa.text("select 1 from information_schema.schemata where schema_name = :n"), {"n": db.database}
            ).first() is not None
        engine.dispose()
        return {"ok": True, "server_version": version, "database_exists": exists,
                "latency_ms": int((time.perf_counter() - started) * 1000)}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": redact(f"{type(exc).__name__}: {exc}")}


def ensure_database(db: DbParams) -> None:
    if db.driver == "sqlite":
        return
    engine = make_engine(db, with_database=False)
    try:
        with engine.begin() as conn:
            exists = conn.execute(
                sa.text("select 1 from information_schema.schemata where schema_name = :n"), {"n": db.database}
            ).first()
            if not exists:
                conn.execute(
                    sa.text(f"CREATE DATABASE `{db.database}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")
                )
    finally:
        engine.dispose()


def create_super_admin(session: Session, tenant_id: str, username: str, display_name: str, password: str,
                       meta: AuditMeta) -> int:
    check_strength(password, username)
    if session.scalar(sa.select(AdminUser.id).where(AdminUser.tenant_id == tenant_id, AdminUser.username == username)):
        raise AppError(409, "USERNAME_EXISTS", "该用户名已存在于目标数据库")
    role_id = session.scalar(
        sa.select(AdminRole.id).where(AdminRole.tenant_id == tenant_id, AdminRole.code == SUPER_ADMIN_ROLE)
    )
    user = AdminUser(tenant_id=tenant_id, username=username, display_name=display_name or username,
                     password_hash=hash_password(password))
    session.add(user)
    session.flush()
    session.add(AdminUserRole(user_id=user.id, role_id=role_id))
    AuditService(tenant_id).record(
        session, actor_type="system", actor_id="installer", action="system.install",
        resource_type="admin_user", resource_id=str(user.id), after=f"创建超级管理员 {username}", meta=meta,
    )
    return user.id


def install(db: DbParams, tenant_id: str, username: str, display_name: str, password: str, meta: AuditMeta) -> None:
    check_strength(password, username)
    ensure_database(db)
    engine = make_engine(db)
    try:
        upgrade_head(engine)
        with make_sessionmaker(engine)() as session, session.begin():
            create_super_admin(session, tenant_id, username, display_name, password, meta)
    finally:
        engine.dispose()
