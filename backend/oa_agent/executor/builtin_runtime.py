"""内置 Tool 运行时（规格 §5.1）：低风险能力 sys.time / sys.calc / sys.export / sys.memory。

- 低风险：time/calc/export/memory。高风险（规格 §5.2–5.3）：http / web_search / fs_read / fs_write / cron，
  必须有 `sandbox_policy`，否则 `ToolError("SANDBOX_REQUIRED")`；cron 只登记「已发布 workflow 名 + cron 表达式」，不执行任何命令。
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
from urllib.parse import urlsplit

import httpx
import sqlalchemy as sa

from oa_agent.errors import AppError
from oa_agent.executor.executor import MSG_NOT_AVAILABLE, Identity, ToolError
from oa_agent.executor.registry import ToolSpec
from oa_agent.security.prompt_guard import normalize_text, scan_flags, scrub_html_with_flags

CHINA_TZ = timezone(timedelta(hours=8))
DEFAULT_TIMEZONE = "Asia/Shanghai"

CALC_MAX_CHARS = 200
CALC_MAX_POW_EXPONENT = 64
CALC_MAX_ABS = 10 ** 100

EXPORT_MAX_BYTES = 1024 * 1024
EXPORT_DEFAULT_TTL = 3600
EXPORT_FILENAME_MAX = 80
MEMORY_LIST_LIMIT = 50

HTTP_DEFAULT_MAX_BYTES = 65536
HTTP_HARD_MAX_BYTES = 1024 * 1024
HTTP_ALLOWED_METHODS = frozenset({"GET", "HEAD", "POST", "PUT", "PATCH", "DELETE"})
FS_DEFAULT_MAX_READ = 65536
FS_DEFAULT_MAX_WRITE = 262144
SEARCH_SECRET_NAME = "builtin.web_search.api_key"
SEARCH_DEFAULT_RESULTS = 5
SEARCH_HARD_MAX_RESULTS = 10
CRON_DEFAULT_MAX_JOBS = 20
CRON_KV_TTL = 365 * 86400
CRON_ARGS = frozenset({"action", "workflow", "cron", "job_id"})
_CRON_FIELDS = ((0, 59), (0, 23), (1, 31), (1, 12), (0, 7))
_CRON_PART = re.compile(r"^(\*|\d{1,2}(?:-\d{1,2})?)(?:/(\d{1,2}))?$")
_DRIVE_RE = re.compile(r"^[A-Za-z]:")
_WORKFLOW_RE = re.compile(r"^[A-Za-z0-9_.\-]{1,64}$")

_BIN_OPS: dict[type, Callable[[Any, Any], Any]] = {
    ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv, ast.Mod: operator.mod, ast.Pow: operator.pow,
}
_UNARY_OPS: dict[type, Callable[[Any], Any]] = {ast.UAdd: operator.pos, ast.USub: operator.neg}
_UNSAFE_NAME = re.compile(r"[^0-9A-Za-z_.\-\u4e00-\u9fff]+")
_TICKET_RE = re.compile(r"^[A-Za-z0-9_\-]{16,64}$")


def _invalid(message: str) -> ToolError:
    return ToolError("INVALID_ARGUMENT", message)


def _sandbox_required(why: str) -> ToolError:
    return ToolError("SANDBOX_REQUIRED", f"高风险内置工具缺少沙箱策略：{why}", user_message=MSG_NOT_AVAILABLE)


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
    """tenant_id/session_factory/data_dir 缺失时对应能力（memory / export / fs_*）不可用，time/calc 始终可用。

    高风险能力额外依赖：kv（cron 登记；可传 KVManager 或 KV）、vault（web_search 供应商 key）、
    global_setting（http 全局白名单默认）。
    """

    HIGH_RISK = frozenset({"sys.http", "sys.web_search", "sys.fs_read", "sys.fs_write", "sys.cron"})

    def __init__(self, *, tenant_id: str = "dscpa", session_factory: Callable[[], Any] | None = None,
                 data_dir: Path | str | None = None, kv: Any | None = None, vault: Any | None = None,
                 global_setting: Callable[[str, str], Any] | None = None):
        self.tenant_id = tenant_id
        self.session_factory = session_factory
        self.data_dir = Path(data_dir) if data_dir is not None else None
        self.kv = kv
        self.vault = vault
        self.global_setting = global_setting
        self._handlers: dict[str, Callable[[ToolSpec, dict, Identity], dict]] = {
            "sys.time": self._time, "sys.calc": self._calc, "sys.export": self._export, "sys.memory": self._memory,
            "sys.http": self._http, "sys.web_search": self._web_search, "sys.fs_read": self._fs_read,
            "sys.fs_write": self._fs_write, "sys.cron": self._cron,
        }

    def call(self, spec: ToolSpec, args: dict, *, identity: Identity) -> dict:
        handler = self._handlers.get(spec.builtin_id or "")
        if handler is None:  # 未实现的内置能力
            raise _not_available()
        if spec.builtin_id in self.HIGH_RISK and not (isinstance(spec.sandbox_policy, dict) and spec.sandbox_policy):
            raise _sandbox_required("sandbox_policy 为空")  # 高风险默认关闭：无策略一律拒绝
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

    # ---- sys.http
    def _global(self, group: str, key: str) -> Any:
        if self.global_setting is None:
            return None
        try:
            return self.global_setting(group, key)
        except Exception:  # noqa: BLE001 —— 全局配置读取失败按「未配置」处理（更严格）
            return None

    def _http(self, spec: ToolSpec, args: dict, identity: Identity) -> dict:
        policy = spec.sandbox_policy
        hosts = _str_list(policy.get("http_allow_hosts")) or _str_list(self._global("runtime", "http_allow_hosts"))
        if not hosts:
            raise _sandbox_required("http_allow_hosts 为空")
        methods = {m.upper() for m in _str_list(policy.get("http_methods"))} or {"GET"}
        method = str(args.get("method") or "GET").strip().upper()
        if method not in HTTP_ALLOWED_METHODS or method not in methods:
            raise ToolError("METHOD_NOT_ALLOWED", f"方法不在允许列表：{method}", user_message="该请求方式未被允许")
        url = _check_url(str(args.get("url") or ""), hosts)
        limit = _bounded_int(policy.get("http_max_response_bytes"), HTTP_DEFAULT_MAX_BYTES, 1, HTTP_HARD_MAX_BYTES)
        body = args.get("body")
        kwargs: dict[str, Any] = {}
        if body is not None:
            if method == "GET" or method == "HEAD":
                raise _invalid("GET/HEAD 不能带 body")
            kwargs["json"] = body
        # 不带员工 Authorization / oa；不跟随重定向（避免经 302 越过白名单）
        status, raw, truncated, ctype = _fetch(method, url, timeout=spec.timeout_seconds, limit=limit, **kwargs)
        body, flags = _clean_body(raw, ctype)
        return {"status": status, "content_type": ctype, "body": body, "truncated": truncated,
                "size_bytes": len(raw), "guard_flags": sorted(flags)}

    # ---- sys.web_search
    def _web_search(self, spec: ToolSpec, args: dict, identity: Identity) -> dict:
        policy = spec.sandbox_policy
        endpoint = str(policy.get("search_endpoint") or "").strip()
        if not endpoint.lower().startswith("https://"):
            raise _sandbox_required("search_endpoint 未配置或非 https")
        query = str(args.get("query") or "").strip()
        if not query:
            raise _invalid("缺少参数 query")
        if len(query) > 300:
            raise _invalid("query 不能超过 300 字")
        key = self._search_key()
        if not key:
            raise _not_available()  # 无供应商 key：不可用
        count = _bounded_int(policy.get("search_max_results"), SEARCH_DEFAULT_RESULTS, 1, SEARCH_HARD_MAX_RESULTS)
        header = str(policy.get("search_key_header") or "Authorization").strip()
        value = f"Bearer {key}" if header.lower() == "authorization" else key
        status, raw, _, ctype = _fetch("GET", endpoint, timeout=spec.timeout_seconds, limit=HTTP_HARD_MAX_BYTES // 4,
                                       params={"q": query, "count": count}, headers={header: value})
        if status >= 400:
            raise ToolError("UPSTREAM_HTTP_ERROR", f"搜索供应商返回 HTTP {status}", http_status=status,
                            user_message="搜索服务暂时不可用")
        try:
            data = json.loads(raw.decode("utf-8", errors="replace"))
        except ValueError:
            raise ToolError("UPSTREAM_BAD_RESPONSE", "搜索供应商返回非 JSON", user_message="搜索服务暂时不可用") from None
        items = data.get("results") if isinstance(data, dict) else None
        if items is None and isinstance(data, dict) and isinstance(data.get("web"), dict):
            items = data["web"].get("results")
        results = []
        flags: set[str] = set()
        for it in (items or [])[:count]:
            if not isinstance(it, dict):
                continue
            row = {}
            for field, val, cap in (("title", it.get("title"), 200), ("url", it.get("url"), 500),
                                    ("snippet", it.get("snippet") or it.get("description"), 500)):
                clean, f = scrub_html_with_flags(str(val or ""))
                row[field] = clean[:cap]
                flags |= f
            results.append(row)
        return {"query": query, "results": results, "guard_flags": sorted(flags)}

    def _search_key(self) -> str | None:
        if self.vault is None or self.session_factory is None:
            return None
        with self.session_factory() as db:
            return self.vault.reveal(db, SEARCH_SECRET_NAME) or None

    # ---- sys.fs_read / sys.fs_write
    def _sandbox_root(self) -> Path:
        if self.data_dir is None:
            raise _not_available()
        return self.data_dir / "sandbox" / _safe_segment(self.tenant_id)

    def _resolve_in_sandbox(self, raw: object) -> tuple[Path, str]:
        root = self._sandbox_root()
        rel = raw if isinstance(raw, str) else ""
        if not rel.strip():
            raise _invalid("缺少参数 path")
        if "\x00" in rel or len(rel) > 255:
            raise _invalid("path 无效")
        norm = rel.replace("\\", "/")
        if norm.startswith("/") or _DRIVE_RE.match(norm) or ".." in norm.split("/"):
            raise ToolError("PATH_NOT_ALLOWED", "路径越出沙箱", user_message="该路径不被允许")
        root_res = root.resolve()
        target = (root_res / norm).resolve()  # 解析符号链接后再校验
        if target != root_res and root_res not in target.parents:
            raise ToolError("PATH_NOT_ALLOWED", "路径越出沙箱", user_message="该路径不被允许")
        if target == root_res:
            raise _invalid("path 必须指向文件")
        return target, norm

    def _fs_read(self, spec: ToolSpec, args: dict, identity: Identity) -> dict:
        target, norm = self._resolve_in_sandbox(args.get("path"))
        limit = _bounded_int(spec.sandbox_policy.get("fs_max_read_bytes"), FS_DEFAULT_MAX_READ, 1, HTTP_HARD_MAX_BYTES)
        if not target.is_file():
            raise ToolError("NOT_FOUND", "文件不存在", user_message="文件不存在")
        with target.open("rb") as fh:
            data = fh.read(limit + 1)
        truncated = len(data) > limit
        text, flags = _clean_body(data[:limit], "text/html" if norm.lower().endswith((".html", ".htm")) else "")
        return {"path": norm, "content": text, "truncated": truncated, "guard_flags": sorted(flags)}

    def _fs_write(self, spec: ToolSpec, args: dict, identity: Identity) -> dict:
        target, norm = self._resolve_in_sandbox(args.get("path"))
        content = args.get("content")
        if not isinstance(content, str):
            raise _invalid("缺少参数 content")
        data = content.encode("utf-8")
        limit = _bounded_int(spec.sandbox_policy.get("fs_max_write_bytes"), FS_DEFAULT_MAX_WRITE, 1,
                             HTTP_HARD_MAX_BYTES)
        if len(data) > limit:
            raise _invalid(f"写入内容不能超过 {limit} 字节")
        if target.is_dir():
            raise _invalid("path 指向目录")
        target.parent.mkdir(parents=True, exist_ok=True)
        root_res = self._sandbox_root().resolve()
        if root_res not in target.parent.resolve().parents and target.parent.resolve() != root_res:
            raise ToolError("PATH_NOT_ALLOWED", "路径越出沙箱", user_message="该路径不被允许")
        target.write_bytes(data)
        return {"path": norm, "written": True, "size_bytes": len(data)}

    # ---- sys.cron（只登记，不执行任何命令）
    def _cron_kv(self) -> Any:
        if self.kv is None:
            raise _not_available()
        return getattr(self.kv, "current", self.kv)

    def _cron(self, spec: ToolSpec, args: dict, identity: Identity) -> dict:
        extra = set(args) - CRON_ARGS
        if extra:
            raise _invalid("不支持的参数：" + ",".join(sorted(map(str, extra))))
        action = str(args.get("action") or "list").strip()
        if action not in ("add", "list", "remove"):
            raise _invalid("action 取值无效")
        kv = self._cron_kv()
        key = f"builtin:cron:{self.tenant_id}:{identity.oa}"
        try:
            jobs = json.loads(kv.get(key) or "[]")
        except ValueError:
            jobs = []
        if action == "list":
            return {"items": jobs}
        if action == "remove":
            job_id = str(args.get("job_id") or "").strip()
            kept = [j for j in jobs if j.get("job_id") != job_id]
            if len(kept) != len(jobs):
                kv.set(key, json.dumps(kept, ensure_ascii=False), CRON_KV_TTL)
            return {"removed": len(kept) != len(jobs), "job_id": job_id}
        workflow = str(args.get("workflow") or "").strip()
        if not _WORKFLOW_RE.match(workflow):
            raise _invalid("workflow 名称无效")
        expr = _validate_cron(args.get("cron"))
        if not self._is_published_workflow(workflow):
            raise _invalid("只能登记已发布的 workflow")
        max_jobs = _bounded_int(spec.sandbox_policy.get("cron_max_jobs"), CRON_DEFAULT_MAX_JOBS, 1, 200)
        if len(jobs) >= max_jobs:
            raise _invalid(f"定时任务不能超过 {max_jobs} 个")
        job = {"job_id": secrets.token_hex(6), "workflow": workflow, "cron": expr,
               "created_at": int(time.time())}
        jobs.append(job)
        kv.set(key, json.dumps(jobs, ensure_ascii=False), CRON_KV_TTL)
        # 登记即止：本运行时不含调度器，不执行 workflow 或任何命令
        return {"added": True, "job_id": job["job_id"], "workflow": workflow, "cron": expr, "executes": False}

    def _is_published_workflow(self, workflow: str) -> bool:
        from oa_agent.db.models import WorkflowVersion

        if self.session_factory is None:
            raise _not_available()
        with self.session_factory() as db:
            return db.scalar(sa.select(WorkflowVersion.id).where(
                WorkflowVersion.tenant_id == self.tenant_id, WorkflowVersion.workflow_id == workflow,
                WorkflowVersion.status == "published").limit(1)) is not None


def _str_list(value: object) -> list[str]:
    if isinstance(value, str):
        value = [value]
    return [str(v).strip().lower() for v in value if str(v).strip()] if isinstance(value, (list, tuple)) else []


def _bounded_int(value: object, default: int, lo: int, hi: int) -> int:
    try:
        n = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, n))


def _host_allowed(host: str, allow: list[str]) -> bool:
    for pat in allow:
        if pat.startswith("*."):
            if host.endswith(pat[1:]) and len(host) > len(pat) - 1:
                return True
        elif host == pat:
            return True
    return False


def _check_url(url: str, allow: list[str]) -> str:
    url = url.strip()
    if not url or len(url) > 2000 or any(ord(c) < 32 for c in url):
        raise _invalid("缺少或非法的 url")
    try:
        parts = urlsplit(url)
        host = (parts.hostname or "").lower()
        _ = parts.port
    except ValueError:
        raise _invalid("url 无效") from None
    if parts.scheme not in ("http", "https") or not host:
        raise _invalid("url 只允许 http/https")
    if parts.username is not None or parts.password is not None:
        raise _invalid("url 不能含用户信息")
    if not _host_allowed(host, allow):
        raise ToolError("HOST_NOT_ALLOWED", f"主机不在白名单：{host}", user_message="该地址不在允许访问的范围内")
    return url


def _fetch(method: str, url: str, *, timeout: float, limit: int, params: dict | None = None,
           headers: dict | None = None, json: Any = None) -> tuple[int, bytes, bool, str]:
    """受控出站请求：不跟随重定向、不带员工身份、按字节上限流式读取。"""
    try:
        with httpx.Client(timeout=timeout or 10.0, follow_redirects=False, trust_env=False) as client:
            with client.stream(method, url, params=params, headers=headers, json=json) as resp:
                buf = bytearray()
                truncated = False
                for chunk in resp.iter_bytes():
                    buf.extend(chunk)
                    if len(buf) > limit:
                        truncated = True
                        del buf[limit:]
                        break
                return resp.status_code, bytes(buf), truncated, resp.headers.get("content-type", "")
    except httpx.TimeoutException:
        raise ToolError("UPSTREAM_TIMEOUT", "出站请求超时", user_message="请求超时") from None
    except httpx.HTTPError as exc:  # 只记异常类型，避免 URL / 头里的密钥进入错误信息
        raise ToolError("UPSTREAM_UNAVAILABLE", f"出站请求失败：{type(exc).__name__}",
                        user_message="请求失败") from None


def _clean_body(raw: bytes, content_type: str) -> tuple[str, set[str]]:
    """出站/沙箱文件正文清洗：HTML → scrub_html；其它 → NFKC；一并返回防注入标志（不含原文）。"""
    text = raw.decode("utf-8", errors="replace")
    if "html" in (content_type or "").lower() or text.lstrip().startswith("<"):
        return scrub_html_with_flags(text)
    clean = normalize_text(text)
    return clean, scan_flags(clean)


def _validate_cron(value: object) -> str:
    expr = " ".join(str(value or "").split())
    fields = expr.split(" ")
    if len(fields) != 5:
        raise _invalid("cron 必须是 5 段表达式")
    for field, (lo, hi) in zip(fields, _CRON_FIELDS):
        for part in field.split(","):
            m = _CRON_PART.match(part)
            if not m:
                raise _invalid("cron 表达式无效")
            rng, step = m.group(1), m.group(2)
            if rng != "*":
                nums = [int(x) for x in rng.split("-")]
                if any(n < lo or n > hi for n in nums) or (len(nums) == 2 and nums[0] > nums[1]):
                    raise _invalid("cron 表达式无效")
            if step is not None and int(step) < 1:
                raise _invalid("cron 表达式无效")
    return expr


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
    return BuiltinRuntime(tenant_id=rt.tenant_id, session_factory=rt.session, data_dir=rt.settings.data_dir,
                          kv=rt.kv, vault=rt.vault, global_setting=rt.setting)

