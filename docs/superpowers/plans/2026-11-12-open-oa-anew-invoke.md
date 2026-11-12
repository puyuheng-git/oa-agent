# open-oa ANew / Export 通用接入 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 open-oa 落地 mint + Export catalog + 通用 invoke；Service 为行程等 Export 挂 Agent 契约；Agent 改走 open-oa、导入启用 Tool，并强拆 office-api Agent 路径。

**Architecture:** Service `oa/agent_bridge` 维护可暴露方法注册表并执行白名单内 `ANew`；open-oa 仅做 HTTP 面（mint / catalog / invoke）；Agent 以 `kind=open_oa_invoke` Tool 调用 invoke，员工启用真相源仍在 Agent 后台。本期预留 catalog `extensions.mcp`，不实现 MCP Server。

**Tech Stack:** ThinkPHP（open-oa）、service-app PHP Export、FastAPI / SQLAlchemy / pytest（oa-langGraph）、现有 Tool Catalog。

**Spec:** `docs/superpowers/specs/2026-11-12-open-oa-anew-invoke-design.md`

## Global Constraints

- Agent 永不直接 `ANew` / 不访问 `td_oa`；只调 open-oa HTTP。
- 本链路文案与配置主称呼为 **open-oa** / `open_oa`，不再用 office-api 称呼该上游。
- invoke 只允许注册表内方法；身份只信员工 token；模型自报 `oa` 丢弃。
- 写：确认前不调用；确认后带 `Idempotency-Key`；Service 重校验。
- 本期强拆：下线 office-api 上 Agent mint/行程等对应路由；Agent 去掉对本链路 office-api 依赖。
- 回复与文档中文；代码标识符英文。
- 测试不得把未执行说成通过；真 open-oa / Service 联调标「外部依赖未验证」直至测通。
- Commit 仅在用户明确要求时执行；涉及三仓分别提交（见各 Task）。

**三仓路径：**

| 仓 | 根路径 |
|----|--------|
| Service | `D:\MYOA\webroot\puyueheng\service\service-app` |
| open-oa | `D:\MYOA\webroot\puyueheng\site\open-oa` |
| Agent | `E:\python_project\oa-langGraph` |

---

## File map

| 文件 | 职责 |
|------|------|
| `service-app/.../oa/agent_bridge/AgentExportRegistry.php` | 可暴露方法注册表（契约） |
| `service-app/.../oa/agent_bridge/Export.php` | `listAgentExports` / `invokeAgentExport` |
| `service-app/.../oa/agent_bridge/Error.php` | 业务错误码 |
| `service-app/.../out_attendance/go_out_application/Export.php` | 可选：薄封装 agent* 方法；或仅在 Registry 映射到现有方法 |
| `open-oa/app/controller/agent/Token.php` | mint（从 office-api 平替） |
| `open-oa/app/controller/agent/ExportBridge.php` | catalog + invoke |
| `open-oa/app/middleware/AuthAgentBearer.php` | Authorization → `oa/user::checkLogin` |
| `open-oa/route/app.php` + `config/user.php` | 路由与 mint 白名单 |
| `office-api/.../agent/Token.php` + 路由 | **删除/下线** Agent 相关 |
| `backend/oa_agent/integrations/open_oa.py` | 原 `office_api.py` 平替（mint + GET/POST） |
| `backend/oa_agent/executor/registry.py` | `kind=open_oa_invoke`；`invoke_service` / `invoke_method` |
| `backend/oa_agent/executor/executor.py` | 分派 invoke POST |
| `backend/oa_agent/executor/catalog.py` | schema 支持 invoke 字段 |
| `backend/oa_agent/admin/catalog_api.py` | `POST .../import/open-oa-catalog` |
| `backend/oa_agent/config/schema.py` | 文案改为 open-oa；默认上游 `open_oa` |
| `openapi/travel_expense.yaml` | 改为 invoke 形态或删除改由 catalog 导入 |
| `docs/ops/*.md` + `docs/STATUS.md` | 文案与状态回写 |

---

