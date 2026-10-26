"""Alembic 环境。

- 编程调用：通过 config.attributes["connection"] 传入连接（安装向导 / 测试）。
- 命令行：`uv run alembic upgrade head`，从 data/bootstrap.json + master key 解析连接。
"""

from __future__ import annotations

from alembic import context

from oa_agent.db.models import Base

target_metadata = Base.metadata


def _engine_from_bootstrap():
    from oa_agent.bootstrap.files import load_or_create_master_key, read_bootstrap
    from oa_agent.config.crypto import Cipher
    from oa_agent.db.engine import make_engine
    from oa_agent.settings import AppSettings

    settings = AppSettings()
    if not settings.bootstrap_path.exists():
        raise SystemExit("系统未安装：缺少 data/bootstrap.json，请先完成安装向导")
    cipher = Cipher(load_or_create_master_key(settings))
    return make_engine(read_bootstrap(settings, cipher).database)


def run_migrations_online() -> None:
    connection = context.config.attributes.get("connection")
    if connection is not None:
        context.configure(connection=connection, target_metadata=target_metadata, render_as_batch=True)
        with context.begin_transaction():
            context.run_migrations()
        return

    engine = _engine_from_bootstrap()
    with engine.connect() as conn:
        context.configure(connection=conn, target_metadata=target_metadata, render_as_batch=True)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    raise SystemExit("不支持 offline 模式")
run_migrations_online()
