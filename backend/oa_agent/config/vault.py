"""密钥保险箱：agent_secret 表，AES-GCM 加密；对外只暴露掩码。"""

from __future__ import annotations

from dataclasses import dataclass

import sqlalchemy as sa
from sqlalchemy.orm import Session

from oa_agent.config.crypto import Cipher, key_hint, mask_display
from oa_agent.db.models import Secret


@dataclass
class SecretView:
    is_set: bool
    hint: str

    @property
    def display(self) -> str:
        return mask_display(self.is_set, self.hint)

    def as_dict(self) -> dict:
        return {"is_set": self.is_set, "display": self.display}


class SecretVault:
    def __init__(self, cipher: Cipher, tenant_id: str):
        self._cipher = cipher
        self._tenant = tenant_id

    def _aad(self, name: str) -> str:
        return f"{self._tenant}:{name}"

    def _row(self, db: Session, name: str) -> Secret | None:
        return db.scalar(sa.select(Secret).where(Secret.tenant_id == self._tenant, Secret.name == name))

    def set(self, db: Session, name: str, value: str, actor: str) -> SecretView:
        nonce, ct = self._cipher.encrypt(value, self._aad(name))
        row = self._row(db, name)
        hint = key_hint(value)
        if row is None:
            row = Secret(tenant_id=self._tenant, name=name, ciphertext=ct, nonce=nonce, key_hint=hint, updated_by=actor)
            db.add(row)
        else:
            row.ciphertext, row.nonce, row.key_hint = ct, nonce, hint
            row.version += 1
            row.updated_by = actor
        db.flush()
        return SecretView(True, hint)

    def delete(self, db: Session, name: str) -> bool:
        row = self._row(db, name)
        if row is None:
            return False
        db.delete(row)
        db.flush()
        return True

    def describe(self, db: Session, name: str | None) -> SecretView:
        row = self._row(db, name) if name else None
        return SecretView(row is not None, row.key_hint if row else "")

    def reveal(self, db: Session, name: str | None) -> str | None:
        """仅供服务端内部使用（连接外部系统），绝不经 API 返回。"""
        row = self._row(db, name) if name else None
        if row is None:
            return None
        return self._cipher.decrypt(row.nonce, row.ciphertext, self._aad(name))
