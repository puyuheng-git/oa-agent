# LLM 模型路由交付说明

**日期：** 2026-11-17  
**规格：** [`docs/superpowers/specs/2026-11-17-llm-model-routing-design.md`](../superpowers/specs/2026-11-17-llm-model-routing-design.md)  
**状态：** 已交付（代码未 commit，待用户验收）

## 目标

后台模型管理支持：全局默认模型、模型分类（`category` 文本/视觉等 + `tier` 大/小）、同池（category, tier）有序顺延（`max_failover`），并让路由阶段优先使用 `(text, small)` 池的小模型。

## 涉及文件

- `backend/oa_agent/db/models.py`：模型分类/池/默认设置的数据结构
- `backend/migrations/versions/0017_llm_model_routing.py`：迁移（含存量默认回填）
- `backend/oa_agent/runtime/llm.py`：`resolve_model` 路由与同池顺延
- `backend/oa_agent/admin/llm_api.py`：模型分类、池、`/defaults` 管理接口
- `backend/oa_agent/chat/service.py`：聊天路径接入 `resolve_model`、`_router_model` 选小模型
- `backend/oa_agent/runtime/graphs/oa_assistant.py`：配套调用（该文件另含与本特性无关的未提交改动）
- `frontend/src/admin/views/LlmView.vue`：默认★、分类、池排序、`max_failover`、不匹配警告
- `backend/tests/test_llm_routing.py`（新增）；`test_llm.py`、`test_prompt_guard.py` 小改

## 测试命令与结果

```bash
cd backend
uv run pytest tests/test_llm.py tests/test_llm_routing.py tests/test_migrations.py -v
# 41 passed
uv run pytest tests/test_agent_chat.py -v -k "llm or model" --maxfail=3
# 5 passed, 1 failed（见下，与路由无关）
cd ../frontend
npx vue-tsc --noEmit   # Task 5 记录：无错误
```

`test_agent_chat.py::test_chat_works_without_any_skill_when_model_available` 失败原因：种子写入 `agent_skill_pack` 时 SQLite 报 `NOT NULL constraint failed: agent_skill_pack.id`，属于工作区中其它未提交的 skill pack 改动，与模型路由无关，未处理。

## 已知限制（来自各任务评审）

- 流式回复时，若已推出部分内容后提供方报错并顺延，新候选会重新推流，可能出现重复片段。
- `_router_model` 行为变化：未配置 `router_model_id` 时取 `(text, small)` 池首选；无池仍回退主模型。
- 前端 `charts.spec.ts` 存在预先失败（`STATUS_HUE` 缺配色），与本特性无关。
- `test_next_turn_tool_action_reaches_call_tool` 受他人未提交的 `oa_assistant` bundle 改动影响，与选模无关。
- 全量 `pytest tests` 耗时 >7 分钟，未完整跑完。
- 池编辑为「单选 + 添加 + 上移/下移」，非拖拽；只读账号看不到 `max_failover`。
- 无 LlmView 组件测试，未做浏览器 E2E。

## 待用户验收

- 后台「模型管理」页：新增模型分类、设默认★、建池并排序、`max_failover` 保存后刷新保持、勾选「显示不匹配」警告、无 `sys.setting.edit` 时无操作入口。
- 路由阶段小模型行为：配置 `(text, small)` 池后，路由选用池首选，失败时按池序顺延。
