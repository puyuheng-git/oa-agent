"""系统内置 Tool 目录（规格 §5.1）与幂等 upsert。

- 代码内声明全部内置能力；注册表对外名固定 `builtin.<id去掉 sys. 前缀>`，`builtin_id` 仍存 `sys.xxx`。
- `ensure_builtin_tools` 只插入缺失行：已存在的行（含管理员改过的 enabled / 摘要 / 沙箱策略）一律不覆盖。
- 高风险项（cron / http / web_search / fs_*）默认 enabled=False；本模块只落库，不实现执行。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Session

from oa_agent.db.models import Tool

BUILTIN_PREFIX = "sys."
TOOL_NAME_PREFIX = "builtin."
SYSTEM_OPERATOR = "system"


@dataclass(frozen=True)
class BuiltinDef:
    builtin_id: str
    summary: str
    risk_level: str
    enabled: bool
    needs_sandbox: bool = False
    sandbox_policy: dict[str, Any] = field(default_factory=dict)

    @property
    def name(self) -> str:
        return tool_name(self.builtin_id)


def tool_name(builtin_id: str) -> str:
    """`sys.time` → `builtin.time`。"""
    if not builtin_id.startswith(BUILTIN_PREFIX) or len(builtin_id) == len(BUILTIN_PREFIX):
        raise ValueError(f"内置工具 id 必须形如 sys.<name>：{builtin_id!r}")
    return TOOL_NAME_PREFIX + builtin_id[len(BUILTIN_PREFIX):]


BUILTIN_CATALOG: list[BuiltinDef] = [
    BuiltinDef("sys.time", "当前时间 / 时区", "low", True),
    BuiltinDef("sys.calc", "安全表达式计算", "low", True),
    BuiltinDef("sys.export", "导出文件并返回下载票据", "medium", True, True,
               {"export_ttl_seconds": 3600}),
    BuiltinDef("sys.memory", "员工长期记忆", "medium", True),
    BuiltinDef("sys.cron", "定时触发已发布的流程或任务模板", "high", False),
    BuiltinDef("sys.http", "受控 HTTP 请求", "high", False, True,
               {"http_allow_hosts": [], "http_methods": ["GET"], "http_max_response_bytes": 65536}),
    BuiltinDef("sys.web_search", "网络搜索", "high", False, True, {"search_max_results": 5}),
    BuiltinDef("sys.fs_read", "沙箱内读文件", "high", False, True, {"fs_root": "sandbox", "fs_max_read_bytes": 65536}),
    BuiltinDef("sys.fs_write", "沙箱内写文件", "high", False, True, {"fs_root": "sandbox"}),
]


def ensure_builtin_tools(db: Session, tenant_id: str) -> int:
    """幂等 upsert：只补缺失行，返回新插入条数。调用方负责事务。"""
    existing = set(db.scalars(sa.select(Tool.name).where(Tool.tenant_id == tenant_id,
                                                         Tool.name.like(TOOL_NAME_PREFIX + "%"))))
    created = 0
    for d in BUILTIN_CATALOG:
        if d.name in existing:
            continue
        db.add(Tool(tenant_id=tenant_id, name=d.name, kind="builtin", builtin_id=d.builtin_id, summary=d.summary,
                    enabled=d.enabled, risk_level=d.risk_level, requires_confirmation=False,
                    sandbox_policy_json=dict(d.sandbox_policy) or None, source_file="builtin",
                    updated_by=SYSTEM_OPERATOR))
        created += 1
    if created:
        db.flush()
    return created
