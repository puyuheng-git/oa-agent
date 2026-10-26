"""配置中心：非密钥值存 agent_setting，密钥存 agent_secret。"""

from __future__ import annotations

import json
import re
from urllib.parse import urlparse

import sqlalchemy as sa
from sqlalchemy.orm import Session

from oa_agent.config.schema import GROUPS, FieldDef, GroupDef, secret_name
from oa_agent.config.vault import SecretVault
from oa_agent.db.models import Setting
from oa_agent.errors import AppError
from oa_agent.integrations.office_api import DEFAULT_UPSTREAM, UPSTREAM_KEY_RE
from oa_agent.observability.redact import redact

ORIGIN_RE = re.compile(r"https?://[A-Za-z0-9.-]+(:\d{1,5})?")
MAX_UPSTREAMS = 20


def _group(name: str) -> GroupDef:
    g = GROUPS.get(name)
    if g is None:
        raise AppError(404, "SETTING_GROUP_NOT_FOUND", f"配置组不存在：{name}")
    return g


def _coerce(f: FieldDef, value):
    if value is None or value == "":
        return f.default
    if f.kind == "int":
        if isinstance(value, bool):
            raise AppError(422, "VALIDATION_ERROR", f"{f.label} 必须是整数")
        try:
            number = int(value)
        except (TypeError, ValueError):
            raise AppError(422, "VALIDATION_ERROR", f"{f.label} 必须是整数") from None
        if (f.min is not None and number < f.min) or (f.max is not None and number > f.max):
            raise AppError(422, "VALIDATION_ERROR",
                           f"{f.label} 必须在 {f.min}～{f.max}{f.unit} 之间（当前 {number}）")
        return number
    if f.kind == "bool":
        if isinstance(value, bool):
            return value
        if str(value).lower() in ("true", "1", "yes", "on"):
            return True
        if str(value).lower() in ("false", "0", "no", "off"):
            return False
        raise AppError(422, "VALIDATION_ERROR", f"{f.label} 只能是开或关")
    if f.kind == "enum":
        if str(value) not in {v for v, _ in f.options}:
            raise AppError(422, "VALIDATION_ERROR", f"{f.label} 取值无效：{value}")
        return str(value)
    if f.kind in ("text", "str") and f.max is not None:
        text = str(value) if f.kind == "text" else str(value).strip()
        if len(text) > f.max:
            raise AppError(422, "VALIDATION_ERROR", f"{f.label} 不能超过 {f.max} 字")
        return text if text.strip() else f.default
    if f.kind == "url":
        return _url(f.label, value)
    if f.kind == "upstreams":
        return _upstreams(f, value)
    if f.kind == "list":
        items = value if isinstance(value, list) else str(value).split(",")
        items = [str(i).strip() for i in items if str(i).strip()]
        if f.key == "allowed_frame_origins":
            items = [_origin(f, i) for i in items]
        return items
    return str(value).strip()


def _url(label: str, value) -> str:
    text = str(value).strip()
    parsed = urlparse(text)
    if not parsed.scheme or not parsed.netloc:
        raise AppError(422, "VALIDATION_ERROR", f"{label} 不是合法地址")
    if parsed.password:
        raise AppError(422, "VALIDATION_ERROR", f"{label} 不要在地址中携带密码，请填写到密码字段")
    return text.rstrip("/")


def _upstreams(f: FieldDef, value) -> list[dict]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            raise AppError(422, "VALIDATION_ERROR", f"{f.label} 格式无效") from None
    if not isinstance(value, list) or not all(isinstance(i, dict) for i in value):
        raise AppError(422, "VALIDATION_ERROR", f"{f.label} 必须是 {{key, label, base_url}} 列表")
    if len(value) > MAX_UPSTREAMS:
        raise AppError(422, "VALIDATION_ERROR", f"{f.label} 最多 {MAX_UPSTREAMS} 项")
    out: list[dict] = []
    for item in value:
        key = str(item.get("key") or "").strip()
        if not UPSTREAM_KEY_RE.fullmatch(key) or key == DEFAULT_UPSTREAM:
            raise AppError(422, "VALIDATION_ERROR", f"{f.label}：标识 {key!r} 只能用小写字母、数字、下划线，"
                                                    f"以字母开头，2～32 位，且不能是 {DEFAULT_UPSTREAM}")
        if any(o["key"] == key for o in out):
            raise AppError(422, "VALIDATION_ERROR", f"{f.label}：标识 {key} 重复")
        label = f"{f.label}「{key}」"
        url = _url(label, item.get("base_url") or "")
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https") or parsed.username or parsed.query or parsed.fragment:
            raise AppError(422, "VALIDATION_ERROR", f"{label} 只能是 http(s) 地址，不能带用户名、查询串或 #")
        out.append({"key": key, "label": str(item.get("label") or "").strip()[:64] or key, "base_url": url})
    return out


