# 交付说明：LLM 按提供方拉取远端模型列表

**日期：** 2026-10-28  
**规格：** `docs/superpowers/specs/2026-10-28-llm-remote-models-design.md`  
**权威设计：** `docs/design/2026-10-09-oa-langgraph-design.md` §9 / §12  

---

## 1. 功能

1. `GET /v1/admin/llm/providers/{id}/remote-models`：服务端用 vault 解密 Key 后请求 OpenAI 兼容 `GET {base_url}/models`，返回模型 ID 列表（截断 200，带 `truncated`）。  
2. 无 Key / 远端失败 → `ok: false` + 脱敏错误；提供方不存在 404；无 `sys.setting.view` → 403。  
3. 管理端 LLM 页新增/编辑模型：`model_name` 可搜索下拉 + 允许手填；打开对话框/切换提供方/点刷新时拉取；失败不阻塞保存。  

---

## 2. 文件清单

| 路径 | 说明 |
|------|------|
| `backend/oa_agent/integrations/llm_check.py` | `check_provider` 支持 `limit`；返回全量计数与截断列表 |
| `backend/oa_agent/admin/llm_api.py` | `remote-models` 只读接口 |
| `backend/tests/test_llm.py` | 列表 / 截断 / 无 Key / 脱敏 / 404 / 403 |
| `frontend/src/admin/views/LlmView.vue` | 可搜索下拉 + 刷新 |
| `docs/design/2026-10-09-oa-langgraph-design.md` | API 表增补 |
| `docs/delivery/2026-10-28-llm-remote-models-delivery.md` | 本文 |

无 Alembic 迁移。

---

## 3. 迁移说明

无。

---

## 4. API 说明

| 方法 | 路径 | 权限 | 说明 |
|------|------|------|------|
| GET | `/v1/admin/llm/providers/{provider_id}/remote-models` | `sys.setting.view` | 只读探测；**不写审计** |

---

## 5. 权限与安全

- 密钥只写不读：响应与错误经 `redact()`，不含明文 Key。  
- 列表失败不阻塞模型 CRUD。  

---

## 6. 测试结果

| 项 | 结果 |
|----|------|
| `tests/test_llm.py` remote-models 相关（mock `/models`） | **自动化通过**（随本功能提交） |
| 真实提供方拉取 | **外部依赖未验证** |
| 管理端手工点选下拉 | **未执行** |

---

## 7. 未完成项

- 非 OpenAI 兼容协议、静态内置 catalog、批量导入。  
- 流程配置里的模型下拉暂不改数据源。  

---

## 8. 下一阶段建议

见 [`docs/STATUS.md`](../STATUS.md) **X1**（`router_model_id`）起。