### Task 1: Service — Agent Export 注册表与 invoke（只读行程）

**Files:**
- Create: `D:\MYOA\webroot\puyueheng\service\service-app\src\service\oa\agent_bridge\AgentExportRegistry.php`
- Create: `D:\MYOA\webroot\puyueheng\service\service-app\src\service\oa\agent_bridge\Export.php`
- Create: `D:\MYOA\webroot\puyueheng\service\service-app\src\service\oa\agent_bridge\Error.php`
- Test: `D:\MYOA\webroot\puyueheng\service\service-app\src\service\oa\agent_bridge\_smoke_agent_bridge.php`（一次性冒烟，可删）

**Interfaces:**
- Produces ANew 名：`oa/agent_bridge`
- `Export::listAgentExports(): array` → 契约列表（见下）
- `Export::invokeAgentExport(string $service, string $method, array $args, array $identity): array`
  - `$identity` 至少含 `oa`（string）、`uid`（int，可选）
  - 成功返回业务 `data`（数组）；失败抛 `lib\exception\Exception` + Error 码
- Registry 条目形状：

```php
[
  'service' => 'out_attendance/go_out_application',
  'method'  => 'getTravelExpensePageList',
  'op'      => 'read',           // read|write
  'risk'    => 'low',            // low|medium|high
  'summary' => '分页查询本人行程报销单',
  'params'  => [
    ['name' => 'page', 'type' => 'integer', 'required' => false, 'label' => '页码'],
    ['name' => 'limit', 'type' => 'integer', 'required' => false, 'label' => '每页条数'],
    // date_gte / date_lte / status / ... 与现网 Tool 对齐
  ],
  'returns' => [
    'kind' => 'list',
    'fields' => ['id', 'date', 'client_name', 'total_amount', 'status', 'status_text', 'source', 'source_text', 'transport_types_desc', 'remark'],
    'list_columns' => ['id', 'date', 'client_name', 'total_amount', 'status_text'],
    'labels' => [/* 与 openapi/travel_expense.yaml 一致 */],
  ],
  'extensions' => ['mcp' => null],
]
```

- Error 码（示例，实现时写入 `Error.php` 常量）：`AGENT_EXPORT_NOT_FOUND`、`AGENT_EXPORT_FORBIDDEN_ARG`、`AGENT_EXPORT_WRITE_NEEDS_IDEMPOTENCY`（写留给 Task 7）

- [ ] **Step 1: 写注册表 + Export 骨架**

`AgentExportRegistry::all(): array` 静态返回上述行程 list + detail 两条（detail 映射 `getTravelExpenseOneByParams`）。

`Export::listAgentExports` 直接 `return AgentExportRegistry::all();`。

`Export::invokeAgentExport`：
1. 在 registry 查找 `(service, method)`，找不到 → `AGENT_EXPORT_NOT_FOUND`
2. 从 `$args` 去掉 `oa` / `authorization` / `token` / `uid`
3. 将 `$identity['oa']` **强制**写入业务 params（list 的筛选条件 / detail 的查询条件），禁止用模型传入的他人 oa
4. `ANew($service)->{$method}(...)` —— 参数绑定按 registry 约定：list 用 `($params, $page, $limit)`；detail 用 `([$params])` 与现 Export 签名一致
5. 返回归一化 `data`（list：`{list, total}`；detail：单对象）

- [ ] **Step 2: 本地冒烟**

```php
// _smoke_agent_bridge.php — 在可加载 service 的环境执行
$svc = ANew('oa/agent_bridge');
$cat = $svc->listAgentExports();
assert(count($cat) >= 2);
$identity = ['oa' => '<测试账号>', 'uid' => 0];
$data = $svc->invokeAgentExport(
  'out_attendance/go_out_application',
  'getTravelExpensePageList',
  ['page' => 1, 'limit' => 5],
  $identity
);
assert(isset($data['list']) || is_array($data));
echo "OK\n";
```

Run: 按现网 service 冒烟方式执行该脚本  
Expected: 打印 `OK`；伪造未注册 method 应抛错

