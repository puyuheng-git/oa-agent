# Task 3 Extra 范围说明（commit `c6820a5`）

| 项 | 内容 |
|----|------|
| Commit | `c6820a5678851c96a967dbe7934fda78a9af1db4` |
| 消息 | `feat: prompt_guard skeleton for user and memory text` |
| 计划 | `docs/superpowers/plans/2026-10-27-mcp-builtin-tool-guard.md` → Task 3 |
| 审查 | Quality = Changes requested（Important: **Extra**） |

## 摘要

Task 3 目标是 `prompt_guard` 骨架，并接入**长期记忆过滤**与 **oa_assistant 用户消息**。提交 `c6820a5` 除上述接线外，还**首次纳入**整文件 `oa_assistant.py`（约 974 行）及整文件 `memory_guard.py`（17 行），二者在 `c6820a5^` 中**不在 Git 中**（本地未跟踪 WIP）。后续任务**不得**把完整 `oa_assistant` 图实现视为「Task 3 交付物」或 Task 3 独占改动。

## 为何必须整文件打包

1. 计划要求 **Modify** `runtime/graphs/oa_assistant.py`，在 understand 组提示处调用 `prepare_user_text` / 历史员工句 `normalize_text`。
2. 该路径在提交前**从未进过版本库**；不存在「只提交几个 hunk」的基线分支。
3. 不附带整文件则无法在 CI/他人克隆上运行 understand 接线测试（`test_prompt_guard` 等）或跑通依赖 `oa_assistant` 工作流的用例。
4. 因此审查认定的 **Extra** 是**前序未提交 WIP 与 Task 3 最小接线捆在同一 commit**，而非 Task 3 规格要求新建整图。

## `c6820a5` 文件清单：Core Task 3 vs Extra

| 文件 | 归类 | 说明 |
|------|------|------|
| `backend/oa_agent/security/__init__.py` | **Core** | 包初始化（+1 行） |
| `backend/oa_agent/security/prompt_guard.py` | **Core** | Task 3 新建模块：`normalize_text`、`wrap_untrusted`、`scan_flags`、`prepare_user_text`、`prepare_memory_text` 等 |
| `backend/oa_agent/chat/memory_guard.py` | **Core** | Task 3 计划内：`is_blocked_memory_text` 委托 `scan_flags`（整文件 17 行；提交前同样未跟踪，但内容即本任务记忆侧接入） |
| `backend/tests/test_prompt_guard.py` | **Core** | Task 3 新建测试 |
| `backend/tests/test_chat.py` | **Core（附带）** | 用户 human 消息经围栏后更新断言（1 hunk） |
| `backend/tests/test_conversations.py` | **Core（附带）** | 同上 |
| `backend/tests/test_chat_threads.py` | **Core（附带）** | 同上 |
| `backend/tests/test_agent_chat.py` | **Core（附带）** | 同上 |
| `backend/tests/test_agent_advanced.py` | **Core（附带）** | 同上 |
| `backend/oa_agent/runtime/graphs/oa_assistant.py` | **Core（接线）+ Extra（主体）** | 见下节 |

### `oa_assistant.py` 内 Task 3 实际改动（Core 子集）

仅下列语义属于 Task 3；其余约 **960+ 行**为此前本地 WIP（OA 助手整图：understand / call_tool / respond / remember、多步引用、chain_plan、tool_select、记忆压缩、handoff 等），归属**前序/并行任务**，**不**算 Task 3 规格交付：

- `from oa_agent.security.prompt_guard import normalize_text, prepare_user_text`
- `USER_FENCE_NOTE` 及 understand 的 system 提示追加说明
- 当前用户句：`("human", prepare_user_text(state["message"]))`
- 历史中带往模型的**员工原话**：`normalize_text(content)`（助手摘要不改写）

JSON 选 tool 协议、规则回退仍用原始 `message` 等行为按 Task 3 报告，未因整文件首次入库而改变意图。

## 对后续任务的约定

- **Do not** 在 Task 4+ 的交付说明里写「Task 3 实现了 oa_assistant 全图」。
- **Do** 将 `oa_assistant.py` 的大块逻辑归因到其真实功能线（如多 Agent、链式查询、写工作流等），Task 3 只认领 `prompt_guard` 接线。
- 若需拆分历史：应用**新 commit 前移 WIP** 或文档标注（本文件即审查要求的文档 fix）；**不要**改写 `c6820a5` 历史。
- 围栏深化（Executor 结果、sys.http、`scrub_html` 等）属计划 **Task 12**，不属于 Task 3 Core。
