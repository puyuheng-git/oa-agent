# Demo IdP（本地 / 演示）

**用途：** 在无 OA 宿主页、无 office-api 配置时，验证 Identity Broker、多 connector 凭证与 `raw_json` Tool 执行链。  
**禁止：** 生产环境开启；不得替代 OA assertion 或企微身份。

## 配置

管理后台 → **连接配置** → 组 **IdP**：

| 字段 | 说明 |
|------|------|
| `demo_idp_enabled` | 默认 **False**；仅本机或隔离演示环境设为 True |
| `demo_shared_secret` | 本地共享口令（明文存配置，仅限本机）；保存后界面只显示掩码 |

## 行为摘要

- IdP 标识：`demo`；校验 payload 需 `principal_id` + `secret`（与共享口令一致）。
- 成功后会话 `channel=demo`，`credentials["demo"]` 含 `authorization`（默认 `Bearer demo-token`），**无** `office` 票。
- 与 **`demo_http`** Pack（`connectors: [demo]`）配合，用于证明「零 OA」路径；Pack 说明见 [`packs/demo_http/README.md`](../../packs/demo_http/README.md)。

## 完整接入

Demo 只解决「谁在用助手」；业务接口仍需配置上游、Tool/Skill 或 Pack。步骤见 **[新系统接入手册](integrate-external-system.md)**。