- [ ] **Step 3: Commit（仅当用户要求）**

```bash
# 在 service-app 仓库
git add src/service/oa/agent_bridge
git commit -m "feat(agent_bridge): Export 注册表与只读行程 invoke"
```

---

### Task 2: open-oa — mint 平替

**Files:**
- Create: `D:\MYOA\webroot\puyueheng\site\open-oa\app\controller\agent\Token.php`
- Modify: `D:\MYOA\webroot\puyueheng\site\open-oa\route\app.php`
- Modify: `D:\MYOA\webroot\puyueheng\site\open-oa\config\user.php`（`login_white_urls` 增加 `/agent/token/mint`）
- Reference（只读复制逻辑）: `D:\MYOA\webroot\puyueheng\site\office-api\app\controller\agent\Token.php`

**Interfaces:**
- `POST /agent/token/mint`（form：`oa` | `wework_user_id` 二选一 + `gateway_secret`）
- 成功：`{code:0, msg, data:{authorization, uid, oa, display_name?, expire}}`
- 行为与 office-api 现网 Token::mint 一致（含 `AGENT_MINT_ALLOW_IPS`）

- [ ] **Step 1: 增加控制器与路由**

从 office-api `Token.php` 复制到 open-oa（namespace `app\controller\agent`），保留 `ANew('oa/user')->agentMintOfficeToken*` 调用。

路由：

```php
Route::post('agent/token/mint', 'agent.Token/mint');
```

白名单：`config/user.php` → `login_white_urls` 追加 `'/agent/token/mint'`。

- [ ] **Step 2: 冒烟 mint**

```bash
curl -s -X POST "$OPEN_OA_BASE/agent/token/mint" \
  -d "oa=<测试账号>&gateway_secret=$AGENT_GATEWAY_SECRET"
```

Expected: JSON `code` 成功；`data.authorization` 非空；错误密钥失败

- [ ] **Step 3: Commit（仅当用户要求）**

```bash
git commit -m "feat(agent): open-oa 平替 mint 入口"
```

---

### Task 3: open-oa — catalog + invoke + Bearer 鉴权

**Files:**
- Create: `open-oa/app/middleware/AuthAgentBearer.php`
- Create: `open-oa/app/controller/agent/ExportBridge.php`
- Modify: `open-oa/route/app.php`
- Modify: `open-oa/config/user.php`（catalog/invoke **不要**进 login 白名单；走 Bearer）

**Interfaces:**
- `GET /agent/export-catalog` — Header `Authorization`；返回 `{code, data: {items: [...]}}`，items = `listAgentExports()`
- `POST /agent/invoke` — Header `Authorization`；JSON body：

```json
{
  "service": "out_attendance/go_out_application",
  "method": "getTravelExpensePageList",
  "args": { "page": 1, "limit": 10 }
}
```

写操作另需 Header `Idempotency-Key`（Task 7 强制；本期 read 可忽略）。

- `AuthAgentBearer`：读 `Authorization` → `ANew('oa/user')->checkLogin($authorization, true, $fields)` → 注入 request 属性 `agent_oa` / `agent_uid`；失败 401

- [ ] **Step 1: 实现 AuthAgentBearer**

参考 office-api `AuthUser.php` 中 Authorization 分支；失败返回 JSON 401，**不要** redirect `/login`。

- [ ] **Step 2: 实现 ExportBridge**

```php
public function catalog() {
  $items = ANew('oa/agent_bridge')->listAgentExports();
  return $this->suc(['items' => $items]);
}

public function invoke() {
  $service = trim((string)$this->request->post('service', ''));
  // 若 Content-Type JSON，从 json 取 service/method/args
  $method = ...;
  $args = ...; // array
  $identity = [
    'oa' => (string)$this->request->agent_oa,
    'uid' => (int)$this->request->agent_uid,
  ];
  $data = ANew('oa/agent_bridge')->invokeAgentExport($service, $method, $args, $identity);
  return $this->suc($data);
}
```

路由组挂 `AuthAgentBearer`：

