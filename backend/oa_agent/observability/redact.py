"""统一脱敏（设计 §11）。

- `redact`：日志、审计、异常信息使用；去掉密钥类和个人信息（身份证、银行卡、手机号、发票号）。
- `redact_secrets`：运行事件与对话记录使用；只去密钥类（token/Authorization/API Key/口令），
  业务与个人信息按原样保留，供后台查看完整对话与训练（硬约束 5：任何地方都不得出现明文密钥）。
"""

from __future__ import annotations

import re

MAX_SUMMARY = 2048

_SECRET_RULES: list[tuple[re.Pattern[str], str]] = [
    # scheme://user:password@host —— 连接串中的口令
    (re.compile(r"(?P<p>[a-zA-Z][a-zA-Z0-9+.-]*://[^:/@\s]*:)[^@\s]+(?=@)"), r"\g<p>***"),
    (re.compile(r"(?i)(authorization\s*[:=]\s*)(bearer\s+)?[^\s,;\"']+"), r"\1\2***"),
    (re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{8,}"), "Bearer ***"),
    (
        re.compile(r"(?i)((?:api[_-]?key|token|secret|password|passwd|pwd)[\"']?\s*[:=]\s*[\"']?)[^\s,;\"'&}]+"),
        r"\1***",
    ),
    (re.compile(r"\bsk-[A-Za-z0-9_-]{8,}"), "sk-***"),
]

_PII_RULES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"(?<!\d)\d{17}[\dXx](?!\d)"), "[身份证]"),
    (re.compile(r"(?<!\d)\d{16,19}(?!\d)"), "[银行卡]"),
    (re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)"), "[手机号]"),
    (re.compile(r"(?i)(发票号(?:码)?\s*[:：]?\s*)\w+"), r"\1***"),
]


_RULES = _SECRET_RULES + _PII_RULES


def _apply(text: str | None, rules: list[tuple[re.Pattern[str], str]], limit: int | None) -> str:
    if not text:
        return ""
    out = str(text)
    for pattern, repl in rules:
        out = pattern.sub(repl, out)
    if limit is not None and len(out) > limit:
        out = out[:limit] + "…[截断]"
    return out


def redact(text: str | None, limit: int = MAX_SUMMARY) -> str:
    return _apply(text, _RULES, limit)


def redact_secrets(text: str | None, limit: int | None = None) -> str:
    return _apply(text, _SECRET_RULES, limit)
