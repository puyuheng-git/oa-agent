from __future__ import annotations

import re
from pathlib import Path

import sqlalchemy as sa
from sqlalchemy.engine import URL, Engine
from sqlalchemy.orm import Session, sessionmaker

from oa_agent.bootstrap.files import DbParams

DB_NAME_RE = re.compile(r"^[A-Za-z0-9_]{1,64}$")


def build_url(db: DbParams, with_database: bool = True) -> URL:
    if db.driver == "sqlite":
        return URL.create("sqlite+pysqlite", database=db.database)
    return URL.create(
        "mysql+pymysql",
        username=db.user,
        password=db.password,
        host=db.host,
        port=db.port,
        database=db.database if with_database else None,
        query={"charset": "utf8mb4"},
    )


def make_engine(db: DbParams, with_database: bool = True, connect_timeout: int = 5) -> Engine:
    url = build_url(db, with_database)
    if db.driver == "sqlite":
        Path(db.database).parent.mkdir(parents=True, exist_ok=True)
        engine = sa.create_engine(url, connect_args={"check_same_thread": False})

        @sa.event.listens_for(engine, "connect")
        def _fk_on(dbapi_conn, _):
            dbapi_conn.execute("PRAGMA foreign_keys=ON")

        return engine
    return sa.create_engine(
        url,
        pool_pre_ping=True,
        pool_recycle=3600,
        connect_args={"connect_timeout": connect_timeout},
    )


def make_sessionmaker(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(engine, expire_on_commit=False)
