# Agent Export 向导（替代 catalog 导入）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 用「填 a/b/c → 反射列 Export public 方法 → 配参 → 指定测试员工测通 → 入 Tool」替换 Registry / export-catalog / 清单导入；`/agent/invoke` 升级为员工 Bearer + 网关密钥，且不影响业务侧普通 `ANew`。

**Architecture:** Service `ExportInspector` 只做反射发现；`oa/agent_bridge` 按请求中的 `call` 绑定并强制注入员工 `oa`（无注册表）。open-oa 提供 discover/describe/probe，invoke 双鉴权。Agent 管理端向导落库 `open_oa_invoke`；运行时执行器写死 service/method/call 并附带网关密钥。

**Tech Stack:** ThinkPHP 6 / PHP 7.2+（service-app、open-oa）；FastAPI / Vue3 / pytest（oa-langGraph）。

**Spec:** `docs/superpowers/specs/2026-11-16-agent-export-wizard-design.md`

## Global Constraints

- 普通业务 `ANew(...)` **零改动**；双鉴权与 Inspector **只**挂在 open-oa `/agent/*`。
- 产品白名单 = Agent 已启用 Tool；**删除** `AgentExportRegistry` / `export-catalog` / 清单导入 UI+API。
- `POST /agent/invoke` = 员工 Bearer **且** `X-Agent-Gateway-Secret`；模型不可改 service/method/call。
- probe 使用 body 中的测试员工 `oa`；未测通不落库；入库前 `result.fields` 按 kind 必填。
- 回复与文档中文；代码标识符英文；PHP 遵守项目 call-args / 注释规范。
- Commit 仅在用户明确要求时执行；三仓分别提交。
- 测试不得把未执行说成通过；真 open-oa/Service 联调标「外部依赖未验证」直至测通。

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
| `service-app/.../oa/agent_bridge/ExportInspector.php` | **新建** `listPublicMethods` / `describeMethod` |
| `service-app/.../oa/agent_bridge/Export.php` | 改：discover 委托 Inspector；`invokeAgentExport` 无 Registry，按 `call` 绑定 |
| `service-app/.../oa/agent_bridge/AgentExportRegistry.php` | **删除** |
| `service-app/.../oa/agent_bridge/Error.php` | 文案：NOT_FOUND=方法不存在；可增 `AGENT_EXPORT_BAD_CALL` |
| `service-app/.../oa/agent_bridge/_smoke_*.php` | 冒烟改为 Inspector + 无 Registry invoke |
| `open-oa/.../AuthAgentBearer.php` | discover/describe/probe=网关；invoke=Bearer+网关；删 catalog |
| `open-oa/.../ExportBridge.php` | discover/describe/probe/invoke；删 catalog |
| `open-oa/route/app.php` + `config/user.php` | 新路由；删 export-catalog |
| `backend/.../integrations/open_oa.py` | discover/describe/probe；invoke 带网关；删 get_export_catalog |
| `backend/.../executor/registry.py` + `catalog.py` + `executor.py` | schema/`ToolSpec` 增加 `invoke_call`；POST body 带 `call`；header 带网关密钥 |
| `backend/.../admin/catalog_api.py` | 向导 API；删 open-oa-catalog import |
| `frontend/.../ToolsView.vue` + `ops.ts` + `toolGuides.ts` | 向导 UI；删清单导入 |
| `docs/delivery/...` + 本计划勾选 | 交付回写 |

---

### Task 1: Service — `ExportInspector` 反射发现

**Files:**
- Create: `D:\MYOA\webroot\puyueheng\service\service-app\src\service\oa\agent_bridge\ExportInspector.php`
- Modify: `D:\MYOA\webroot\puyueheng\service\service-app\src\service\oa\agent_bridge\Export.php`（增加 `discoverExports` / `describeExport` 薄封装）
- Modify: `D:\MYOA\webroot\puyueheng\service\service-app\src\service\oa\agent_bridge\Error.php`（如需 `AGENT_EXPORT_SERVICE_INVALID`）
- Test: `D:\MYOA\webroot\puyueheng\service\service-app\src\service\oa\agent_bridge\_smoke_export_inspector.php`

