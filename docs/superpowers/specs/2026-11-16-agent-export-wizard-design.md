# Agent Export 向导接入设计（替代 catalog 导入）

| 项 | 内容 |
|---|---|
| 日期 | 2026-11-16 |
| 状态 | 已评审待实现 |
| 范围 | Service 反射发现 Export 方法；open-oa discover/describe/probe；Agent 管理端「填 a/b/c → 选方法 → 配参 → 测通 → 入 Tool」；下线 Registry / export-catalog / 清单导入 |
| 前置 | [2026-11-12 open-oa ANew invoke](./2026-11-12-open-oa-anew-invoke-design.md) 已落地通用 invoke 骨架；本设计修正「谁定义契约、如何进入 Tool」 |

## 1. 背景与目标

一期实现是：Service `AgentExportRegistry` 预注册契约 → `GET /agent/export-catalog` → Agent「从 open-oa 清单导入」。

与产品设想不符。目标流程改为：

1. 管理员在 Agent 后台填写 `a/b/c`（ANew 服务名）
2. 系统经 Service 公共类反射，列出该模块 `Export` 全部 **public** 方法
3. 管理员选择方法，配置参数、调用形态（call）、返回字段等（混合预填）
4. 指定测试员工，点击「测试接口」
5. 测试成功后加入 Tool；启用后才进入员工对话

**硬约束**

- 普通业务 `ANew('x/y/z')->method(...)` **行为不变**；双鉴权与反射 **只** 作用于 Agent 专用 open-oa HTTP 桥
- 运行时白名单 = Agent 后台 **已启用** 的 Tool（不再维护 PHP `AgentExportRegistry`）
- `POST /agent/invoke` = **员工 Bearer + Agent 网关密钥**
- 旧清单导入与 Registry **直接下线**（不长期双轨）

## 2. 决策摘要

| 编号 | 决策 |
|---|---|
| D1 | Service 公共 `ExportInspector`：`ANew(service)` 后列出 Export 全部 public 方法 |
| D2 | 参数/返回：混合预填（签名 + PHPDoc），管理员补全后再测 |
| D3 | Agent 已启用 Tool 即产品白名单；无 Service 代码注册表 |
| D4 | 测试接口使用 **指定测试员工** oa |
| D5 | 整条替换 catalog 导入；Registry / export-catalog / 清单 UI+API 删除 |
| D6 | 方案：反射发现 + open-oa 管理探测 + Agent 向导落库；invoke 双鉴权 |
| D7 | 双鉴权 **不** 进入 `ANew` / ApiProxy 内核 |

## 3. 边界与原则

**不变**

- 业务模块互调 `ANew`、OA 页调 Service、现有 Export 实现
- mint 员工 token 能力（仍在 open-oa）

**变（仅 Agent 通道）**

| 入口 | 鉴权 | 作用 |
|---|---|---|
| `POST /agent/invoke` | 员工 Bearer **且** `X-Agent-Gateway-Secret` | 员工对话真实调用 |
| discover / describe / probe | 网关密钥；probe 另带测试员工身份 | 向导拉方法、测接口 |

**下线**

- `AgentExportRegistry`
- `GET /agent/export-catalog`、`listAgentExports`
- Agent「从 open-oa 清单导入」及 `GET/POST .../import/open-oa-catalog`

## 4. 向导交互与 API

### 4.1 管理端流程

1. 输入 `service` → 拉取方法列表  
2. 选择 Export public 方法  
3. 编辑：Tool 名、摘要、op、风险、`model_params`、`result`、`call`  
   - 运行时 HTTP 固定为 `POST /agent/invoke`（管理员配的是契约，不是另开 REST 动词）  
4. 指定测试员工 oa + 测试参数 → **测试接口**  
5. 成功 → 写入 `open_oa_invoke` Tool（默认可不启用）  
6. 失败 → **不落库**（改完再测）

### 4.2 API 分层

| 调用方 | 路径（示意） | 作用 |
|---|---|---|
| Agent 管理 → open-oa | `POST /agent/export/discover` `{service}` | 列 public 方法 + 粗略签名 |
| Agent 管理 → open-oa | `POST /agent/export/describe` `{service,method}` | 单方法推断 params/returns/`call` 建议 |
| Agent 管理 → open-oa | `POST /agent/export/probe` `{service,method,args,oa,call?...}` | 指定员工真调一次 |
| Agent 管理本地 | 现有/扩展 `POST/PUT /v1/admin/tools` | 测通后保存 Tool |
| 员工运行时 | `POST /agent/invoke`（Bearer + 网关密钥） | 对话执行 |

open-oa → Service：

- discover/describe → `ExportInspector`（只反射）
- probe/invoke → 共用无 Registry 的 Export 调用绑定（强制注入本次员工 `oa`）

## 5. Service `ExportInspector`

**职责**

- `listPublicMethods(string $service): array`
- `describeMethod(string $service, string $method): array`
- 挂于 `oa/agent_bridge`（或同命名空间）；**业务 `ANew` 不经过此类**

