"""管理后台权限点目录（设计 §9）。新增权限点只追加；super_admin 自动拥有全部。"""

from __future__ import annotations

SUPER_ADMIN_ROLE = "super_admin"

PERMISSIONS: dict[str, str] = {
    "ops.run.view": "运行：总览/列表/详情（脱敏）",
    "ops.run.view_sensitive": "运行：完整对话记录与模型调用原文（访问即审计）",
    "ops.run.operate": "运行：取消/恢复/重试",
    "ops.intervention.handle": "人工介入处理",
    "ops.tool.manage": "Tool 同步/启停",
    "ops.skill.manage": "Skill 同步/启停",
    "ops.config.edit": "Workflow 配置编辑",
    "ops.config.publish": "Workflow 配置发布",
    "ops.config.rollback": "Workflow 配置回滚",
    "sys.setting.view": "查看连接与 LLM 配置",
    "sys.setting.edit": "修改连接与 LLM 配置（含密钥写入）",
    "sys.account.manage": "账号、角色、权限分配",
    "ops.audit.view": "审计查询",
    "ops.employee.view": "员工治理：目录与摘要",
    "ops.employee.sensitive": "员工治理：会话原文与记忆正文（访问即审计）",
    "ops.employee.manage": "员工治理：写操作",
    "ops.conversation.export": "对话记录导出（训练数据，导出即审计）",
}