**Interfaces:**
- Produces:
  - `ExportInspector::listPublicMethods(string $service): array`  
    每项：`['name'=>string,'param_names'=>string[],'is_public'=>true]`
  - `ExportInspector::describeMethod(string $service, string $method): array`  
    `['service','method','params'=>[...],'call_suggest'=>'page_list|one_by_params|named_args','returns'=>null|array,'summary'=>string]`
  - `Export::discoverExports(string $service): array` → 调 Inspector
  - `Export::describeExport(string $service, string $method): array` → 调 Inspector
- Consumes: `ANew($service)`；`ReflectionClass` / `ReflectionMethod`

- [ ] **Step 1: 编写 `ExportInspector.php` 骨架**

```php
<?php
namespace app\service\oa\agent_bridge;

use lib\exception\Exception;
use ReflectionClass;
use ReflectionMethod;

class ExportInspector
{
    /** @var string[] */
    private static $nameBlacklist = [];

    /**
     * @param string $service ANew 服务名 a/b/c
     * @return array
     */
    public static function listPublicMethods(string $service): array
    {
        $export = self::resolveExport($service);
        $ref = new ReflectionClass($export);
        $out = [];
        foreach ($ref->getMethods(ReflectionMethod::IS_PUBLIC) as $m) {
            $name = $m->getName();
            if (strpos($name, '__') === 0) {
                continue;
            }
            if ($m->isStatic()) {
                continue;
            }
            if (in_array($name, self::$nameBlacklist, true)) {
                continue;
            }
            $paramNames = [];
            foreach ($m->getParameters() as $p) {
                $paramNames[] = $p->getName();
            }
            $out[] = [
                'name' => $name,
                'param_names' => $paramNames,
                'is_public' => true,
            ];
        }
        return $out;
    }

    /**
     * @param string $service ANew 服务名
     * @param string $method 方法名
     * @return array
     */
    public static function describeMethod(string $service, string $method): array
    {
        // Reflection + 粗解析 PHPDoc @param/@return；call_suggest 按形参形态；
        // 禁止把 oa/token 等写入 params；returns 无法推断时为 null
        // （实现时写完整，勿留 TODO）
    }

    /**
     * @param string $service ANew 服务名
     * @return object
     */
    private static function resolveExport(string $service)
    {
        $service = trim($service);
        if ($service === '' || strpos($service, '..') !== false) {
            throw Exception::user(Error::AGENT_EXPORT_NOT_FOUND);
        }
        $export = ANew($service);
        if (!is_object($export)) {
            throw Exception::user(Error::AGENT_EXPORT_NOT_FOUND);
        }
        return $export;
    }
}
```

- [ ] **Step 2: `Export` 增加 discover/describe 委托；冒烟脚本列出 `out_attendance/go_out_application` 且含 `getTravelExpensePageList`**

```php
public function discoverExports(string $service): array
{
    return ExportInspector::listPublicMethods($service);
}

public function describeExport(string $service, string $method): array
{
    return ExportInspector::describeMethod($service, $method);
}
```

Run（在可加载 ANew 的环境）: `php .../_smoke_export_inspector.php`  
Expected: 打印方法列表含 `getTravelExpensePageList`；describe 给出 `call_suggest=page_list`

- [ ] **Step 3: 用户要求时再 commit（Service 仓）**

---

### Task 2: Service — 无 Registry 的 `invokeAgentExport`

**Files:**
- Modify: `.../oa/agent_bridge/Export.php`
- Delete: `.../oa/agent_bridge/AgentExportRegistry.php`
- Modify: `.../oa/agent_bridge/Error.php`（`AGENT_EXPORT_NOT_FOUND` 文案改为「方法不存在或不可调用」；可选 `AGENT_EXPORT_BAD_CALL`）
- Modify: `_smoke_agent_bridge.php`（去掉 Registry 断言）

**Interfaces:**
- Change: `invokeAgentExport(string $service, string $method, array $args, array $identity, string $idempotencyKey = '', string $call = 'one_by_params', string $op = 'read'): array`
- 行为：反射确认 public 方法存在；剥身份字段；强制 `$clean['oa']=$oa`；按 `$call` 绑定；write 校验幂等键；**不再** `AgentExportRegistry::find`

- [ ] **Step 1: 改 `invokeAgentExport` 签名与实现（删除 Registry 查找）**

关键逻辑：

