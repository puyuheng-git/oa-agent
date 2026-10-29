"""EnvelopeProfile 注册表与统一 parse 入口。"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from oa_agent.connectors.profiles.oa_office import parse_oa_office
from oa_agent.connectors.profiles.raw_json import parse_raw_json

EnvelopeParser = Callable[..., tuple[Any, str]]

_PROFILES: dict[str, EnvelopeParser] = {
    "oa_office": parse_oa_office,
    "raw_json": parse_raw_json,
}


def get_profile(name: str) -> EnvelopeParser:
    try:
        return _PROFILES[name]
    except KeyError as exc:
        raise KeyError(f"未知 envelope profile：{name}") from exc


def parse_envelope(
    profile: str,
    status_code: int,
    body: object,
    *,
    success_codes: set[str],
    hint_max: int,
    json_decode_ok: bool = True,
) -> tuple[object, str]:
    """成功返回 (data, hint)；失败抛 ConnectorError。"""
    parser = get_profile(profile)
    return parser(
        status_code,
        body,
        success_codes=success_codes,
        hint_max=hint_max,
        json_decode_ok=json_decode_ok,
    )
