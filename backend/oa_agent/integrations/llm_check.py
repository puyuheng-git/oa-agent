"""LLM 连接测试（OpenAI 兼容协议）。只返回提供方真实响应，不做任何估算。"""

from __future__ import annotations

import time

import httpx

from oa_agent.observability.redact import redact


def _headers(api_key: str | None) -> dict:
    return {"Authorization": f"Bearer {api_key}"} if api_key else {}


def _fail(exc_or_resp) -> dict:
    if isinstance(exc_or_resp, httpx.Response):
        return {"ok": False, "error": redact(f"HTTP {exc_or_resp.status_code}: {exc_or_resp.text[:300]}")}
    return {"ok": False, "error": redact(f"{type(exc_or_resp).__name__}: {exc_or_resp}")}


def check_provider(base_url: str, api_key: str | None, timeout: float, *, limit: int = 50) -> dict:
    started = time.perf_counter()
    try:
        resp = httpx.get(f"{base_url.rstrip('/')}/models", headers=_headers(api_key), timeout=timeout)
    except httpx.HTTPError as exc:
        return _fail(exc)
    if resp.status_code != 200:
        return _fail(resp)
    try:
        models = [m.get("id") for m in resp.json().get("data", []) if isinstance(m, dict) and m.get("id")]
    except ValueError:
        models = []
    return {
        "ok": True,
        "latency_ms": int((time.perf_counter() - started) * 1000),
        "model_count": len(models),
        "truncated": len(models) > limit,
        "models": models[:limit],
    }


def check_model(base_url: str, api_key: str | None, timeout: float, model: str) -> dict:
    started = time.perf_counter()
    payload = {"model": model, "messages": [{"role": "user", "content": "ping"}], "max_tokens": 8}
    try:
        resp = httpx.post(f"{base_url.rstrip('/')}/chat/completions", json=payload,
                          headers=_headers(api_key), timeout=timeout)
    except httpx.HTTPError as exc:
        return _fail(exc)
    if resp.status_code != 200:
        return _fail(resp)
    try:
        usage = resp.json().get("usage")
    except ValueError:
        usage = None
    return {"ok": True, "latency_ms": int((time.perf_counter() - started) * 1000), "usage": usage}