```php
$export = ANew($service);
if (!is_object($export) || !method_exists($export, $method)) {
    throw Exception::user(Error::AGENT_EXPORT_NOT_FOUND);
}
$ref = new \ReflectionMethod($export, $method);
if (!$ref->isPublic() || $ref->isStatic() || strpos($method, '__') === 0) {
    throw Exception::user(Error::AGENT_EXPORT_NOT_FOUND);
}
// ... clean args, force oa ...
if ($op === 'write' && $idempotencyKey === '') {
    throw Exception::user(Error::AGENT_EXPORT_WRITE_NEEDS_IDEMPOTENCY);
}
if ($call === 'page_list') { /* 现有 page/limit 逻辑 */ }
elseif ($call === 'named_args') {
    $ordered = [];
    foreach ($ref->getParameters() as $p) {
        $n = $p->getName();
        if (array_key_exists($n, $clean)) {
            $ordered[] = $clean[$n];
        } elseif ($p->isDefaultValueAvailable()) {
            $ordered[] = $p->getDefaultValue();
        } else {
            throw Exception::user(Error::AGENT_EXPORT_FORBIDDEN_ARG);
        }
    }
    $raw = $ref->invokeArgs($export, $ordered);
} else {
    $raw = $export->{$method}($clean);
}
```

- [ ] **Step 2: 删除 `AgentExportRegistry.php`；全仓 grep `AgentExportRegistry` / `listAgentExports` 清零**

- [ ] **Step 3: 冒烟：对 `getTravelExpensePageList` 用测试 oa + `call=page_list` 调通（环境可用时）**

- [ ] **Step 4: 用户要求时再 commit**

---

### Task 3: open-oa — 鉴权与 discover/describe/probe/invoke

**Files:**
- Modify: `D:\MYOA\webroot\puyueheng\site\open-oa\app\middleware\AuthAgentBearer.php`
- Modify: `D:\MYOA\webroot\puyueheng\site\open-oa\app\controller\agent\ExportBridge.php`
- Modify: `D:\MYOA\webroot\puyueheng\site\open-oa\route\app.php`
- Modify: `D:\MYOA\webroot\puyueheng\site\open-oa\config\user.php`

**Interfaces:**
- Routes under `/agent`（middleware `AuthAgentBearer`）:
  - `POST export/discover` → gateway
  - `POST export/describe` → gateway
  - `POST export/probe` → gateway（body 含测试 `oa`）
  - `POST invoke` → **Bearer + gateway**
  - **删除** `GET export-catalog`
- `ExportBridge::probe`：校验网关模式 → 用 body.oa 解析/校验员工 → `invokeAgentExport(..., $call, $op)`
- `ExportBridge::invoke`：要求 `agent_auth_mode` 表示已同时通过 Bearer+gateway；body 含 `service/method/args/call/op`

- [ ] **Step 1: 重写 `AuthAgentBearer` 路径规则**

```php
// 伪代码顺序：
// 1) 若是 discover|describe|probe：仅 gateway_secret OK → agent_auth_mode=gateway, agent_oa=''
// 2) 若是 invoke：必须 Authorization Bearer 校验员工，且 gateway_secret OK；缺一 unauthorized
// 3) 其他 /agent/*：保持既有或 unauthorized
// 删除 isExportCatalogPath；改为 isAgentExportManagePath / isAgentInvokePath
```

- [ ] **Step 2: `ExportBridge` 实现 discover/describe/probe；invoke 读取 `call`/`op` 传给 Service；删除 `catalog()`**

```php
public function discover() {
    $payload = $this->readPayload();
    $service = trim((string)($payload['service'] ?? ''));
    $bridge = ANew('oa/agent_bridge');
    return $this->suc(['methods' => $bridge->discoverExports($service)]);
}

public function probe() {
    // 仅 gateway 模式；oa 从 body；call/op/args/service/method
    // identity = ['oa' => $oa, 'uid' => ...]（可用 oa/user 查 uid）
    // return suc(data)
}
```

- [ ] **Step 3: 更新 `route/app.php` 与 `config/user.php` 白名单路径**

- [ ] **Step 4: 手工或脚本：无网关 invoke → 401；有网关无 Bearer invoke → 401；双凭证 + 合法方法 → 200（环境可用时）**

- [ ] **Step 5: 确认业务页直接 ANew 未改动（抽查 go_out_application 调用链无 diff）**

- [ ] **Step 6: 用户要求时再 commit（open-oa 仓）**

---

### Task 4: Agent — `OpenOaClient` 与执行器双鉴权 + `call`