```php
Route::group('agent', function () {
  Route::get('export-catalog', 'agent.ExportBridge/catalog');
  Route::post('invoke', 'agent.ExportBridge/invoke');
})->middleware(AuthAgentBearer::class);
```

- [ ] **Step 3: 冒烟**

```bash
# 先 mint 拿 token，再：
curl -s -H "Authorization: $TOKEN" "$OPEN_OA_BASE/agent/export-catalog"
curl -s -X POST -H "Authorization: $TOKEN" -H "Content-Type: application/json" \
  -d '{"service":"out_attendance/go_out_application","method":"getTravelExpensePageList","args":{"page":1,"limit":5}}' \
  "$OPEN_OA_BASE/agent/invoke"
```

Expected: catalog 含行程两条；invoke 返回列表 data；无 token → 401；假 method → 业务错误

- [ ] **Step 4: Commit（仅当用户要求）**

```bash
git commit -m "feat(agent): open-oa catalog 与通用 invoke"
```

---

### Task 4: Agent — `open_oa` 客户端与默认上游

**Files:**
- Create: `backend/oa_agent/integrations/open_oa.py`（由 `office_api.py` 复制演进）
- Modify: 所有 `from oa_agent.integrations.office_api import ...` 改为 `open_oa`（可用 git grep 列出）
- Modify: `backend/oa_agent/config/schema.py`（文案 open-oa；`default_upstream_key` 默认 `open_oa`）
- Keep: `office_api.py` 可暂留薄 re-export 一版以免漏改，但公开注释标明 deprecated → 下一 Task 删除
- Test: `backend/tests/test_open_oa_client.py`（新建，迁自 office 客户端测试要点）

**Interfaces:**
- `DEFAULT_UPSTREAM = "open_oa"`
- `MINT_PATH = "/agent/token/mint"`
- `OpenOaClient`：保留 `mint` / `mint_by_wework` / `get`；**新增** `post(path, json_body, authorization, *, headers=None, timeout=...)`
- 错误类可仍名 `OpenOaError`（或保留 `OfficeApiError` 别名一期，文案改 open-oa）
- 员工配置文案：`office_api_not_configured` key 可保留兼容，**展示文案**改为「助手尚未配置 open-oa」

- [ ] **Step 1: 写失败测试（POST）**

```python
# backend/tests/test_open_oa_client.py
import httpx
from oa_agent.integrations.open_oa import OpenOaClient

def test_post_json_success(httpx_mock):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path.endswith("/agent/invoke")
        return httpx.Response(200, json={"code": 0, "msg": "ok", "data": {"list": [], "total": 0}})

    transport = httpx.MockTransport(handler)
    c = OpenOaClient("http://open-oa.test", transport=transport)
    resp = c.post("/agent/invoke", {"service": "a", "method": "b", "args": {}}, "Bearer t")
    assert resp.data == {"list": [], "total": 0}
```

Run: `cd backend && uv run pytest tests/test_open_oa_client.py::test_post_json_success -v`  
Expected: FAIL（模块/方法不存在）

- [ ] **Step 2: 实现 `open_oa.py` + 最小 import 切换（chat/service、executor、wecom、identity）**

`post` 实现对照现有 `get`：同一信封解析、`business_hint`、错误码映射。

- [ ] **Step 3: 跑测试**

Run: `cd backend && uv run pytest tests/test_open_oa_client.py tests/test_demo_no_oa_m4.py -v`  
Expected: PASS（demo 仍可不依赖 open-oa base）

- [ ] **Step 4: Commit（仅当用户要求）**

```bash
git commit -m "feat(integrations): open_oa 客户端与 POST invoke"
```

---

### Task 5: Agent — `open_oa_invoke` Tool 形态与 Executor

**Files:**
- Modify: `backend/oa_agent/executor/registry.py`（`ToolSpec` 增字段）
- Modify: `backend/oa_agent/executor/catalog.py`（规范化 / `to_tool_spec`）
- Modify: `backend/oa_agent/executor/executor.py`（分派）
- Modify: `backend/oa_agent/connectors/http_json.py`（若走 hub，确保 POST JSON body）
- Test: `backend/tests/test_open_oa_invoke_executor.py`

