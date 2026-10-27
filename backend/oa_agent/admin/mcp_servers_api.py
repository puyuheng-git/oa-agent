"""/v1/admin/mcp-servers：出站 MCP 连接配置 CRUD（规格 §3.2 / §3.4，权限点 ops.mcp.manage）。

headers / env 只写不读：密文存 SecretVault，响应只返回 headers_set / env_set 掩码；审计只记「已变更」。
远程（sse/http）地址必须命中「MCP 连接」配置组的白名单；未配置白名单时拒绝所有远程地址。
"""

from __future__ import annotations

import json
import re
from typing import Literal
from urllib.parse import urlparse

import sqlalchemy as sa
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError

from oa_agent.auth.rbac import AdminCtx, admin_read, admin_write
from oa_agent.config.crypto import mask_display
from oa_agent.db.models import McpServer, Tool
from oa_agent.errors import AppError

router = APIRouter(prefix="/v1/admin/mcp-servers", tags=["admin-mcp-servers"])

PERM = "ops.mcp.manage"
NAME_RE = re.compile(r"^[a-z][a-z0-9_-]{1,63}$")
PREFIX_RE = re.compile(r"^[a-z0-9_]{0,32}$")
ENV_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")
HEADER_KEY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]{0,63}$")
SHELL_CHARS = set(" \t\r\n;&|<>$`\"'\\*?(){}[]!#~")
DEFAULT_PORTS = {"http": 80, "https": 443}
MAX_MAP_ITEMS = 50
MAX_VALUE_LEN = 4096


class McpServerIn(BaseModel):
    name: str = Field(max_length=64)
    display_name: str = Field(default="", max_length=128)
    transport: Literal["stdio", "sse", "http"]
    command: str | None = Field(default=None, max_length=255)
    args: list[str] = Field(default_factory=list, max_length=50)
    url: str | None = Field(default=None, max_length=512)
    tool_prefix: str = Field(default="", max_length=32)
    timeout_seconds: int = Field(default=30, ge=1, le=300)
    enabled: bool = False
    # 写入专用：None = 沿用，{} = 清除，非空 = 整体替换
    headers: dict[str, str] | None = None
    env: dict[str, str] | None = None


def _secret_name(name: str, kind: str) -> str:
    return f"mcp.{name}.{kind}"


def _secret_view(ctx: AdminCtx, name: str, kind: str) -> dict:
    # 值是 JSON 字典，不给末 4 位提示（避免泄露序列化尾部字符）
    is_set = ctx.runtime.vault.describe(ctx.db, _secret_name(name, kind)).is_set
    return {"is_set": is_set, "display": mask_display(is_set, "")}


def _view(ctx: AdminCtx, row: McpServer) -> dict:
    return {
        "name": row.name, "display_name": row.display_name, "enabled": row.enabled,
        "transport": row.transport, "command": row.command, "args": list(row.args_json or []), "url": row.url,
        "tool_prefix": row.tool_prefix, "timeout_seconds": row.timeout_seconds,
        "headers_set": _secret_view(ctx, row.name, "headers"), "env_set": _secret_view(ctx, row.name, "env"),
        "last_sync_at": row.last_sync_at, "last_sync_result": row.last_sync_result,
        "last_sync_error": row.last_sync_error,
        "created_by": row.created_by, "created_at": row.created_at, "updated_at": row.updated_at,
    }


def _get(ctx: AdminCtx, name: str) -> McpServer:
    row = ctx.db.scalar(sa.select(McpServer).where(McpServer.tenant_id == ctx.runtime.tenant_id,
                                                   McpServer.name == name))
    if row is None:
        raise AppError(404, "NOT_FOUND", "MCP 连接不存在")
    return row


def _bad(message: str) -> AppError:
    return AppError(422, "VALIDATION_ERROR", message)


def _origin_key(url: str) -> tuple[str, str, int] | None:
    parsed = urlparse(url.strip())
    if parsed.scheme not in DEFAULT_PORTS or not parsed.hostname:
        return None
    try:
        port = parsed.port or DEFAULT_PORTS[parsed.scheme]
    except ValueError:
        return None
    return parsed.scheme, parsed.hostname.lower(), port


