from __future__ import annotations

from datetime import UTC, datetime

import sqlalchemy as sa
from sqlalchemy.dialects import mysql
from sqlalchemy.types import TypeDecorator


class UtcDateTime(TypeDecorator):
    """统一 UTC：入库去掉时区（MySQL DATETIME(3)），出库补上 UTC。"""

    impl = sa.DateTime
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "mysql":
            return dialect.type_descriptor(mysql.DATETIME(fsp=3))
        return dialect.type_descriptor(sa.DateTime())

    def process_bind_param(self, value: datetime | None, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("UtcDateTime 需要带时区的 datetime")
        return value.astimezone(UTC).replace(tzinfo=None)

    def process_result_value(self, value: datetime | None, dialect):
        if value is None:
            return None
        return value.replace(tzinfo=UTC)


def utcnow() -> datetime:
    return datetime.now(UTC)


BigIntPK = sa.BigInteger().with_variant(sa.Integer(), "sqlite")