**Interfaces:**
- `ToolSpec.kind` 增加 `"open_oa_invoke"`
- `ToolSpec.invoke_service: str = ""`
- `ToolSpec.invoke_method: str = ""`
- 运行时注册：`kind=open_oa_invoke` 且启用、低风险免确认可读，或 write 走确认链
- Executor：当 `kind == "open_oa_invoke"`：

```python
body = {
  "service": spec.invoke_service,
  "method": spec.invoke_method,
  "args": clean,  # 已 validate，无身份字段
}
headers = {}
if spec.risk_level != "low" or /* op write */ False:
    headers["Idempotency-Key"] = ...  # Task 7；read 不传
client.post("/agent/invoke", body, auth, headers=headers, timeout=spec.timeout_seconds)
```

- schema 规范化：`method` 固定存 `POST`，`path` 固定 `/agent/invoke`；`upstream` 默认 `open_oa`

- [ ] **Step 1: 失败测试**

```python
def test_execute_open_oa_invoke_posts_service_method(runtime_harness):
    # 注册一条 kind=open_oa_invoke 的 ToolSpec
    # mock OpenOaClient.post 断言 body.service/method，返回 list
    # execute(...) → ok 且 data 裁剪后含 list
    ...
```

Run: `uv run pytest tests/test_open_oa_invoke_executor.py -v`  
Expected: FAIL

- [ ] **Step 2: 实现 registry/catalog/executor 最小通路**

- [ ] **Step 3: 测试 PASS**

- [ ] **Step 4: Commit（仅当用户要求）**

```bash
git commit -m "feat(executor): open_oa_invoke 分派 POST /agent/invoke"
```

---

### Task 6: Agent — 管理端从 open-oa catalog 导入

**Files:**
- Modify: `backend/oa_agent/admin/catalog_api.py`
- Modify: `frontend/src/admin` Tool 管理页（增加「从 open-oa 清单导入」按钮与勾选 UI；若一期求快：仅 API + 简单多选对话框）
- Test: `backend/tests/test_open_oa_catalog_import.py`

**Interfaces:**
- `POST /v1/admin/tools/import/open-oa-catalog`
  - 权限：`ops.tool.manage` + CSRF + Idempotency-Key
  - Body：`{ "names": ["out_attendance/go_out_application.getTravelExpensePageList", ...] }`  
    或 `{ "items": [ { "service", "method" }, ...] }`
  - 行为：服务端用 **mint_base_url / 默认 open_oa upstream** 调 `GET /agent/export-catalog`（可用网关密钥 mint 临时票，或配置只读拉取用的服务账号——**一期用 gateway mint 测试账号不可行**时：允许管理端传入已配置 upstream，用「系统配置的探测」：catalog 接口若需员工票，则增加 open-oa **可选** `X-Agent-Gateway-Secret` 只读拉清单；**推荐实现**：catalog 对 gateway_secret 或 Bearer 二选一，管理导入走 secret，员工 invoke 走 Bearer）
  - 将命中条目转为 Tool 草稿/版本（`kind=open_oa_invoke`，填 `invoke_service/method`、`model_params`、`result_*`、`risk`）；**不自动启用**除非已有同名兼容更新规则与现网一致
  - 审计：`tool.import_open_oa_catalog`

**Catalog 鉴权补充（open-oa，本 Task 一并改）：**

- `GET /agent/export-catalog` 允许：有效 Bearer **或** 校验通过的 `gateway_secret`（仅 list，不可 invoke）

- [ ] **Step 1: open-oa catalog 支持 gateway_secret 只读**

- [ ] **Step 2: Agent 失败测试（mock httpx 返回 items → 生成 schema）**

- [ ] **Step 3: 实现 API + 最小前端勾选**

- [ ] **Step 4: 测试 PASS；手工：后台导入行程两条，状态为已注册/待启用符合版本规则**

