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
    """从模型逐段输出中增量取出给员工看的正文：JSON 输出取 "reply" 字段的字符串值；
    allow_text 时，不以 { 或 ` 开头的输出视为纯文本回答整体输出。工具调用（没有 reply 字段）不会产生任何片段。"""

    KEY = re.compile(r'"reply"\s*:\s*"')

    def __init__(self, on_delta: Callable[[str], None], allow_text: bool = False):
        self._on_delta, self._allow_text = on_delta, allow_text
        self._buf, self._emitted, self._mode = "", 0, ""

    def feed(self, piece: str) -> None:
        if not piece:
            return
        self._buf += piece
        if not self._mode:
            head = self._buf.lstrip()
            if not head:
                return
            self._mode = "text" if self._allow_text and head[0] not in "{`" else "json"
        if self._mode == "text":
            visible = self._buf.lstrip()
        else:
            m = self.KEY.search(self._buf)
            if not m:
                return
            visible = _decode_partial(self._buf[m.end():])
        if len(visible) > self._emitted:
            self._on_delta(visible[self._emitted:])
            self._emitted = len(visible)

    @property
    def emitted(self) -> bool:
        return self._emitted > 0


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
                on_delta: Callable[[str], None] | None = None) -> dict:
    """调用模型并解析 JSON 输出；记录 model_call 事件。只保留最终内容，不展示/记录推理链。
    text_fallback：输出不是 JSON 时把纯文本转成结果（返回 None 仍按无效输出处理）。
    on_delta：只流式输出 JSON 里 reply 字段；不以纯文本模式边想边推（避免英文思考过程刷屏）。
    纯文本兜底成功时，若尚未流式输出过，再整段推一次 reply。"""
    # 故意 allow_text=False：模型先输出英文/思考再 JSON 时，不能整段当员工可见正文
    stream = ReplyStream(on_delta, allow_text=False) if on_delta else None
    call = _LoggedCall(cfg, messages, rec, node_name)
    text, usage = call.run(chat_model, stream.feed if stream else None)
    parsed = _parse_json(text)
    if parsed is None and text_fallback is not None:
        parsed = text_fallback(text)
    if on_delta and parsed and stream is not None and not stream.emitted:
        reply = parsed.get("reply")
        if isinstance(reply, str) and reply.strip():
            on_delta(reply.strip())
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


def _parse_json(text: str) -> dict | None:
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return None
    try:
        value = json.loads(m.group(0))
    except ValueError:
        return None
    return value if isinstance(value, dict) else None
