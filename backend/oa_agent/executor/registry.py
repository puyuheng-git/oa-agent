"""运行时 Tool 注册表。正式运行从 Catalog（数据库）加载；`load()` 直接读 OpenAPI 文件，供测试使用。"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from oa_agent.settings import REPO_ROOT

DEFAULT_SPECS = (REPO_ROOT / "openapi" / "travel_expense.yaml",)


@dataclass(frozen=True)
class ToolSpec:
    name: str
    method: str
    path: str
    version: str
    schema_hash: str
    risk_level: str
    requires_confirmation: bool
    timeout_seconds: float
    inject_identity_fields: tuple[str, ...]
    top_level_fields: tuple[str, ...]
    query_params_field: str | None
    model_params: dict
    result_kind: str
    result_fields: tuple[str, ...]
    summary: str = ""
    description: str = ""
    result_labels: dict = field(default_factory=dict)
    list_columns: tuple[str, ...] = ()
    identity_params: dict = field(default_factory=dict)  # 普通查询参数名 → 身份字段，由服务端注入
    upstream: str = "office"  # office-api 地址标识（「OA 对接」中配置）
    kind: str = "office"  # office | builtin | mcp：Executor 据此分派
    builtin_id: str | None = None
    mcp_server_id: int | None = None
    mcp_tool_name: str | None = None
    sandbox_policy: dict = field(default_factory=dict)
    # 身份绑定：[{"param": "oa", "from": "identity.oa"}]；旧 inject_identity_fields 由 catalog 合成
    identity_bindings: tuple[dict, ...] = ()
    # 响应信封：oa_office（现网 code/msg/data）| raw_json（整段 JSON 即 data）；实际解析以 Connector 配置为准
    envelope_profile: str = "oa_office"

    def label(self, key: str) -> str:
        return self.result_labels.get(key) or key

    def columns(self) -> tuple[str, ...]:
        return self.list_columns or self.result_fields[:6]


class ToolRegistry:
    def __init__(self, tools: dict[str, ToolSpec]):
        self._tools = tools

    def get(self, name: str) -> ToolSpec | None:
        return self._tools.get(name)

    def names(self) -> list[str]:
        return sorted(self._tools)

    @classmethod
    def load(cls, paths: tuple[Path, ...] = DEFAULT_SPECS) -> "ToolRegistry":
        from oa_agent.executor.catalog import canonical_hash, parse_openapi, registration_blockers, schema_part, to_tool_spec

        tools: dict[str, ToolSpec] = {}
        for path in paths:
            spec_version, ops = parse_openapi(path)
            for name, spec in ops.items():
                if not spec["spec_enabled"] or spec["risk_level"] != "low" or spec["requires_confirmation"]:
                    continue
                if registration_blockers(_FileTool(), True, spec["method"]):
                    continue
                schema = schema_part(spec)
                tools[name] = to_tool_spec(schema, spec_version, 1, canonical_hash(schema))
        return cls(tools)


class _FileTool:
    enabled = spec_enabled = True
    risk_level = "low"
    requires_confirmation = False
