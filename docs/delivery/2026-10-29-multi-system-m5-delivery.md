# 交付说明：多系统平台 M5 — 产品化收官

**日期：** 2026-10-29  
**规格：** `docs/superpowers/specs/2026-10-28-multi-system-platform-design.md`（M5）  
**计划：** `docs/superpowers/plans/2026-10-29-multi-system-m5-productize.md`  
**前置：** M1–M4 已交付

---

## 1. 功能

1. **领域包管理：** 新增 `PacksView`，展示包标识、名称、版本、启用状态、连接器与校验错误；支持带原因启停，空态显示「暂无数据」。
2. **产品文案去 OA 中心化：** 设置、Tool 表单和使用说明改用「连接器 / 业务上游」叙事；兼容配置 key `oa` 与 Python 包名 `oa_agent` 不变。
3. **连接器总览：** 新增只读 `GET /v1/admin/connectors`，聚合 HTTP 上游、MCP 与 builtin；Settings 顶部卡片展示配置状态。
4. **调用过程维度：** `RoutingView` 展示事件真实存在的 `connector_id` / `pack_id`，缺失时显示「—」，不推断或伪造。
5. **接入手册与演示说明：** 新增《新系统接入》与 demo IdP / `demo_http` 说明，并接入文档索引。
6. **渠道到 IdP 映射：** 新增字符串配置 `idp.channel_idp_map_json`；Broker 支持解析与非法 JSON 回落默认映射。

**验收口径：** 有稳定 HTTP JSON API 时，按手册可在一个工作日内完成 Agent 侧接入（不含对方改接口）。

---

## 2. 文件清单

- 前端：`frontend/src/admin/packs.ts`、`views/PacksView.vue`、`router.ts`、`views/SettingsView.vue`、`views/RoutingView.vue`、`routing.ts`、Tool/catalog 文案及对应测试。
- 后端：`backend/oa_agent/admin/connectors_api.py`、`main.py`、`config/schema.py`、`identity/broker.py`、连接器权限与 catalog 展示文案及对应测试。
- Pack / 文档：`packs/demo_http/README.md`、`docs/ops/integrate-external-system.md`、`docs/ops/demo-idp.md`、`docs/ops/user-guide.md`、`docs/README.md`。

---

## 3. 迁移说明

无数据库迁移。`oa` 配置组 key、现网 office 上游与 `oa_travel` 默认启用行为保持不变。新增 `channel_idp_map_json` 默认映射为 `oa_web→oa_assertion`、`wecom→wecom`、`demo→demo`；非法 JSON 安全回落默认值。

---

## 4. API 说明

- `GET /v1/admin/connectors`：需 `sys.setting.view` 或 `ops.tool.manage`；返回 `{items: [{id, kind, label, envelope_profile?, health}]}`，`health` 仅表示 `configured|missing`，不伪装真实健康探测。
- 领域包沿用 M3 `GET /v1/admin/packs` 与启停 API；管理写继续经 CSRF、`Idempotency-Key` 与审计链。
- `idp.channel_idp_map_json` 已可配置，Broker 的 `verify_channel` 可显式使用；但运行时入口尚未统一调用该方法，因此修改映射暂不影响现网 OA / 企微 launch。
- M5 终审 I1 已修：领域包启停增加 `packs.enabled_ids` 显式启用覆盖；`default_enabled: false` 的包经启用 API 后重载仍保持启用，`disabled_ids` 优先级最高。

---

## 5. 权限与安全

- 对 `td_oa` 零访问；业务数据仍只来自员工凭证可访问的 HTTP 上游。
- Tool 仅保存上游标识与相对路径；模型输出不参与身份、权限或健康状态判定。
- 连接器总览读取公开配置视图，不解密密钥；密钥仍只写不读。
- Pack 启停写操作沿用权限 + CSRF + 幂等键 + 审计，审计失败则操作失败。

---

## 6. 测试结果

### 自动化通过

- 后端：`cd backend && uv run pytest -q --tb=line` — **564 passed，1 skipped，0 failed**（565 collected）。
- 前端：`cd frontend && npm run test` — **18 files passed，98 tests passed，0 failed**。
- 类型检查：`cd frontend && npx vue-tsc --noEmit` — **通过，0 errors**。

### 手工未执行

- 管理端领域包启停、连接器卡片、调用过程列的浏览器手工 UI 验收未执行。
- 真 OA / 真企微入口与员工端完整对话未手工回归。

### 外部依赖未验证

- 真实 office-api、外部 HTTP JSON API、MCP Server、LLM、企微与 OIDC 提供方均未联调。

---

## 7. 未完成项

- OIDC 仍仅骨架，未做真实授权码流联调。
- I2 未完成：运行时入口尚未统一走 `IdentityBroker.verify_channel`；`channel_idp_map_json` 当前为预留配置，修改它暂不影响现网 OA / 企微 launch。
- UI 手工验收未执行。

---

## 8. 收官与下一阶段

多系统平台 **M0–M5 产品化完成并收官**。下一刀不再是 M5；后续按 `docs/STATUS.md` 增量推进 OIDC 真联调、X2 embedding、X3 UI 手工验收与 X7–X9 平台加固。
