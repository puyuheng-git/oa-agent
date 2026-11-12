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
from oa_agent.db.models import LlmModel, LlmProvider
from oa_agent.observability.events import RunRecorder

INTENT_PURPOSE = "intent"


@dataclass(frozen=True)
class ModelConfig:
    provider_name: str
    base_url: str
    api_key: str | None
    timeout: int
    model_name: str
    params: dict


def resolve_model(db: Session, vault: SecretVault, tenant_id: str, model_id: int | None = None,
                  purpose: str = INTENT_PURPOSE) -> ModelConfig | None:
    """发布配置指定了模型且该模型启用时用它；否则优先选带用途标签的启用模型，再否则任一启用模型；
    都没有返回 None（走规则）。"""
    rows = db.execute(
        sa.select(LlmModel, LlmProvider)
        .join(LlmProvider, LlmProvider.id == LlmModel.provider_id)
        .where(LlmModel.tenant_id == tenant_id, LlmModel.enabled.is_(True), LlmProvider.enabled.is_(True))
        .order_by(LlmModel.id)
    ).all()
    if not rows:
        return None
    pinned = next(((m, p) for m, p in rows if model_id is not None and m.id == model_id), None)
    model, provider = pinned or next(((m, p) for m, p in rows if purpose in (m.purpose_tags or [])), rows[0])
    return ModelConfig(provider.name, provider.base_url, vault.reveal(db, provider.secret_ref),
                       provider.timeout_seconds, model.model_name, dict(model.params_json or {}))


def build_chat_model(cfg: ModelConfig):
    from langchain_openai import ChatOpenAI

    kwargs = {"model": cfg.model_name, "base_url": cfg.base_url, "api_key": cfg.api_key or "not-set",
              "timeout": min(cfg.timeout, 30), "max_retries": 0, "stream_usage": True}
    if "temperature" in cfg.params:
        kwargs["temperature"] = cfg.params["temperature"]
    if "max_tokens" in cfg.params:
        kwargs["max_tokens"] = cfg.params["max_tokens"]
    return ChatOpenAI(**kwargs)


class ModelCallError(Exception):
    pass


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
    text, usage = call.run(chat_model, stream.feed if stream else None)
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
    if parsed is None:
        raise ModelCallError("模型输出不是合法 JSON")
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
