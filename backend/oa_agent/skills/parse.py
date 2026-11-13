"""解析 agentskills.io / Anthropic SKILL.md frontmatter。"""

from __future__ import annotations

import re
from typing import Any

import yaml

NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
MAX_NAME = 64
MAX_DESC = 1024
MAX_SKILL_MD = 200_000


class SkillMdError(ValueError):
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


def parse_skill_md(text: str) -> dict[str, Any]:
    """返回 {name, description, body, frontmatter, raw}。"""
    raw = text if isinstance(text, str) else ""
    if not raw.strip():
        raise SkillMdError("SKILL.md 为空")
    if len(raw) > MAX_SKILL_MD:
        raise SkillMdError(f"SKILL.md 不能超过 {MAX_SKILL_MD} 字符")
    fm: dict[str, Any] = {}
    body = raw
    if raw.startswith("---"):
        end = raw.find("\n---", 3)
        if end < 0:
            raise SkillMdError("SKILL.md frontmatter 未闭合")
        block = raw[3:end].strip()
        body = raw[end + 4:].lstrip("\n")
        try:
            loaded = yaml.safe_load(block) if block else {}
        except yaml.YAMLError as exc:
            raise SkillMdError(f"frontmatter 无法解析：{exc}") from exc
        if loaded is None:
            fm = {}
        elif not isinstance(loaded, dict):
            raise SkillMdError("frontmatter 必须是对象")
        else:
            fm = loaded
    name = str(fm.get("name") or "").strip().lower()
    description = str(fm.get("description") or "").strip()
    if not name or not NAME_RE.fullmatch(name):
        raise SkillMdError("name 须为小写字母/数字/连字符，最长 64")
    if not description:
        raise SkillMdError("description 不能为空")
    if len(description) > MAX_DESC:
        raise SkillMdError(f"description 不能超过 {MAX_DESC} 字符")
    if len(name) > MAX_NAME:
        raise SkillMdError(f"name 不能超过 {MAX_NAME} 字符")
    return {
        "name": name,
        "description": description,
        "body": body,
        "frontmatter": fm,
        "raw": raw,
        "display_name": str(fm.get("display_name") or name).strip()[:128] or name,
    }
