# 项目完成度与后续扩展

**更新日期：** 2026-10-28  
**权威设计：** [`design/2026-10-09-oa-langgraph-design.md`](design/2026-10-09-oa-langgraph-design.md)  
**冲突时以 `design/` 为准；** `history/` / `reference/` 仅供追溯。

---

## 1. 总览

| 层次 | 状态 | 说明 |
|------|------|------|
| 设计 P0–P6 骨架 | **已交付** | 见 [`delivery/2026-10-09-p3-p6-delivery.md`](delivery/2026-10-09-p3-p6-delivery.md)；真实 OA/MySQL/Redis/LLM 联调多为「外部依赖未验证」 |
| 平台子系统 E→C→A | **已交付** | 会话 / Skill 可见性 / 长期记忆 + 管理端员工治理 |
| O1–O6 纠偏 | **部分完成** | O1/O3 已上线；O2 写闭环 flag 默认关；O4/O6 部分；O5 仅骨架 |
| 出站 MCP + Builtin | **已交付（一期）** | 真 Client + 沙箱高风险默认关；真实 MCP/搜索联调未执行 |
| Tool 路由模式 + 调用过程 | **已交付** | 六模式可配置；管理端「调用过程」；embedding / 独立路由模型仍为扩展 |
| LLM 远端模型列表 | **已交付** | 提供方 `/models` 拉取 + 可搜索下拉；见规格 |
| 多系统可插拔平台 | **M1 已交付**（通向平台的部分能力） | 规格 [`multi-system-platform-design`](superpowers/specs/2026-10-28-multi-system-platform-design.md)；交付 [`multi-system-m1-delivery`](delivery/2026-10-28-multi-system-m1-delivery.md)；M2+ 未开 |

---

## 2. 已完成清单（可勾对交付）

| 项 | 规格 / 计划 | 交付说明 | 状态 |
|----|-------------|----------|------|
| P0–P6 核心能力 | 权威设计 §13 | [`2026-10-09-p3-p6-delivery`](delivery/2026-10-09-p3-p6-delivery.md) | ✅ |
| 前后端接线 | [`wiring-design`](superpowers/specs/2026-10-22-frontend-backend-wiring-design.md) | [`wiring-delivery`](delivery/2026-10-22-wiring-delivery.md) | ✅（C 类未做项已拆子系统） |
| E 历史会话 | [`chat-threads-design`](superpowers/specs/2026-10-23-chat-threads-design.md) | [`chat-threads-delivery`](delivery/2026-10-23-chat-threads-delivery.md) | ✅ |
| C Skill 可见性 | [`mcp-skill-visibility-design`](superpowers/specs/2026-10-23-mcp-skill-visibility-design.md) | [`mcp-skill-visibility-delivery`](delivery/2026-10-23-mcp-skill-visibility-delivery.md) | ✅ |
| A 长期记忆 | [`employee-memory-design`](superpowers/specs/2026-10-23-employee-memory-design.md) | [`employee-memory-delivery`](delivery/2026-10-23-employee-memory-delivery.md) | ✅（Profile 未做） |
| 管理端员工治理 | [`admin-employee-governance-design`](superpowers/specs/2026-10-23-admin-employee-governance-design.md) | [`admin-employee-governance-delivery`](delivery/2026-10-23-admin-employee-governance-delivery.md) | ✅ |
| O0–O6 纠偏 | [`remediation-o1-o6-design`](superpowers/specs/2026-10-26-remediation-o1-o6-design.md) | [`remediation-o1-o6-delivery`](delivery/2026-10-26-remediation-o1-o6-delivery.md) | 🔶 部分 |
| 出站 MCP / Builtin | [`mcp-builtin-tool-guard-design`](superpowers/specs/2026-10-27-mcp-builtin-tool-guard-design.md) | [`mcp-builtin-tool-guard-delivery`](delivery/2026-10-27-mcp-builtin-tool-guard-delivery.md) | ✅ 一期 |
| Tool 路由六模式 | [`tool-routing-modes-design`](superpowers/specs/2026-10-28-tool-routing-modes-design.md) | [`tool-routing-modes-delivery`](delivery/2026-10-28-tool-routing-modes-delivery.md) | ✅ |
| Auth 与上游解耦 | `.cursor/plans/auth与上游解耦_*.plan.md` | 设计 + schema/后台拆分 | ✅（OA 同 Passport 依赖现网） |
| LLM 远端模型列表 | [`llm-remote-models-design`](superpowers/specs/2026-10-28-llm-remote-models-design.md) | [`llm-remote-models-delivery`](delivery/2026-10-28-llm-remote-models-delivery.md) | ✅ |
| 多系统 M1 Principal/Connector | [`multi-system-platform-design`](superpowers/specs/2026-10-28-multi-system-platform-design.md) M1；计划 [`multi-system-m1-connectors`](superpowers/plans/2026-10-28-multi-system-m1-connectors.md) | [`multi-system-m1-delivery`](delivery/2026-10-28-multi-system-m1-delivery.md) | ✅（行为兼容；M2+ 未做） |

