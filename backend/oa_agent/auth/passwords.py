from __future__ import annotations

import re

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from oa_agent.errors import AppError

_hasher = PasswordHasher()  # argon2id

MIN_LENGTH = 12


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


_DUMMY_HASH = _hasher.hash("timing-equalizer-not-a-password")


def burn_verify(password: str) -> None:
    """用户不存在时也做一次哈希校验，避免以响应时间探测用户名。"""
    verify_password(_DUMMY_HASH, password)


def check_strength(password: str, username: str = "", min_length: int = MIN_LENGTH) -> None:
    """min_length 来自配置中心「后台安全」组，不会低于 MIN_LENGTH（安全底线）。"""
    min_length = max(MIN_LENGTH, int(min_length))
    classes = sum(
        bool(re.search(p, password)) for p in (r"[a-z]", r"[A-Z]", r"\d", r"[^A-Za-z0-9]")
    )
    if len(password) < min_length or classes < 3:
        raise AppError(422, "WEAK_PASSWORD", f"密码至少 {min_length} 位，且包含大写、小写、数字、符号中的至少 3 类")
    if username and username.lower() in password.lower():
        raise AppError(422, "WEAK_PASSWORD", "密码不能包含用户名")