def _check_url(ctx: AdminCtx, url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise _bad("MCP 远程地址只能是 https 地址")
    if parsed.username or parsed.password or parsed.fragment:
        raise _bad("MCP 地址不能带用户名、密码或 #，鉴权头请填写到「请求头」")
    allowed = ctx.runtime.settings_svc.effective(ctx.db, "mcp").get("allowed_origins") or []
    ctx.db.rollback()
    if not allowed:
        raise _bad("尚未配置远程 MCP 地址白名单，请先在「系统接入 → MCP 连接」中配置后再添加远程连接")
    key = _origin_key(url)
    if key is None or key not in {k for k in (_origin_key(o) for o in allowed) if k}:
        raise _bad("该地址不在远程 MCP 地址白名单内")


def _check_command(command: str | None) -> str:
    text = (command or "").strip()
    if not text:
        raise _bad("stdio 类型必须填写 command")
    if any(c in SHELL_CHARS for c in text):
        raise _bad("command 只能是可执行文件路径或名称，不能包含空格、引号或 shell 元字符；参数请填在 args")
    return text


def _check_map(label: str, data: dict[str, str], key_re: re.Pattern) -> None:
    if len(data) > MAX_MAP_ITEMS:
        raise _bad(f"{label} 最多 {MAX_MAP_ITEMS} 项")
    for key, value in data.items():
        if not key_re.fullmatch(key):
            raise _bad(f"{label} 名称不合法：{key}")
        if len(value) > MAX_VALUE_LEN or "\r" in value or "\n" in value:
            raise _bad(f"{label} {key} 的值过长或含换行")


def _validate(ctx: AdminCtx, body: McpServerIn) -> str | None:
    """返回规范化后的 command（stdio）；校验失败抛 422。"""
    if not NAME_RE.fullmatch(body.name):
        raise _bad("名称只能用小写字母、数字、下划线、连字符，以字母开头，2～64 位")
    if not PREFIX_RE.fullmatch(body.tool_prefix):
        raise _bad("tool_prefix 只能用小写字母、数字、下划线，最多 32 位")
    if any(len(a) > 512 or "\x00" in a for a in body.args):
        raise _bad("args 单项过长或含非法字符")
    if body.headers:
        _check_map("请求头", body.headers, HEADER_KEY_RE)
    if body.env:
        _check_map("环境变量", body.env, ENV_KEY_RE)
    if body.transport == "stdio":
        if body.url:
            raise _bad("stdio 类型不能填写 url")
        if body.headers:
            raise _bad("stdio 类型不支持请求头，请使用环境变量")
        return _check_command(body.command)
    if body.command or body.args:
        raise _bad("远程类型不能填写 command / args")
    if body.env:
        raise _bad("远程类型不支持环境变量，请使用请求头")
    if not body.url or not body.url.strip():
        raise _bad("远程类型必须填写 url")
    _check_url(ctx, body.url.strip())
    return None


def _apply_secret(ctx: AdminCtx, name: str, kind: str, value: dict[str, str] | None, *, drop: bool) -> bool:
    """按「None 沿用 / {} 清除 / 非空替换」写入保险箱；drop=True 强制清除（类型切换）。返回是否变更。"""
    secret = _secret_name(name, kind)
    vault = ctx.runtime.vault
    if drop or value == {}:
        return vault.delete(ctx.db, secret)
    if value:
        vault.set(ctx.db, secret, json.dumps(value, ensure_ascii=False), ctx.user.username)
        return True
    return False


def _summary(row: McpServer, changed_secrets: list[str]) -> dict:
    out = {"transport": row.transport, "enabled": row.enabled, "command": row.command,
           "args": list(row.args_json or []), "url": row.url, "tool_prefix": row.tool_prefix,
           "timeout_seconds": row.timeout_seconds}
    for kind in changed_secrets:
        out[kind] = "已变更"
    return out


def _fill(row: McpServer, body: McpServerIn, command: str | None, env_value: dict[str, str] | None) -> None:
    row.display_name = body.display_name or body.name
    row.transport = body.transport
    row.enabled = body.enabled
    row.command = command
    row.args_json = list(body.args) if body.transport == "stdio" else None
    row.url = body.url.strip() if body.transport != "stdio" and body.url else None
    row.tool_prefix = body.tool_prefix
    row.timeout_seconds = body.timeout_seconds
    if body.transport != "stdio":
        row.env_json = None
    elif env_value is not None:
        row.env_json = sorted(env_value) or None


@router.get("")
def list_servers(ctx: AdminCtx = Depends(admin_read(PERM))):
    rows = ctx.db.scalars(sa.select(McpServer).where(McpServer.tenant_id == ctx.runtime.tenant_id)
                          .order_by(McpServer.name)).all()
    return {"items": [_view(ctx, r) for r in rows]}


@router.get("/{name}")
def get_server(name: str, ctx: AdminCtx = Depends(admin_read(PERM))):
    return _view(ctx, _get(ctx, name))


@router.post("")
def create_server(body: McpServerIn, ctx: AdminCtx = Depends(admin_write(PERM))):
    command = _validate(ctx, body)
    try:
        with ctx.db.begin():
            if ctx.db.scalar(sa.select(McpServer.id).where(McpServer.tenant_id == ctx.runtime.tenant_id,
                                                           McpServer.name == body.name)):
                raise AppError(409, "ALREADY_EXISTS", f"MCP 连接 {body.name} 已存在，请改为编辑")
            row = McpServer(tenant_id=ctx.runtime.tenant_id, name=body.name, transport=body.transport,
                            created_by=ctx.user.username)
            _fill(row, body, command, body.env)
            ctx.db.add(row)
            ctx.db.flush()
            changed = []
            if _apply_secret(ctx, body.name, "headers", body.headers, drop=False):
                changed.append("headers")
            if _apply_secret(ctx, body.name, "env", body.env, drop=False):
                changed.append("env")
            row.headers_secret_ref = _secret_name(body.name, "headers") if "headers" in changed else None
            ctx.audit("mcp_server.create", "mcp_server", body.name, after=_summary(row, changed))
    except IntegrityError:
        raise AppError(409, "ALREADY_EXISTS", f"MCP 连接 {body.name} 已存在，请改为编辑") from None
    return _view(ctx, _get(ctx, body.name))


@router.put("/{name}")
def update_server(name: str, body: McpServerIn, ctx: AdminCtx = Depends(admin_write(PERM))):
    if body.name != name:
        raise AppError(422, "VALIDATION_ERROR", "MCP 连接名创建后不能修改")
    command = _validate(ctx, body)
    with ctx.db.begin():
        row = _get(ctx, name)
        before = _summary(row, [])
        stdio = body.transport == "stdio"
        changed = []
        if _apply_secret(ctx, name, "headers", body.headers, drop=stdio):
            changed.append("headers")
        if _apply_secret(ctx, name, "env", body.env, drop=not stdio):
            changed.append("env")
        _fill(row, body, command, body.env)
        if stdio and body.env == {}:
            row.env_json = None
        has_headers = ctx.runtime.vault.describe(ctx.db, _secret_name(name, "headers")).is_set
        row.headers_secret_ref = _secret_name(name, "headers") if has_headers else None
        ctx.audit("mcp_server.update", "mcp_server", name, before=before, after=_summary(row, changed))
    return _view(ctx, _get(ctx, name))


@router.delete("/{name}")
def delete_server(name: str, ctx: AdminCtx = Depends(admin_write(PERM))):
    with ctx.db.begin():
        row = _get(ctx, name)
        used = ctx.db.scalars(sa.select(Tool.name).where(Tool.tenant_id == ctx.runtime.tenant_id,
                                                         Tool.mcp_server_id == row.id)).all()
        if used:
            raise AppError(409, "MCP_SERVER_IN_USE", f"以下 Tool 仍来自该连接，请先处理：{'、'.join(used[:10])}")
        before = _summary(row, [])
        for kind in ("headers", "env"):
            ctx.runtime.vault.delete(ctx.db, _secret_name(name, kind))
        ctx.db.delete(row)
        ctx.audit("mcp_server.delete", "mcp_server", name, before=before)
    return {"ok": True}
