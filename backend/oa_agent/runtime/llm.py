"""按后台 LLM 配置构造模型客户端，并把调用记录为 model_call 事件（只记提供方原始 usage）。"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from typing import Callable

import sqlalchemy as sa
from sqlalchemy.orm import Session

from oa_agent.config.vault import SecretVault
from oa_agent.db.models import LlmDefaults, LlmModel, LlmProvider, LlmRoute
from oa_agent.observability.events import RunRecorder

INTENT_PURPOSE = "intent"


CAPABILITIES = ("text", "vision", "multimodal", "embedding")
TIERS = ("large", "small")
DEFAULT_MAX_FAILOVER = 3


@dataclass(frozen=True)
class ModelConfig:
    provider_name: str
    base_url: str
    api_key: str | None
    timeout: int
    model_name: str
    params: dict
    # 以下字段放在末尾并带默认值，保持旧的 6 参位置构造兼容
    model_id: int = 0
    capabilities: tuple[str, ...] = ("text",)
    model_tier: str = "large"


def _config_ok(m: LlmModel, p: LlmProvider, vault: SecretVault, db: Session) -> bool:
    """模型启用、提供方启用且已配置 API Key（设计 §4.2）。"""
    return bool(m.enabled and p.enabled and vault.reveal(db, p.secret_ref))


def _to_cfg(m: LlmModel, p: LlmProvider, vault: SecretVault, db: Session) -> ModelConfig:
    return ModelConfig(p.name, p.base_url, vault.reveal(db, p.secret_ref), p.timeout_seconds, m.model_name,
                       dict(m.params_json or {}), m.id, tuple(m.capabilities or ["text"]), m.model_tier or "large")


def _pool_ids(route: LlmRoute, after_id: int | None, by_id: dict, usable: Callable[[int], bool]) -> list[int]:
    """取池内可用候选：能力/档位须与池一致，无效条目静默跳过；after_id 在池内时只取其后。"""
    ids = list(route.model_ids or [])
    if after_id is not None and after_id in ids:
        ids = ids[ids.index(after_id) + 1:]
    out = []
    for mid in ids:
        pair = by_id.get(mid)
        if pair is None or mid == after_id or not usable(mid):
            continue
        m = pair[0]
        if route.capability in (m.capabilities or ["text"]) and (m.model_tier or "large") == route.model_tier:
            out.append(mid)
    return out


def _failover_route(routes: list[LlmRoute], model: LlmModel, capability: str | None) -> LlmRoute | None:
    """显式 model_id 的顺延池（设计 §4.4）：传了 capability 用 (capability, 模型档位)，
    否则在含该 ID 且档位一致的启用池里按 capability 固定顺序取第一条。"""
    tier = model.model_tier or "large"
    if capability:
        return next((r for r in routes if r.capability == capability and r.model_tier == tier), None)
    hits = [r for r in routes if r.model_tier == tier and model.id in (r.model_ids or [])]
    hits.sort(key=lambda r: CAPABILITIES.index(r.capability) if r.capability in CAPABILITIES else len(CAPABILITIES))
    return hits[0] if hits else None


def resolve_candidates(db: Session, vault: SecretVault, tenant_id: str, model_id: int | None = None, *,
                       capability: str | None = None, model_tier: str | None = None,
                       purpose: str = INTENT_PURPOSE) -> list[ModelConfig]:
    """按设计 §4.1 顺序给出配置可用的有序候选，长度 ≤ max_failover。
    显式 ID 可用时排首位，并追加其同池后续；不可用则跳过它走后续步骤；全部没有返回空列表。"""
    # 读取租户内模型、启用的路由池与默认配置
    defaults = db.scalar(sa.select(LlmDefaults).where(LlmDefaults.tenant_id == tenant_id))
    limit = (defaults.max_failover if defaults else None) or DEFAULT_MAX_FAILOVER
    rows = db.execute(
        sa.select(LlmModel, LlmProvider).join(LlmProvider, LlmProvider.id == LlmModel.provider_id)
        .where(LlmModel.tenant_id == tenant_id).order_by(LlmModel.id)
    ).all()
    by_id = {m.id: (m, p) for m, p in rows}
    routes = list(db.scalars(sa.select(LlmRoute).where(LlmRoute.tenant_id == tenant_id, LlmRoute.enabled.is_(True))))
    usable_cache: dict[int, bool] = {}

    def usable(mid: int) -> bool:
        if mid not in usable_cache:
            usable_cache[mid] = mid in by_id and _config_ok(*by_id[mid], vault, db)
        return usable_cache[mid]

    ordered: list[int] = []
    # 步骤 1：显式 ID（可用则首位）+ 同池后续
    if model_id is not None and model_id in by_id:
        if usable(model_id):
            ordered.append(model_id)
        pool = _failover_route(routes, by_id[model_id][0], capability)
        if pool is not None:
            ordered.extend(_pool_ids(pool, model_id, by_id, usable))
    # 步骤 2：(capability, tier) 路由池；仅当显式 ID 没产出候选时进入
    if not ordered and capability and model_tier:
        route = next((r for r in routes if r.capability == capability and r.model_tier == model_tier), None)
        if route is not None:
            ordered.extend(_pool_ids(route, None, by_id, usable))
    elif not ordered:
        # 步骤 3：全局默认；步骤 4：用途标签 → 任一启用模型
        gid = defaults.global_default_model_id if defaults else None
        if gid and usable(gid):
            ordered.append(gid)
        else:
            tagged = next((m.id for m, _ in rows if purpose in (m.purpose_tags or []) and usable(m.id)), None)
            ordered.append(tagged if tagged is not None else next((m.id for m, _ in rows if usable(m.id)), 0))
    # 去重、截断到 max_failover 并转为配置
    seen: list[int] = []
    for mid in ordered:
        if mid and mid not in seen:
            seen.append(mid)
    return [_to_cfg(*by_id[mid], vault, db) for mid in seen[:limit]]


def resolve_model(db: Session, vault: SecretVault, tenant_id: str, model_id: int | None = None,
                  purpose: str = INTENT_PURPOSE, *, capability: str | None = None,
                  model_tier: str | None = None) -> ModelConfig | None:
    """取首选候选；没有可用模型返回 None（走规则）。"""
    cands = resolve_candidates(db, vault, tenant_id, model_id, capability=capability,
                               model_tier=model_tier, purpose=purpose)
    return cands[0] if cands else None


def build_chat_model(cfg: ModelConfig):
    from langchain_openai import ChatOpenAI

    # 超时以后台 Provider 配置为准；复杂 ReAct / 附件任务可能需要数分钟
    timeout_sec = max(1, int(cfg.timeout or 60))
    kwargs = {"model": cfg.model_name, "base_url": cfg.base_url, "api_key": cfg.api_key or "not-set",
              "timeout": timeout_sec, "max_retries": 0, "stream_usage": True}
    if "temperature" in cfg.params:
        kwargs["temperature"] = cfg.params["temperature"]
    if "max_tokens" in cfg.params:
        kwargs["max_tokens"] = cfg.params["max_tokens"]
    return ChatOpenAI(**kwargs)


class ModelCallError(Exception):
    reply_emitted = False  # 失败前 reply/answer 正文是否已流式推给用户（是则不得顺延，避免重复文本）


class ReplyStream:
    """增量输出对话页可见内容：`<think>…</think>`（若有）+ JSON 的 reply/answer 字段。
    无标签的英文推理不会输出；工具调用（无 reply/answer）不产生片段。"""

    FIELD = re.compile(r'"(?:reply|answer)"\s*:\s*"')
    THINK_CLOSE = re.compile(r"</think\s*>", re.I)

    def __init__(self, on_delta: Callable[[str], None], allow_text: bool = False):
        self._on_delta, self._allow_text = on_delta, allow_text
        self._buf, self._emitted = "", 0
        self.reply_emitted = False  # 是否已输出 reply/answer 正文（不含纯思考段）

    def feed(self, piece: str) -> None:
        if not piece:
            return
        self._buf += piece
        visible = self._compose(self._buf)
        if len(visible) > self._emitted:
            self._on_delta(visible[self._emitted:])
            self._emitted = len(visible)

    @property
    def emitted(self) -> bool:
        return self._emitted > 0

    def _compose(self, buf: str) -> str:
        think_part, rest = _split_think_for_stream(buf)
        answer = self._extract_answer(rest)
        if answer:
            self.reply_emitted = True
        if think_part is None and not answer:
            return ""
        if think_part is None:
            return answer
        if not answer:
            return think_part
        return f"{think_part}\n{answer}"

    def _extract_answer(self, text: str) -> str:
        body = _THINK_BLOCK_RE.sub("", text or "")
        open_at = _THINK_OPEN_RE.search(body)
        if open_at:
            body = body[: open_at.start()]
        body = re.sub(r"<[^>]*$", "", body)
        head = body.lstrip()
        if not head:
            return ""
        if self._allow_text and head[0] not in "{`":
            return head
        m = self.FIELD.search(body)
        if not m:
            return ""
        return _decode_partial(body[m.end():])


ESCAPES = {'"': '"', "\\": "\\", "/": "/", "b": "\b", "f": "\f", "n": "\n", "r": "\r", "t": "\t"}


def _decode_partial(raw: str) -> str:
    """解码一个尚未结束的 JSON 字符串（raw 从开引号之后开始）；末尾不完整的转义先不输出。"""
    out, i = [], 0
    while i < len(raw):
        ch = raw[i]
        if ch == '"':
            break
        if ch != "\\":
            out.append(ch)
            i += 1
            continue
        if i + 1 >= len(raw):
            break
        nxt = raw[i + 1]
        if nxt == "u":
            code = raw[i + 2:i + 6]
            if len(code) < 4:
                break
            try:
                out.append(chr(int(code, 16)))
            except ValueError:
                pass
            i += 6
            continue
        out.append(ESCAPES.get(nxt, nxt))
        i += 2
    return "".join(out)


def _call(chat_model, messages: list, on_piece: Callable[[str], None] | None):
    """返回 (最终文本, usage)。有流式回调且模型支持 stream 时逐段读取，否则一次性 invoke。"""
    if on_piece is None or not hasattr(chat_model, "stream"):
        resp = chat_model.invoke(messages)
        usage = (resp.response_metadata or {}).get("token_usage") or getattr(resp, "usage_metadata", None)
        return _final_text(resp.content), usage
    parts: list[str] = []
    usage = None
    for chunk in chat_model.stream(messages):
        piece = _final_text(getattr(chunk, "content", ""))
        if piece:
            parts.append(piece)
            on_piece(piece)
        usage = getattr(chunk, "usage_metadata", None) or usage
        meta = getattr(chunk, "response_metadata", None) or {}
        usage = meta.get("token_usage") or usage
    return "".join(parts), (dict(usage) if usage else None)


def invoke_json(chat_model, cfg: ModelConfig, messages: list, rec: RunRecorder, node_name: str,
                text_fallback: Callable[[str], dict | None] | None = None,
                on_delta: Callable[[str], None] | None = None,
                on_reply_emitted: Callable[[], None] | None = None) -> dict:
    """调用模型并解析 JSON 输出；记录 model_call 事件。
    text_fallback：输出不是 JSON 时把纯文本转成结果（返回 None 仍按无效输出处理）。
    on_delta：流式输出 `<think>` 思考段（若有）与 JSON 的 reply/answer；无标签英文推理不推送。
    on_reply_emitted：当 reply/answer 正文已流式输出时回调（纯思考段不触发），供上层避免重复推送终态。
    纯文本兜底成功时，若尚未流式输出过，再整段推一次可见正文。"""
    # 故意 allow_text=False：模型先输出无标签英文推理再 JSON 时，不能整段当员工可见正文
    stream = ReplyStream(on_delta, allow_text=False) if on_delta else None
    call = _LoggedCall(cfg, messages, rec, node_name)
    try:
        text, usage = call.run(chat_model, stream.feed if stream else None)
    except ModelCallError as exc:
        # 调用中途失败：标记正文是否已流出，供 invoke_json_failover 决定能否换模型
        exc.reply_emitted = bool(stream is not None and stream.reply_emitted)
        raise
    cleaned = _strip_think_blocks(text)
    parsed = _parse_json(cleaned)
    if parsed is None and text_fallback is not None:
        parsed = text_fallback(cleaned)
    parsed = _attach_thinking(parsed, text)
    if on_delta and parsed and stream is not None and not stream.emitted:
        visible = _visible_from_parsed(parsed)
        if visible:
            on_delta(visible)
            if _visible_answer_body(visible):
                stream.reply_emitted = True
    if stream is not None and stream.reply_emitted and on_reply_emitted is not None:
        on_reply_emitted()
    return call.finish(text, usage, parsed)


_INVALID_OUTPUT_MARKERS = ("模型输出不是合法 JSON", "模型没有输出内容")


def is_provider_error(exc: BaseException) -> bool:
    """是否传输/提供方错误（可顺延）：模型已返回但输出非法 JSON/空输出不算（设计 §4.3）。"""
    if not isinstance(exc, ModelCallError):
        return True
    msg = str(exc)
    return not any(marker in msg for marker in _INVALID_OUTPUT_MARKERS)


def invoke_json_failover(pairs: list[tuple[object, ModelConfig]], messages: list, rec: RunRecorder,
                         node_name: str, **kwargs) -> dict:
    """按候选顺序调用 invoke_json：提供方错误换下一个候选；非法 JSON、正文已流出或候选耗尽直接抛出。
    顺延成功时在该次 model_log 上记 failover_from（首选模型 ID）与 attempt（第几次尝试）。"""
    if not pairs:
        raise ModelCallError("没有可用的模型候选")
    last_index = len(pairs) - 1
    for i, (chat_model, cfg) in enumerate(pairs):
        try:
            parsed = invoke_json(chat_model, cfg, messages, rec, node_name, **kwargs)
        except ModelCallError as exc:
            # 非提供方错误（输出非法）、正文已流式输出（换模型会重复文本）或已无后续候选：不再顺延
            if not is_provider_error(exc) or exc.reply_emitted or i == last_index:
                raise
            continue
        if i > 0 and rec.model_logs:
            rec.model_logs[-1]["failover_from"] = pairs[0][1].model_id
            rec.model_logs[-1]["attempt"] = i + 1
        return parsed
    raise ModelCallError("没有可用的模型候选")  # 不可达：循环内必然 return 或 raise


def invoke_text(chat_model, cfg: ModelConfig, messages: list, rec: RunRecorder, node_name: str) -> str:
    """调用模型取纯文本输出（如会话摘要）；同样记录 model_call 事件。空输出视为失败。"""
    call = _LoggedCall(cfg, messages, rec, node_name)
    text, usage = call.run(chat_model, None)
    text = text.strip()
    call.finish(text, usage, {"text": text} if text else None, "模型没有输出内容")
    return text


class _LoggedCall:
    def __init__(self, cfg: ModelConfig, messages: list, rec: RunRecorder, node_name: str):
        self.cfg, self.messages, self.rec, self.node_name = cfg, messages, rec, node_name
        self.prompt = {"messages": [{"role": role, "content": content} for role, content in messages]}
        self.meta = {"model": cfg.model_name, "provider": cfg.provider_name}
        self.log = {"node_name": node_name, "provider": cfg.provider_name, "model": cfg.model_name,
                    "messages": self.prompt["messages"], "output_text": None, "parsed": None, "usage": None,
                    "status": "error", "error_summary": None, "duration_ms": None}
        self.started = 0.0

    def _duration(self) -> int:
        return int((time.perf_counter() - self.started) * 1000)

    def run(self, chat_model, on_piece: Callable[[str], None] | None) -> tuple[str, dict | None]:
        self.rec.model_call_count += 1
        self.rec.model_logs.append(self.log)
        self.started = time.perf_counter()
        try:
            text, usage = _call(chat_model, self.messages, on_piece)
        except Exception as exc:  # noqa: BLE001 —— 任意提供方错误都降级处理
            summary = f"{type(exc).__name__}: {exc}"
            self.log.update(error_summary=summary, duration_ms=self._duration())
            self.rec.event("model_call", node_name=self.node_name, status="error", input_summary=self.prompt,
                           duration_ms=self._duration(), error_code="MODEL_CALL_FAILED", error_summary=summary,
                           metadata=self.meta)
            raise ModelCallError(str(exc)) from exc
        if usage:
            self.rec.usages.append({**self.meta, "usage": usage})
        return text, usage

    def finish(self, text: str, usage: dict | None, parsed: dict | None,
               invalid: str = "模型输出不是合法 JSON") -> dict:
        ok = parsed is not None
        duration = self._duration()
        self.log.update(output_text=text, parsed=parsed, usage=usage, duration_ms=duration,
                        status="ok" if ok else "error", error_summary=None if ok else invalid)
        self.rec.event("model_call", node_name=self.node_name, status="ok" if ok else "error",
                       duration_ms=duration, error_code=None if ok else "MODEL_OUTPUT_INVALID",
                       input_summary=self.prompt, output_summary=parsed if ok else text,
                       metadata={**self.meta, "usage": usage})
        if not ok:
            raise ModelCallError(invalid)
        return parsed


def complete_json(chat_model, messages: list) -> dict:
    """不属于员工运行的模型调用（如后台生成草稿）：只返回解析后的 JSON，不记运行事件。"""
    try:
        resp = chat_model.invoke(messages)
    except Exception as exc:  # noqa: BLE001
        raise ModelCallError(f"{type(exc).__name__}: {exc}") from exc
    parsed = _parse_json(_final_text(resp.content))
    if not isinstance(parsed, dict):
        raise ModelCallError("模型输出不是合法 JSON 对象")
    return parsed


def _final_text(content) -> str:
    """只取最终文本块；提供方返回的 thinking/reasoning 块不记录、不展示。"""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(b.get("text", "") if isinstance(b, dict) and b.get("type") == "text" else
                       (b if isinstance(b, str) else "") for b in content)
    return ""


_THINK_BLOCK_RE = re.compile(r"<think\b[^>]*>.*?</think\s*>", re.I | re.S)
_THINK_OPEN_RE = re.compile(r"<think\b[^>]*>", re.I)
_THINK_CLOSE_RE = re.compile(r"</think\s*>", re.I)
_THINK_WRAP_RE = re.compile(r"^<think\b[^>]*>(.*?)</think\s*>\s*(.*)$", re.I | re.S)


def _strip_think_blocks(text: str) -> str:
    """去掉模型泄漏的 `<think>…</think>` 思考段（含未闭合的开标签之后内容）。"""
    cleaned = _THINK_BLOCK_RE.sub("", text or "")
    open_at = _THINK_OPEN_RE.search(cleaned)
    if open_at:
        cleaned = cleaned[: open_at.start()]
    return cleaned.strip()


def _split_think_for_stream(buf: str) -> tuple[str | None, str]:
    """流式拆分：返回 (带标签的思考可见段或 None, 剩余文本)。思考未闭合时剩余为空，避免段内 JSON 泄漏。"""
    open_m = _THINK_OPEN_RE.search(buf or "")
    if not open_m:
        return None, re.sub(r"<[^>]*$", "", buf or "")
    after_open = buf[open_m.end():]
    close_m = _THINK_CLOSE_RE.search(after_open)
    if not close_m:
        inner = re.sub(r"<[^>]*$", "", after_open)
        return f"<think>{inner}", ""
    inner = after_open[: close_m.start()]
    rest = after_open[close_m.end():]
    before = buf[: open_m.start()]
    return f"<think>{inner}</think>", before + rest


def extract_think_inner(text: str) -> str:
    """提取已闭合 `<think>` 段正文（多段合并）。"""
    parts = [m.group(1).strip() for m in re.finditer(
        r"<think\b[^>]*>(.*?)</think\s*>", text or "", re.I | re.S)]
    return "\n\n".join(p for p in parts if p)


def peel_think_wrap(text: str) -> tuple[str, str]:
    """若文本以完整 think 包裹开头，返回 (思考正文, 其余)；否则 ("", 原文)。"""
    m = _THINK_WRAP_RE.match((text or "").lstrip())
    if not m:
        return "", text or ""
    return (m.group(1) or "").strip(), (m.group(2) or "")


def wrap_think(thinking: str, body: str) -> str:
    thinking = (thinking or "").strip()
    body = body or ""
    if not thinking:
        return body
    if not body:
        return f"<think>{thinking}</think>"
    return f"<think>{thinking}</think>\n{body}"


def _attach_thinking(parsed: dict | None, raw: str) -> dict | None:
    """把原文思考段挂到 reply/answer，供终态与历史展示；解析 JSON 仍用去思考后的正文。"""
    if not parsed:
        return parsed
    thinking = extract_think_inner(raw)
    if not thinking:
        return parsed
    out = dict(parsed)
    for key in ("reply", "answer"):
        val = out.get(key)
        if isinstance(val, str) and val.strip():
            if _THINK_OPEN_RE.match(val.lstrip()):
                return out
            out[key] = wrap_think(thinking, val)
            return out
    return out


def _visible_from_parsed(parsed: dict) -> str:
    for key in ("reply", "answer"):
        val = parsed.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    return ""


def _visible_answer_body(visible: str) -> bool:
    _, body = peel_think_wrap(visible)
    return bool((body or "").strip())


def _iter_json_objects(text: str):
    """按花括号平衡扫描文本中的 JSON 对象候选（忽略字符串内括号）。"""
    i, n = 0, len(text)
    while i < n:
        if text[i] != "{":
            i += 1
            continue
        depth, in_str, esc, j = 0, False, False, i
        while j < n:
            ch = text[j]
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
            elif ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    yield text[i : j + 1]
                    break
            j += 1
        i = j + 1 if depth == 0 else i + 1


def _parse_json_objects(text: str) -> dict | None:
    last: dict | None = None
    for candidate in _iter_json_objects(text or ""):
        try:
            value = json.loads(candidate)
        except ValueError:
            continue
        if isinstance(value, dict):
            last = value
    return last


def _parse_json(text: str) -> dict | None:
    """解析模型 JSON：优先取 `</think>` 之外的对象；没有则回退到全文最后一个合法对象。"""
    without_think = _THINK_BLOCK_RE.sub("", text or "")
    parsed = _parse_json_objects(without_think)
    if parsed is not None:
        return parsed
    return _parse_json_objects(text)
