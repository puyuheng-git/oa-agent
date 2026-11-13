# Agent Skill 包 / 沙箱执行 / 租户市场 — 交付说明

**日期：** 2026-11-13  
**范围：** P1–P3（模型、沙箱、GitHub 导入、对话页 Skill 管理、租户市场）

## 能力摘要

- 新增与目录 Skill（`skills/*.yaml` + Tool）并行的 **Agent Skill 包**（`SKILL.md` + scripts）。
- 管理后台 **Skill 包** 页：从 GitHub 导入系统包（如 `anthropics/skills` 下 xlsx/pdf/docx/pptx）。
- 内置工具 `builtin.skill_exec`：在服务器沙箱跑包内 python/node 脚本。
- 对话页原「工作空间」改为 **Skill 管理**：我的库启停/自建、市场热门安装与上架。
- 存放一律在服务器（库表 + `data/skill_packs/`）；脚本只在后端执行。

## 迁移

- Alembic：`0014_skill_packs`

## 主要 API

| 方法 | 路径 | 说明 |
|------|------|------|
| GET/POST | `/v1/admin/skill-packs` / `.../import/github` | 管理端列表与导入 |
| GET/POST/PUT/PATCH/DELETE | `/v1/chat/skill-packs` | 员工个人库 |
| GET/POST | `/v1/chat/skill-market` / `.../install` | 租户市场 |

## 验收要点

1. 迁移后管理端导入 GitHub Office Skills，对话会话 `skill_packs` 可见。
2. 员工关闭某包后，后续对话不再注入该包。
3. 调用 `builtin.skill_exec` 成功则 `invoke_count` 增加；市场按调用量排序。
4. 自建包推到市场后，其他员工可「添加到我的」。