**Files:**
- Modify: `E:\python_project\oa-langGraph\backend\oa_agent\integrations\open_oa.py`
- Modify: `E:\python_project\oa-langGraph\backend\oa_agent\executor\registry.py`
- Modify: `E:\python_project\oa-langGraph\backend\oa_agent\executor\catalog.py`
- Modify: `E:\python_project\oa-langGraph\backend\oa_agent\executor\executor.py`
- Modify: `E:\python_project\oa-langGraph\backend\oa_agent\connectors\http_json.py`（若 invoke 需透传 extra_headers）
- Test: `E:\python_project\oa-langGraph\backend\tests\test_open_oa_*.py`（改建）

**Interfaces:**
- `OpenOaClient.discover_exports(service, *, gateway_secret) -> list`
- `OpenOaClient.describe_export(service, method, *, gateway_secret) -> dict`
- `OpenOaClient.probe_export(..., oa, args, call, op, *, gateway_secret) -> Any`
- `OpenOaClient.post(..., extra_headers)` 已有；执行器 invoke 时加 `X-Agent-Gateway-Secret`
- 删除 `get_export_catalog` / `CATALOG_PATH`
- `ToolSpec.invoke_call: str = "one_by_params"`
- normalize / `tool_spec_from_schema` 读写 `invoke_call`
- `_execute_open_oa_invoke` body: `{"service","method","args","call": spec.invoke_call, "op": ...}`

- [ ] **Step 1: 写失败测试 — invoke 请求必须带网关 header（可用 httpx mock）**

```python
def test_open_oa_invoke_sends_gateway_secret(monkeypatch, ...):
    # 断言 post headers 含 X-Agent-Gateway-Secret
    # 断言 body 含 call
```

- [ ] **Step 2: 实现 client 方法；executor 从 runtime OA settings 取 `gateway_secret` 传入 post `extra_headers`**

注意：`ToolExecutor` 当前可能无 settings 句柄——从 `self.clients` 同源配置或构造时注入 `gateway_secret`（与 mint 同源）。若 connector 路径，扩展 `connector.invoke(..., extra_headers=)`。

- [ ] **Step 3: catalog normalize 支持 `invoke_call`；缺省 `one_by_params`**

- [ ] **Step 4: 删除 catalog import 相关 client 方法；改/删 `test_open_oa_catalog_import.py`**

- [ ] **Step 5: `pytest` 相关用例全绿**

Run: `.\.venv\Scripts\python.exe -m pytest backend/tests/test_open_oa_catalog_import.py backend/tests/test_executor_open_oa*.py -q`（按实际文件名调整）  
Expected: PASS 或旧 catalog 测试已删除/替换

- [ ] **Step 6: 用户要求时再 commit**

---

### Task 5: Agent 管理 API — 向导后端（替换清单导入）

**Files:**
- Modify: `E:\python_project\oa-langGraph\backend\oa_agent\admin\catalog_api.py`
- Test: `E:\python_project\oa-langGraph\backend\tests\test_export_wizard_admin.py`（新建）

**Interfaces:**
- `POST /v1/admin/tools/export-wizard/discover` `{service}` → `{methods: [...]}`
- `POST /v1/admin/tools/export-wizard/describe` `{service, method}` → describe 草稿
- `POST /v1/admin/tools/export-wizard/probe` `{service, method, oa, args, call, op}` → `{data, ...}`
- `POST /v1/admin/tools/export-wizard/save`  
  `{reason, service, method, call, op, risk, name, summary, model_params, result, ...}`  
  校验：须先由同会话可证明的 probe 成功 **或** body 带 `probe_ok: true` 且服务端用短 TTL 缓存 key（推荐：**save 内再强制 probe 一次** 用同一参数，失败则 422）  
  成功 → 写入 Tool `kind=open_oa_invoke`，含 `invoke_service/method/call`
- **删除** `GET/POST .../import/open-oa-catalog` 与 `_open_oa_catalog_client` 的 catalog 专用逻辑（可复用 client+secret 辅助函数改名）

- [ ] **Step 1: 写管理 API 失败/成功测试（monkeypatch OpenOaClient）**

```python
def test_wizard_save_requires_successful_probe(admin, monkeypatch):
    # probe 失败 → save 422
def test_wizard_save_persists_open_oa_invoke(admin, monkeypatch):
    # probe 成功 → tool.kind == open_oa_invoke 且 invoke_call 落库
```