**清理（2026-10-28）：** 已删除 `scripts/` 下一批一次性修补/反编译临时脚本（`_*`），仅保留 `start.ps1` / `start.sh`。

---

## 3. 后续扩展（按推荐优先级）

### P0 — 可马上开发（本仓库可独立完成）

| ID | 项 | 来源 | 说明 |
|----|----|------|------|
| **X1** | `router_model_id` 独立路由模型接线 | 路由交付 §7 | ✅ 已接线（2026-10-28）：`stage=router` 用指定模型，`stage=fill` 用主模型 |
| **X2** | `retrieve_backend=embedding` 向量召回 | 路由交付 §7 | 索引与密钥走现有 LLM/Vault；未就绪须继续 keyword 降级 |
| **X3** | 管理端「调用过程」手工验收清单回填 | 路由交付 §8 | 两 Tab + 配置 enum + `meta_search` 真模型多轮 |
| **X4** | `test_catalog_admin` 失败归属澄清 | MCP 交付 §7 | ✅ 根因=缺 OA upstream；测试已修（见 x4-x6 交付） |

### P1 — 平台路线图未完（需决断或 OA 并行）

| ID | 项 | 子系统 | 说明 |
|----|----|--------|------|
| **X5** | 固定 Workflow 注册表 / 触发完善（D） | D / O2 | ✅ 注册表 + 员工 start API；写闭环仍依赖 OA MVP-3 / flag |
| **X6** | O5 L1 多 Agent 挂接主引擎 | B | ✅ `route_decision` + Skill 子集；默认仅 general，配置可加 finance |
| **X7** | TagProvider 真源（OA 标签） | C | 一期后台规则；OA 接口就绪后接 |
| **X8** | Profile 人事注入 | A | D8=C 仅预留；需 office-api 画像 |
| **X9** | Checkpointer 默认迁出 SQLite；企微 worker 租约 | O4 | 多实例前置 |

### P2 — 加固与联调（外部依赖）

| ID | 项 | 说明 |
|----|----|------|
| **X10** | 真 OA / office-api / LLM / 企微联调 | 交付中大量「外部依赖未验证」 |
| **X11** | 出站 MCP 真实 Server + 搜索供应商 | 含密钥后台入口、`sys.http` 私网拒绝名单 |
| **X12** | 对话保留策略管理 UI / 定时任务 | O6 部分 |
| **X13** | 高风险 builtin 安全评审后再开 | fs_write / cron 等 |

### 明确非目标（本期不排）

- 拖拽可视化编排 IDE  
- Agent 直连 `td_oa`  
- 用模型做权限判定  
- 标准 MCP 入站全家桶  
- 向量知识库作为主记忆  

---

## 4. 建议下一刀

X1 / X4 / X5 / X6 与 **多系统 M1** 已完成（见 [`x4-x6-delivery`](delivery/2026-10-28-x4-x6-delivery.md)、[`multi-system-m1-delivery`](delivery/2026-10-28-multi-system-m1-delivery.md)）。建议继续：

1. **多系统 M2**（envelope / identity_bindings 可配）— 待开计划  
2. **X2** embedding（需额外设计密钥与索引落点）  
3. **X3** 管理端「调用过程」手工验收 + Chat 写 Workflow 快捷按钮  
4. **X7–X9** TagProvider / Profile / Checkpointer 多实例；其后 M3–M5  

本文随交付更新；新交付报告须回写本表状态列。
