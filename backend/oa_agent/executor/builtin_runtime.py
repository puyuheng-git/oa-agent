"""内置 Tool 运行时（规格 §5.1）：低风险能力 sys.time / sys.calc / sys.export / sys.memory。

- 只实现 time/calc/export/memory；cron/http/web_search/fs_* 为高风险，本运行时一律「未对你开放」。
- 身份（oa）只取自服务端 `Identity`；模型传入的 oa/tenant 一律忽略。
- `call` 返回结构化 dict；Executor 负责转成文本并 `wrap_untrusted(source="builtin")` 后回图。
"""

from __future__ import annotations

import ast
import json
import operator
import re
import secrets
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from oa_agent.errors import AppError
from oa_agent.executor.executor import MSG_NOT_AVAILABLE, Identity, ToolError
from oa_agent.executor.registry import ToolSpec

CHINA_TZ = timezone(timedelta(hours=8))
DEFAULT_TIMEZONE = "Asia/Shanghai"

CALC_MAX_CHARS = 200
CALC_MAX_POW_EXPONENT = 64
CALC_MAX_ABS = 10 ** 100

EXPORT_MAX_BYTES = 1024 * 1024
EXPORT_DEFAULT_TTL = 3600
EXPORT_FILENAME_MAX = 80
MEMORY_LIST_LIMIT = 50

_BIN_OPS: dict[type, Callable[[Any, Any], Any]] = {
    ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv, ast.Mod: operator.mod, ast.Pow: operator.pow,
}
_UNARY_OPS: dict[type, Callable[[Any], Any]] = {ast.UAdd: operator.pos, ast.USub: operator.neg}
_UNSAFE_NAME = re.compile(r"[^0-9A-Za-z_.\-\u4e00-\u9fff]+")
_TICKET_RE = re.compile(r"^[A-Za-z0-9_\-]{16,64}$")


def _invalid(message: str) -> ToolError:
    return ToolError("INVALID_ARGUMENT", message)


def _not_available() -> ToolError:
    return ToolError("TOOL_NOT_AVAILABLE", "内置工具不可用", user_message=MSG_NOT_AVAILABLE)


# ---------------------------------------------------------------- sys.calc
def _eval_node(node: ast.AST) -> int | float:
    if isinstance(node, ast.Expression):
        return _eval_node(node.body)
    if isinstance(node, ast.Constant):
        if type(node.value) not in (int, float):  # 排除 bool / str / None / complex
            raise _invalid("表达式只允许数字")
        return node.value
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY_OPS:
        return _check(_UNARY_OPS[type(node.op)](_eval_node(node.operand)))
    if isinstance(node, ast.BinOp) and type(node.op) in _BIN_OPS:
        left, right = _eval_node(node.left), _eval_node(node.right)
        if isinstance(node.op, ast.Pow) and abs(right) > CALC_MAX_POW_EXPONENT:
            raise _invalid("指数过大")
        try:
            return _check(_BIN_OPS[type(node.op)](left, right))
        except ZeroDivisionError:
            raise _invalid("除数不能为 0") from None
        except OverflowError:
            raise _invalid("计算结果过大") from None
    raise _invalid("表达式只允许数字与 + - * / // % ** 和括号")


def _check(value: int | float) -> int | float:
    if isinstance(value, complex):  # (-8) ** 0.5 等
        raise _invalid("计算结果不是实数")
    if abs(value) > CALC_MAX_ABS:
        raise _invalid("计算结果过大")
    return value


def safe_calc(expression: object) -> int | float:
    text = str(expression or "").strip()
    if not text:
        raise _invalid("缺少参数 expression")
    if len(text) > CALC_MAX_CHARS:
        raise _invalid(f"表达式不能超过 {CALC_MAX_CHARS} 个字符")
    try:
        tree = ast.parse(text, mode="eval")
    except (SyntaxError, ValueError, RecursionError, MemoryError):
        raise _invalid("表达式无法解析") from None
    try:
        return _eval_node(tree)
    except RecursionError:
        raise _invalid("表达式嵌套过深") from None