- [ ] **Step 5: Commit（仅当用户要求）**

```bash
git commit -m "feat(admin): 从 open-oa export-catalog 导入 Tool"
```

---

### Task 7: 行程切换 + 写确认样例 + office-api 强拆

**Files:**
- Modify/Replace: `openapi/travel_expense.yaml`（改为 invoke 描述或标注废弃改由 catalog）
- Modify: `skills/` 行程 Skill（若仍文件导入）
- Modify: Service Registry — 增加至少 1 个 **write** 样例（若本期有明确写方法；否则用 `saveOrUpdateTravelExpense` 且 `risk=high` **默认 Agent 不启用**，仅打通确认链测试用 fixture）
- Modify: Agent 确认写路径（现有 workflow / confirmation）使 `open_oa_invoke` + write 走同一确认
- Delete/Disable: office-api `app/controller/agent/Token.php` 路由与 `noneedverifylogin` 中 mint；行程 Agent 专用若有则下线
- Modify: Agent 删除对 `office_api.py` 的残留引用；文档 `docs/ops/user-guide.md`、`integrate-external-system.md`、`demo-idp.md`、`docs/STATUS.md`
- Test: `backend/tests/test_travel_expense_read_harness.py` 改为 mock invoke；新增写确认单测

**Interfaces:**
- 读：启用后的 `query_my_travel_expense_list/detail`（名可保持）→ `open_oa_invoke`
- 写：确认后 `POST /agent/invoke` + `Idempotency-Key`；Service `invokeAgentExport` 对 `op=write` 无 key 则 `AGENT_EXPORT_WRITE_NEEDS_IDEMPOTENCY`；有 key 则 `DuplicateSubmit::assert`（或现网等价）
- office-api：Agent mint 路由移除；返回 404 或明确下线

- [ ] **Step 1: Registry 为 write 强制 Idempotency-Key；open-oa invoke 透传 Header 到 Service**

- [ ] **Step 2: 改行程 harness / 单测走 invoke**

- [ ] **Step 3: 强拆 office-api Agent mint；Agent 配置说明改为只填 open-oa**

- [ ] **Step 4: 联调清单（外部依赖）**

- [ ] mint 仅 open-oa 成功；office-api mint 已失效  
- [ ] catalog 导入 → 启用 → 对话查行程  
- [ ] 篡改 args.oa 无效  
- [ ] 写：未确认无请求；确认后幂等  

- [ ] **Step 5: 回写 STATUS 与 ops 文档**

- [ ] **Step 6: Commit（仅当用户要求）**

```bash
# Agent
git commit -m "feat(travel): 行程改走 open-oa invoke 并强拆 office-api Agent 面"
# office-api / open-oa / service 各自提交对应强拆与写路径
```

---

### Task 8: 交付记录

**Files:**
- Create: `docs/delivery/2026-11-12-open-oa-anew-invoke-delivery.md`
- Modify: `docs/STATUS.md`（增一行本能力状态）

- [ ] **Step 1: 按交付模板写清：已测 / 外部依赖未验证 / 强拆范围**

- [ ] **Step 2: Commit（仅当用户要求）**

```bash
git commit -m "docs(delivery): open-oa ANew invoke 交付说明"
```

---

## Spec coverage（自检）

| 规格要点 | Task |
|----------|------|
| D3 通用 invoke | 1, 3, 5 |
| D5 catalog + 勾选导入 | 3, 6 |
| D7/D8 open-oa + mint | 2, 4 |
| D9 行程 ANew | 1, 7 |
| D10 强拆 office-api | 7 |
| 写确认 + 幂等 | 7 |
| 预留 MCP 字段 | 1（extensions.mcp） |
| 身份注入 / 丢弃自报 oa | 1, 5 |
| 文档与 STATUS | 7, 8 |

## Placeholder scan

无 TBD；catalog 管理端鉴权在 Task 6 已选定「gateway_secret 或 Bearer」。写样例方法若现网不宜暴露，Task 7 可用 high+默认不启用的 fixture，不阻塞读路径交付。
