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
    how: str = ""  # 实现原理（管理端只读说明）
    constraints: tuple[str, ...] = ()

    @property
    def name(self) -> str:
        return tool_name(self.builtin_id)


def tool_name(builtin_id: str) -> str:
    """`sys.time` → `builtin.time`。"""
    if not builtin_id.startswith(BUILTIN_PREFIX) or len(builtin_id) == len(BUILTIN_PREFIX):
        raise ValueError(f"内置工具 id 必须形如 sys.<name>：{builtin_id!r}")
    return TOOL_NAME_PREFIX + builtin_id[len(BUILTIN_PREFIX):]


BUILTIN_CATALOG: list[BuiltinDef] = [
    BuiltinDef(
        "sys.time", "当前时间 / 时区", "low", True,
        how="在 Agent 进程内取当前时刻，按 IANA 时区格式化后返回。不访问 OA、不访问外网。",
        constraints=("缺省时区 Asia/Shanghai", "结果经不可信数据围栏后回图"),
    ),
    BuiltinDef(
        "sys.calc", "安全表达式计算", "low", True,
        how="用 AST 解析表达式，只允许数字与 + - * / // % ** 和括号，禁止函数调用、属性访问与变量名。",
        constraints=("表达式最长 200 字符", "指数绝对值 ≤ 64", "结果绝对值有上限，防溢出"),
    ),
    BuiltinDef(
        "sys.export", "导出文件并返回下载票据", "medium", True, True,
        {"export_ttl_seconds": 3600},
        how="把文本写入本机 data/exports/{tenant}/，签发一次性下载票据；不直连 OA 业务库。",
        constraints=("内容体积有上限", "票据有过期时间（见沙箱策略 export_ttl_seconds）", "文件名经清洗，禁止路径穿越"),
    ),
    BuiltinDef(
        "sys.memory", "员工长期记忆", "medium", True,
        how="读写本系统 agent_employee_memory 表中的「当前员工」记忆；oa 只取服务端会话，模型无法指定他人。",
        constraints=("敏感内容（身份证号、工资等）拒绝写入", "条数有上限", "与对话里「请记住」走同一套领域服务"),
    ),
    BuiltinDef(
        "sys.cron", "定时触发已发布的流程或任务模板", "high", False, True, {"cron_max_jobs": 20},
        how="只在 KV 中登记「已发布 workflow 名 + cron 表达式」，本期不真正调度执行命令或脚本。",
        constraints=("默认停用，须管理员启用", "必须配置 sandbox_policy", "workflow 名须符合白名单字符集"),
    ),
    BuiltinDef(
        "sys.http", "受控 HTTP 请求", "high", False, True,
        {"http_allow_hosts": [], "http_methods": ["GET"], "http_max_response_bytes": 65536},
        how="由 Agent 发起外呼 HTTP；主机须命中 Tool 沙箱或全局 runtime.http_allow_hosts；默认不跟随重定向，不带员工 Authorization。",
        constraints=("默认停用", "无沙箱策略则调用失败（SANDBOX_REQUIRED）", "响应体限字节；HTML 会做诱导内容清洗"),
    ),
    BuiltinDef(
        "sys.web_search", "网络搜索", "high", False, True, {"search_max_results": 5},
        how="调用已配置的搜索供应商 API；密钥只从 Vault 读取，不进入结果与错误信息。",
        constraints=("默认停用", "须有 sandbox_policy", "返回条数有上限"),
    ),
    BuiltinDef(
        "sys.fs_read", "沙箱内读文件", "high", False, True, {"fs_root": "sandbox", "fs_max_read_bytes": 65536},
        how="只读 data/sandbox/{tenant}/ 下相对路径；resolve 后复核仍在沙箱根内，禁止 .. 穿越。",
        constraints=("默认停用", "须有 sandbox_policy", "读取字节上限可配"),
    ),
    BuiltinDef(
        "sys.fs_write", "沙箱内写文件", "high", False, True, {"fs_root": "sandbox"},
        how="只写 data/sandbox/{tenant}/ 下相对路径；同样做路径规范化与沙箱根校验。",
        constraints=("默认停用", "须有 sandbox_policy", "写入体积有上限"),
    ),
]


_BY_ID = {d.builtin_id: d for d in BUILTIN_CATALOG}


def _p(label: str, description: str = "", *, required: bool = False, enum: tuple[str, ...] = ()) -> dict[str, Any]:
    rule: dict[str, Any] = {"type": "string", "label": label, "required": required}
    if description:
        rule["description"] = description
    if enum:
        rule["enum"] = list(enum)
    return rule


# 模型可填的参数（只放行这些键；身份字段永远由服务端注入）。结果统一为围栏文本，见 BUILTIN_RESULT_*。
BUILTIN_MODEL_PARAMS: dict[str, dict[str, dict[str, Any]]] = {
    "sys.time": {"timezone": _p("时区", "IANA 时区名，如 Asia/Shanghai；缺省为平台默认时区")},
    "sys.calc": {"expression": _p("表达式", "只支持数字与 + - * / // % ** 括号，如 (3+4)*2", required=True)},
    "sys.export": {"content": _p("内容", "要导出的文本", required=True), "filename": _p("文件名")},
    "sys.memory": {"action": _p("操作", "add 记住 / list 列出 / forget 忘记", enum=("add", "list", "forget")),
                   "text": _p("内容", "add 时为要记住的内容；forget 时为要忘记的内容关键字"),
                   "kind": _p("类别")},
    "sys.cron": {"action": _p("操作", "list / add / remove"), "workflow": _p("流程"), "cron": _p("cron 表达式"),
                 "job_id": _p("任务 ID")},
    "sys.http": {"url": _p("URL", required=True), "method": _p("方法")},
    "sys.web_search": {"query": _p("搜索词", required=True)},
    "sys.fs_read": {"path": _p("沙箱内路径", required=True)},
    "sys.fs_write": {"path": _p("沙箱内路径", required=True), "content": _p("内容", required=True)},
}

# builtin / mcp 的结果统一为 {"text": <围栏文本>}，回复层按 text 渲染，不走 office 的字段白名单
TEXT_RESULT_KIND = "text"
TEXT_RESULT_FIELDS = ("text",)


def builtin_model_params(builtin_id: str | None) -> dict[str, dict[str, Any]]:
    return {k: dict(v) for k, v in BUILTIN_MODEL_PARAMS.get(builtin_id or "", {}).items()}


def builtin_guide(builtin_id: str | None) -> dict[str, Any] | None:
    """管理端只读：内置工具实现说明（不参与运行时权限判定）。"""
    d = _BY_ID.get(builtin_id or "")
    if d is None:
        return None
    params = builtin_model_params(d.builtin_id)
    return {
        "kind": "builtin",
        "builtin_id": d.builtin_id,
        "summary": d.summary,
        "how": d.how,
        "constraints": list(d.constraints),
        "risk_level": d.risk_level,
        "default_enabled": d.enabled,
        "needs_sandbox": d.needs_sandbox,
        "default_sandbox_policy": dict(d.sandbox_policy),
        "model_params": params,
        "result": {
            "kind": TEXT_RESULT_KIND,
            "fields": list(TEXT_RESULT_FIELDS),
            "note": "执行结果统一围栏为文本块回图，不走 OA 接口字段白名单。",
        },
        "runtime": "BuiltinRuntime（进程内）",
        "edit_hint": "实现写在代码目录中，后台不能改路径/算法；可用启停与 Skill 绑定控制是否对员工开放。",
    }


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