def normalize_origin(text: str) -> str | None:
    """返回规范 origin（协议+主机+可选端口，无末尾 /）；不合法返回 None。"""
    origin = text.strip().rstrip("/")
    return origin if ORIGIN_RE.fullmatch(origin) else None


def _origin(f: FieldDef, text: str) -> str:
    origin = normalize_origin(text)
    if origin is None:
        raise AppError(422, "VALIDATION_ERROR",
                       f"{f.label} 只能填协议+域名（可带端口），如 https://oa.example.com，不能带路径或通配符：{text}")
    return origin


class SettingsService:
    def __init__(self, vault: SecretVault, tenant_id: str):
        self.vault = vault
        self.tenant = tenant_id

    def _rows(self, db: Session, group: str) -> dict[str, Setting]:
        rows = db.scalars(
            sa.select(Setting).where(Setting.tenant_id == self.tenant, Setting.setting_group == group)
        ).all()
        return {r.setting_key: r for r in rows}

    def view(self, db: Session, group: str) -> dict:
        """对外视图：密钥只给掩码。"""
        g = _group(group)
        rows = self._rows(db, group)
        values, meta = {}, {}
        for f in g.fields:
            if f.kind == "secret":
                values[f.key] = self.vault.describe(db, secret_name(group, f.key)).as_dict()
            else:
                row = rows.get(f.key)
                values[f.key] = row.value_json if row else f.default
                if row:
                    meta[f.key] = {"version": row.version, "updated_by": row.updated_by, "updated_at": row.updated_at}
        return {
            "group": g.name,
            "label": g.label,
            "apply_mode": g.apply_mode,
            "testable": g.testable,
            "description": g.description,
            "fields": [f.public() for f in g.fields],
            "values": values,
            "meta": meta,
        }

    def effective(self, db: Session, group: str) -> dict:
        """内部使用：含解密后的密钥。"""
        g = _group(group)
        rows = self._rows(db, group)
        out = {}
        for f in g.fields:
            if f.kind == "secret":
                out[f.key] = self.vault.reveal(db, secret_name(group, f.key))
            else:
                row = rows.get(f.key)
                out[f.key] = row.value_json if row else f.default
        return out

    def merged_candidate(self, db: Session, group: str, values: dict) -> dict:
        """把提交值与已存值合并（密钥留空 = 沿用已存值），用于「测试连接」。"""
        g = _group(group)
        current = self.effective(db, group)
        for f in g.fields:
            if f.key in values:
                v = values[f.key]
                if f.kind == "secret":
                    if v:
                        current[f.key] = str(v)
                else:
                    current[f.key] = _coerce(f, v)
        return current

    def summary(self, db: Session, group: str) -> str:
        """审计摘要：非密钥值（再脱敏）+ 密钥是否已设置。"""
        g = _group(group)
        rows = self._rows(db, group)
        out = {}
        for f in g.fields:
            if f.kind == "secret":
                out[f.key] = "已设置" if self.vault.describe(db, secret_name(group, f.key)).is_set else "未设置"
            else:
                row = rows.get(f.key)
                out[f.key] = row.value_json if row else f.default
        return redact(json.dumps(out, ensure_ascii=False, default=str))

    def update(self, db: Session, group: str, values: dict, clear_secrets: list[str], actor: str) -> list[str]:
        """返回变更过的字段名。密钥字段：空 = 不改；clear_secrets 中的字段被清除。"""
        g = _group(group)
        unknown = set(values) - {f.key for f in g.fields}
        if unknown:
            raise AppError(422, "VALIDATION_ERROR", f"未知字段：{', '.join(sorted(unknown))}")
        rows = self._rows(db, group)
        changed: list[str] = []
        for f in g.fields:
            if f.kind == "secret":
                name = secret_name(group, f.key)
                if f.key in clear_secrets:
                    if self.vault.delete(db, name):
                        changed.append(f.key)
                elif values.get(f.key):
                    self.vault.set(db, name, str(values[f.key]), actor)
                    changed.append(f.key)
                continue
            if f.key not in values:
                continue
            new = _coerce(f, values[f.key])
            row = rows.get(f.key)
            if row is None:
                if new == f.default:
                    continue
                db.add(
                    Setting(
                        tenant_id=self.tenant,
                        setting_group=group,
                        setting_key=f.key,
                        value_json=new,
                        updated_by=actor,
                    )
                )
                changed.append(f.key)
            elif row.value_json != new:
                row.value_json = new
                row.version += 1
                row.updated_by = actor
                changed.append(f.key)
        db.flush()
        return changed