**列出规则**

| 包含 | 排除 |
|---|---|
| Export 上 public 实例方法 | `__construct` / `__*` |
| 本类及父类 public | static（一期不做） |
| | 可配置内部名黑名单 |

**describe 推断**

- 参数：Reflection 形参 + PHPDoc `@param` → `model_params` 草稿  
- 返回：有 `@return` 则带上；否则 `result.fields` 留空，保存前由管理员补全  
- `call` 建议：  
  - `($params=[], $page=1, $limit=10)` → `page_list`  
  - 单 array `$params`/`$data` → `one_by_params`  
  - 多标量 → `named_args`  
- 永不把 `oa`/`token` 等放入模型可填参数  

**不做**

- 全仓库自动扫描注册  
- 修改目标 Export 源码  
- 在 Service 决定「对员工是否开放」

## 6. probe / invoke 绑定与鉴权

### 6.1 鉴权（仅 open-oa HTTP）

| 接口 | 必须 |
|---|---|
| `POST /agent/invoke` | 员工 Bearer（解析 oa）+ 网关密钥 |
| discover / describe | 网关密钥 |
| probe | 网关密钥 + 测试员工 oa |

缺一即拒绝。持员工票无网关密钥不可 invoke；仅网关密钥无员工身份不可 invoke。

### 6.2 无 Registry 的调用绑定

契约存在 **Agent Tool schema**（向导保存）。Service 侧逻辑（可由原 `invokeAgentExport` 改造）：

1. 校验 `service`/`method` 为 Export 上存在的 public 方法（反射）  
2. 剥离客户端身份字段，强制写入本次 `oa`  
3. 按请求/Tool 的 `call` 绑定：  
   - `one_by_params` → `$export->$method($clean)`  
   - `page_list` → `$export->$method($clean, $page, $limit)`（limit 封顶）  
   - `named_args` → 按形参名 Reflection 拼参  
4. write 要求 Idempotency-Key；read 不要求  
5. 返回数组；`page_list` 做 list/total 规范化  

Agent 执行器：模型 **不可改** `invoke_service` / `invoke_method` / `call`；只填 `model_params` 白名单。

### 6.3 安全模型（接受）

- Service 无代码白名单表  
- 靠：网关密钥不出公网 + 仅 Agent 服务端对已启用 Tool 发 invoke  
- 配错在 probe 阶段暴露；**测通才入库**

## 7. Agent 前后端

- Tools 页：移除「从 open-oa 清单导入」；新增向导对话框/分步表单  
- kind 仍为 `open_oa_invoke`；详情展示 ANew service/method/`call`  
- 表单编辑：向导覆盖更新；普通 OA GET 编辑表单仍不用于此类 Tool  
- 运行时 `OpenOaClient.invoke`：**始终附带网关密钥**（与员工 token 一起）

## 8. 迁移与验收

**顺序**

1. Service：Inspector + 无 Registry invoke；删除 Registry  
2. open-oa：discover/describe/probe；invoke 双鉴权；下线 export-catalog  
3. Agent：向导 UI + 管理 API 转发；删清单导入；invoke 带密钥  
4. 向导重配行程等 Tool；清理旧 catalog 导入数据/文档  
5. 更新交付文档与测试  

**验收**

- [ ] 合法 `a/b/c` 列出全部 public 方法；非法路径错误清晰  
- [ ] 选方法后 params/returns 可预填可改；**probe 不强制** `result.fields`，**入库前强制**补全（按 result.kind）  
- [ ] 指定测试员工 probe 成功可见 data；失败友好错误、无敏感堆栈  
- [ ] 未测通不落库；测通可入 Tool；仅启用后进对话  
- [ ] invoke 请求体携带 Tool 内固化的 `call`（与 service/method 一样不可被模型改）  
- [ ] 员工改不了 service/method；缺网关或缺票 invoke 失败  
- [ ] 抽样业务页/脚本直接 `ANew` 回归通过  
- [ ] catalog / Registry / 清单导入不可达  
- [ ] 行程只读经新 Tool 与同测试账号数据一致  

**回滚**

- 实现期可用短开关；目标态删除旧路径，不做长期双轨  

## 9. 与 2026-11-12 设计的关系

| 11-12 条款 | 本设计 |
|---|---|
| D5 OA 提供清单、勾选导入 | **废止**；改为向导 discover + probe |
| D2 Agent 启用为真相源 | **保留并强化**（无 Service Registry） |
| D3 通用 invoke | **保留**；鉴权升级为 Bearer + 网关密钥 |
| D9 行程走 ANew | **保留**；Tool 改由向导重建 |
| AgentExportRegistry | **删除** |

通用 invoke、mint 迁 open-oa、强拆 office-api Agent 路径等其余结论仍然有效。

## 10. 非目标

- MCP Server / 方案 3 本期仍不做  
- 不在 Inspector 中执行业务写操作（写操作仅经 probe/invoke，且受确认与幂等约束）  
- 不自动把所有 Export public 方法暴露给员工  