# ---------------------------------------------------------------- runtime
class BuiltinRuntime:
    """tenant_id/session_factory/data_dir 缺失时对应能力（memory / export）不可用，time/calc 始终可用。"""

    def __init__(self, *, tenant_id: str = "dscpa", session_factory: Callable[[], Any] | None = None,
                 data_dir: Path | str | None = None):
        self.tenant_id = tenant_id
        self.session_factory = session_factory
        self.data_dir = Path(data_dir) if data_dir is not None else None
        self._handlers: dict[str, Callable[[ToolSpec, dict, Identity], dict]] = {
            "sys.time": self._time, "sys.calc": self._calc, "sys.export": self._export, "sys.memory": self._memory,
        }

    def call(self, spec: ToolSpec, args: dict, *, identity: Identity) -> dict:
        handler = self._handlers.get(spec.builtin_id or "")
        if handler is None:  # 高风险 / 未实现的内置能力
            raise _not_available()
        return handler(spec, dict(args or {}), identity)

    # ---- sys.time
    def _time(self, spec: ToolSpec, args: dict, identity: Identity) -> dict:
        name = str(args.get("timezone") or DEFAULT_TIMEZONE).strip()
        tz = _resolve_tz(name)
        now = datetime.now(tz)
        return {"iso": now.isoformat(timespec="seconds"), "date": now.date().isoformat(),
                "time": now.strftime("%H:%M:%S"), "weekday": now.isoweekday(), "timezone": name,
                "utc_offset": now.strftime("%z")}

    # ---- sys.calc
    def _calc(self, spec: ToolSpec, args: dict, identity: Identity) -> dict:
        expression = str(args.get("expression") or "").strip()
        return {"expression": expression, "result": safe_calc(expression)}

    # ---- sys.export
    def _export_dir(self) -> Path:
        if self.data_dir is None:
            raise _not_available()
        return self.data_dir / "exports" / _safe_segment(self.tenant_id)

    def _export(self, spec: ToolSpec, args: dict, identity: Identity) -> dict:
        root = self._export_dir()
        content = args.get("content")
        if not isinstance(content, str) or not content:
            raise _invalid("缺少参数 content")
        data = content.encode("utf-8")
        if len(data) > EXPORT_MAX_BYTES:
            raise _invalid(f"导出内容不能超过 {EXPORT_MAX_BYTES // 1024} KB")
        filename = _safe_filename(args.get("filename"))
        ttl = int((spec.sandbox_policy or {}).get("export_ttl_seconds") or EXPORT_DEFAULT_TTL)
        ticket = secrets.token_urlsafe(18)
        now = int(time.time())
        root.mkdir(parents=True, exist_ok=True)
        (root / f"{ticket}.bin").write_bytes(data)
        meta = {"ticket": ticket, "oa": identity.oa, "filename": filename, "size_bytes": len(data),
                "created_at": now, "expires_at": now + ttl}
        (root / f"{ticket}.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
        # 不返回服务器路径；下载由后续「下载票据」接口按 ticket + 员工身份校验
        return {"ticket": ticket, "filename": filename, "size_bytes": len(data), "expires_in": ttl,
                "expires_at": meta["expires_at"]}

    def read_export_meta(self, ticket: str) -> dict | None:
        """按票据读取元数据（供下载接口校验 oa / 过期）；票据格式非法或不存在返回 None。"""
        if not _TICKET_RE.match(ticket or ""):
            return None
        path = self._export_dir() / f"{ticket}.json"
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    # ---- sys.memory
    def _memory(self, spec: ToolSpec, args: dict, identity: Identity) -> dict:
        from oa_agent.chat import memory_store as ms
        from oa_agent.chat.memory_guard import filter_injection_rows, is_blocked_memory_text

        if self.session_factory is None:
            raise _not_available()
        action = str(args.get("action") or "list").strip()
        if action not in ("add", "list", "forget"):
            raise _invalid("action 取值无效")
        scope = {"tenant_id": self.tenant_id, "oa": identity.oa}
        try:
            with self.session_factory() as db:
                if action == "list":
                    rows, _ = ms.list_active(db, limit=MEMORY_LIST_LIMIT, offset=0, **scope)
                    rows = filter_injection_rows(rows)
                    return {"items": [{"memory_id": r.memory_id, "kind": r.kind, "text": r.text} for r in rows]}
                text = str(args.get("text") or "").strip()
                if not text:
                    raise _invalid("缺少参数 text")
                if action == "add":
                    if is_blocked_memory_text(text):
                        raise ToolError("MEMORY_REJECTED", "记忆内容含越权/注入短语",
                                        user_message="这类内容不能记入长期记忆")
                    with db.begin():
                        row = ms.add_memory(db, kind=str(args.get("kind") or "note"), text=text, **scope)
                        return {"added": True, "memory_id": row.memory_id}
                with db.begin():
                    target = ms.forget_by_match(db, match_text=text, **scope)
                    return {"forgotten": target is not None, "memory_id": target.memory_id if target else None}
        except AppError as exc:
            raise ToolError("MEMORY_REJECTED", exc.message, user_message=exc.message) from exc


def _resolve_tz(name: str):
    if name in ("Asia/Shanghai", "PRC"):
        return CHINA_TZ
    if name.upper() == "UTC":
        return timezone.utc
    try:
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
        try:
            return ZoneInfo(name)
        except (ZoneInfoNotFoundError, ValueError, OSError):
            pass
    except ImportError:  # pragma: no cover
        pass
    raise _invalid("timezone 无效")


def _safe_segment(value: str) -> str:
    seg = _UNSAFE_NAME.sub("_", str(value or "")).strip("._")
    return seg or "default"


def _safe_filename(raw: object) -> str:
    base = str(raw or "").replace("\\", "/").split("/")[-1]
    name = _UNSAFE_NAME.sub("_", base).strip("._")
    if not name:
        raise _invalid("缺少参数 filename")
    if len(name) > EXPORT_FILENAME_MAX:
        stem, dot, ext = name.rpartition(".")
        name = (stem[:EXPORT_FILENAME_MAX - len(ext) - 1] + "." + ext) if dot and len(ext) < 10 \
            else name[:EXPORT_FILENAME_MAX]
    return name


def build_builtin_runtime(rt: Any) -> BuiltinRuntime:
    """从 AppRuntime 构造生产用 BuiltinRuntime：tenant / session（memory）/ data_dir（export 写 data/exports/{tenant}/）。"""
    return BuiltinRuntime(tenant_id=rt.tenant_id, session_factory=rt.session, data_dir=rt.settings.data_dir)