- [ ] **Step 2: 实现三端点 + save；删除旧 import 路由**

- [ ] **Step 3: pytest 通过**

- [ ] **Step 4: 用户要求时再 commit**

---

### Task 6: Agent 前端 — Tools 向导 UI

**Files:**
- Modify: `E:\python_project\oa-langGraph\frontend\src\admin\views\ToolsView.vue`
- Modify: `E:\python_project\oa-langGraph\frontend\src\admin\ops.ts` / `toolGuides.ts`（展示 `invoke_call`；文案）

**Interfaces:**
- 按钮：「接入 Export 向导」（替换「从 open-oa 清单导入」）
- 步骤：service 输入 → discover → 选 method → describe 填表 → 测试员工 oa + 参数 → probe → 成功后 save
- 删除 open-oa 清单对话框与相关 state

- [ ] **Step 1: 移除清单导入 UI/API 调用**

- [ ] **Step 2: 实现向导对话框（可单页分块，不必多路由）**

关键调用：

```ts
await http.post('/v1/admin/tools/export-wizard/discover', { service })
await http.post('/v1/admin/tools/export-wizard/describe', { service, method })
await http.post('/v1/admin/tools/export-wizard/probe', { service, method, oa, args, call, op })
await http.post('/v1/admin/tools/export-wizard/save', { reason, ...toolFields, ... })
```

- [ ] **Step 3: 详情 guide 展示 `invoke_call`；编辑阻断文案改为「请用 Export 向导覆盖」**

- [ ] **Step 4: 本地打开管理端点一遍主路径（无后端时至少保证无 TS/模板错误）**

- [ ] **Step 5: 用户要求时再 commit**

---

### Task 7: 行程 Tool 重建说明 + 文档清理

**Files:**
- Modify: `E:\python_project\oa-langGraph\docs\delivery\2026-11-12-open-oa-anew-invoke-delivery.md`（标注 catalog 废止，指向新 spec/plan）
- Create or Modify: `E:\python_project\oa-langGraph\docs\delivery\2026-11-16-agent-export-wizard-delivery.md`
- Modify: `openapi/travel_expense.yaml`（若仍存在：注明须经向导；或保留 invoke 形态字段含 `invoke_call`）

- [ ] **Step 1: 交付文档写明操作步骤：用向导接入 `getTravelExpensePageList` / `getTravelExpenseOneByParams`，测试员工、call、result.fields 参考旧 Registry 内容（可把旧 Registry 字段作为附录粘贴后删除代码）**

- [ ] **Step 2: 全文 grep `export-catalog` / `AgentExportRegistry` / `import/open-oa-catalog` / `从 open-oa 清单` 清零或改指向**

- [ ] **Step 3: 用户要求时再 commit**

---

### Task 8: 联调验收（外部依赖）

- [ ] **Step 1: 测试环境配置 mint_base_url + AGENT_GATEWAY_SECRET**
- [ ] **Step 2: 向导走通行程 list；对话启用后查询与同账号一致**
- [ ] **Step 3: 故意去掉网关密钥调用 invoke → 失败**
- [ ] **Step 4: 抽查任一非 Agent 业务页 `ANew` 仍正常**
- [ ] **Step 5: 在 delivery 文档标注「已验证 / 未验证」项**

---

## Spec coverage（自检）

| Spec 要求 | Task |
|-----------|------|
| ExportInspector 列 public 方法 | T1 |
| describe 混合预填 | T1 |
| 无 Registry invoke + call 绑定 | T2 |
| discover/describe/probe HTTP | T3 |
| invoke = Bearer + 网关 | T3、T4 |
| 不影响业务 ANew | T3 Step 5、T8 |
| 下线 catalog/Registry/清单导入 | T2、T3、T4、T5、T6、T7 |
| 向导 UI 测通入库 | T5、T6 |
| 指定测试员工 | T3 probe、T5、T6 |
| Tool 含 invoke_call；模型不可改 | T4、T5 |
| 行程重建与验收 | T7、T8 |

## Placeholder / 一致性自检

- 无 TBD；`call` 三值：`page_list` | `one_by_params` | `named_args` 全文统一
- save 策略定为：**save 内用同一参数再 probe 一次**，避免仅靠前端 `probe_ok` 作弊
- 网关 header 名统一：`X-Agent-Gateway-Secret`
