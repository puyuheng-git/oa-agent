"""AES-GCM 加解密，密钥为 master key（设计 §5.3）。"""

from __future__ import annotations

import base64
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

NONCE_SIZE = 12


class Cipher:
    def __init__(self, master_key: bytes):
        if len(master_key) != 32:
            raise ValueError("master key 必须为 32 字节")
        self._aead = AESGCM(master_key)

    def encrypt(self, plaintext: str, aad: str) -> tuple[bytes, bytes]:
        nonce = os.urandom(NONCE_SIZE)
        return nonce, self._aead.encrypt(nonce, plaintext.encode("utf-8"), aad.encode("utf-8"))

    def decrypt(self, nonce: bytes, ciphertext: bytes, aad: str) -> str:
        return self._aead.decrypt(nonce, ciphertext, aad.encode("utf-8")).decode("utf-8")

    def encrypt_b64(self, plaintext: str, aad: str) -> dict[str, str]:
        nonce, ct = self.encrypt(plaintext, aad)
        return {"nonce": base64.b64encode(nonce).decode(), "ciphertext": base64.b64encode(ct).decode()}

    def decrypt_b64(self, blob: dict[str, str], aad: str) -> str:
        return self.decrypt(base64.b64decode(blob["nonce"]), base64.b64decode(blob["ciphertext"]), aad)


def key_hint(value: str) -> str:
    """后 4 位提示；过短的值不给提示，避免泄露过多。"""
    return value[-4:] if len(value) >= 8 else ""


def mask_display(is_set: bool, hint: str) -> str:
    if not is_set:
        return "未设置"
    return f"已设置 · ****{hint}" if hint else "已设置"
