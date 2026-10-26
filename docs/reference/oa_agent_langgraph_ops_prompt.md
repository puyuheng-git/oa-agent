# Cursor 开发提示词：基于 LangGraph 的企业级 OA Agent 自动化 MCP 架构

## 一、角色定位

你是一名资深企业级架构师、Python MCP 开发工程师、PHP 后端工程师和 AI
Agent 工程师。

请基于当前项目代码，协助我逐步实现一个企业级 OA Agent 架构。项目目标是：

> 用户通过企业微信或 OA
> 对话，用自然语言完成行程查询、报销金额计算、生成报销草稿，并在用户明确确认后提交报销。

当前技术方向：

-   OA 后端：PHP
-   Agent 编排框架：LangGraph
-   MCP Server：Python
-   Agent 入口：企业微信、OA 页面
-   数据库：以现有 OA 数据库为准
-   Agent 不允许直接访问 OA 数据库
-   Agent 必须通过 MCP 调用 OA API
-   MCP 不应该为每个接口手写一个独立 Tool 文件
-   普通 API 应通过 OpenAPI 和 Agent 元数据自动生成 MCP Tool
-   Skill 只负责复杂业务场景，不负责重复描述每个接口
-   高风险操作必须经过用户明确确认

------------------------------------------------------------------------

## 二、总体架构目标

请实现以下分层架构：

``` text
企业微信 / OA Web
        |
        v
Agent Gateway
  - 用户认证
  - 用户身份上下文
  - 会话管理
  - 审计日志
  - 限流
        |
        v
Agent Orchestrator
  - 意图识别
  - 场景路由
  - Skill 选择
  - Tool 筛选
  - Workflow 管理
        |
        v
LangGraph Agent Platform
  - StateGraph 执行图与节点编排
  - 模型调用与意图路由
  - 动态 Tool 绑定和调用
  - Checkpointer 状态持久化
  - interrupt / resume 人工确认与恢复
        |
        v
Skill / Workflow
  - 行程报销业务流程
  - 多接口组合
  - 状态管理
  - 确认节点
        |
        v
OA Auto MCP Adapter
  - 自动发现 OA API
  - 读取 OpenAPI
  - 自动生成 MCP Tool Schema
  - 通用 HTTP 调用
  - 权限和风险策略
        |
        v
PHP OA Domain API
  - 身份和权限校验
  - 业务规则
  - 参数校验
  - 事务处理
  - 幂等控制
        |
        v
MySQL / Redis
```

请不要让 LangGraph、Skill 或 MCP 直接访问数据库。

------------------------------------------------------------------------

## 三、核心设计原则

必须遵守以下原则：

1.  OA API 是业务能力的真实来源。
2.  OpenAPI 是自动生成 MCP Tool 的基础契约。
3.  MCP Adapter 采用通用机制，不为每个接口编写重复代码。
4.  Skill 按业务场景组织，而不是按单个接口组织。
5.  Workflow 负责有状态、强约束的业务流程。
6.  Tool 按业务领域和当前场景进行筛选或动态加载。
7.  高风险操作必须通过确认机制。
8.  所有权限必须在服务端校验，不能只依赖 Skill 或模型指令。
9.  MCP 不允许直接访问数据库。
10. 接口新增或修改后，应尽量通过元数据和自动同步机制完成 Tool 更新。
11. 不要为了追求复杂架构而一次性引入过多微服务。
12. 优先实现可运行的 MVP，再逐步增加企业级能力。
13. 不要擅自修改现有业务规则，不确定时先检查项目代码。
14. 不要编造不存在的接口、字段、数据库表或配置。
15. 任何破坏性修改前，先说明影响范围和迁移方案。

------------------------------------------------------------------------

## 四、第一阶段业务范围：行程报销

只实现行程报销场景，不要一开始扩展会议室、人事、业绩等领域。

用户示例：

``` text
帮我把上周深圳出差的费用报销了。
```

目标流程：

``` text
用户输入
   |
   v
识别为行程报销场景
   |
   v
提取时间、地点等参数
   |
   v
查询当前用户的行程
   |
   v
查询关联发票
   |
   v
计算可报销金额
   |
   v
检查报销规则和数据完整性
   |
   v
生成报销草稿
   |
   v
展示报销明细
   |
   v
等待用户明确确认
   |
   v
再次校验权限、金额、草稿状态
   |
   v
提交报销
   |
   v
返回报销单号和状态
```

必须区分以下操作：

-   查询行程：只读
-   查询发票：只读
-   计算报销金额：只读或计算
-   创建报销草稿：写操作
-   正式提交报销：高风险写操作，必须明确确认

------------------------------------------------------------------------

## 4.1 依赖与版本管理

请先检查项目是否已有 `pyproject.toml`、`requirements.txt` 或锁文件。不要盲目覆盖现有依赖。按当前项目的 Python 版本和依赖管理方式，选择兼容的 LangGraph、模型集成包、MCP Python SDK、FastAPI（若项目需要 HTTP API）及持久化 Checkpointer 依赖。

新增依赖时：
- 说明用途、版本约束和替代方案。
- 锁定经过验证的版本。
- 为图构建、工具绑定、Checkpoint、interrupt/resume 分别编写测试。
- 不要假设 LangGraph 本身会自动发现磁盘上的 Skill 或任意 MCP Server；这些能力需要显式实现或通过已验证的集成提供。

## 五、MCP 自动生成设计

### 5.1 不允许采用的方式

不要为每一个 OA API 手工创建类似下面的文件：

``` text
query_travel_records.py
query_invoice.py
create_reimbursement.py
submit_reimbursement.py
```

除非某个 Tool 具有无法通过通用 HTTP 映射实现的特殊逻辑。

### 5.2 推荐方式

实现一个通用 OA MCP Adapter：

``` text
oa-auto-mcp/
├── server.py
├── discovery.py
├── openapi_loader.py
├── schema_builder.py
├── tool_executor.py
├── permission.py
├── policy.py
├── registry.py
├── oa_api_client.py
└── cache.py
```

职责：

-   `discovery.py`：发现和读取 OA API 元数据
-   `openapi_loader.py`：读取 OpenAPI JSON/YAML
-   `schema_builder.py`：生成 MCP Tool Schema
-   `tool_executor.py`：根据接口定义执行 HTTP 请求
-   `permission.py`：执行工具级权限检查
-   `policy.py`：处理风险等级、确认要求和审计策略
-   `registry.py`：管理 Tool 元数据和状态
-   `oa_api_client.py`：统一调用 PHP OA API
-   `cache.py`：缓存接口定义和 Tool Schema
-   `server.py`：MCP 服务入口

------------------------------------------------------------------------

## 六、OpenAPI 元数据规范

请设计一套可扩展的 API 元数据约定。

普通 OpenAPI 字段至少包括：

-   `operationId`
-   `summary`
-   `description`
-   `tags`
-   请求参数
-   响应 Schema
-   HTTP method
-   path

建议增加扩展字段：

``` yaml
x-agent:
  enabled: true
  domain: reimbursement
  capability: query_travel_records
  risk_level: low
  requires_confirmation: false
  audit_required: true
  idempotent: true
  visibility: user
  timeout_seconds: 10
```

高风险接口示例：

``` yaml
x-agent:
  enabled: true
  domain: reimbursement
  capability: submit_reimbursement
  risk_level: high
  requires_confirmation: true
  audit_required: true
  idempotent: false
  visibility: user
```

请注意：

-   `x-agent.enabled` 不能替代服务端权限校验。
-   元数据中的权限信息只能作为路由和策略参考。
-   最终权限必须由 OA API 重新判断。
-   对不完整或不安全的 API 定义，应拒绝自动暴露，并输出明确错误。

------------------------------------------------------------------------

## 七、第一版 Tool 能力

请优先支持以下业务能力：

``` text
query_my_travel_records
query_travel_invoices
calculate_reimbursement
create_reimbursement_draft
submit_reimbursement
```

Tool 设计要求：

1.  当前用户身份从受信任的上下文中获得。
2.  不允许模型自由传入任意 `user_id` 并绕过身份校验。
3.  所有参数必须经过 Schema 校验。
4.  所有调用都要记录审计日志。
5.  高风险 Tool 必须检查确认状态。
6.  正式提交前必须重新查询草稿状态。
7.  提交操作必须具备幂等保护。
8.  返回结果必须进行统一格式化。
9.  不向模型泄露不必要的内部异常、数据库信息或敏感字段。

------------------------------------------------------------------------

## 八、Skill 设计

只创建一个业务 Skill：

``` text
skills/
└── domains/
    └── travel-reimbursement/
        ├── SKILL.md
        ├── policies.md
        └── examples.md
```

Skill 只描述：

-   什么时候适用
-   如何识别用户意图
-   如何提取时间、地点和行程条件
-   如何组合工具
-   什么时候需要补充信息
-   什么时候必须确认
-   如何处理异常
-   如何向用户展示结果

Skill 不应该重复定义：

-   每个接口的 HTTP 请求代码
-   每个 Tool 的底层实现
-   数据库查询语句
-   最终权限逻辑
-   财务金额安全校验

请将确定性的业务规则放到 OA Domain API 或 Workflow 中，而不是只写在
`SKILL.md` 里。

------------------------------------------------------------------------

## 8.1 LangGraph 实现约束

LangGraph 是编排框架，不是开箱即用的完整 Agent Runtime。请在应用层实现必要的模型接入、MCP 客户端、Skill Registry、Tool Registry、会话入口和权限策略。

推荐采用两种执行模式：

1. 通用问答图：加载当前用户有权访问的 Skill/Tool，由模型按需调用只读工具并组织回答。
2. 业务 Workflow 子图：行程报销等有副作用场景使用显式节点和条件边，固定步骤由代码控制。

建议的图结构：

```text
START
  -> load_trusted_context
  -> route_intent
      -> general_agent -> tool_execution -> response -> END
      -> reimbursement_workflow
          -> collect_parameters
          -> query_travel
          -> query_invoices
          -> calculate
          -> validate_completeness
          -> create_draft
          -> interrupt_for_confirmation
          -> revalidate
          -> submit_idempotently
          -> response
```

具体要求：
- 使用 `StateGraph` 定义图；根据项目所安装的 LangGraph 版本选择对应 API。
- 将模型节点、工具执行节点、业务 Workflow 节点分开，避免在单一超长节点里完成全部逻辑。
- 对简单工具调用可使用 LangGraph/LangChain 生态的工具节点；自动生成的工具应来自 Tool Registry，不得为每个 API 手写重复工具函数。
- Checkpointer 用于恢复图执行；业务状态仍需由 OA API 或可靠业务存储保存，Checkpoint 不能代替报销单真实状态。
- 生产环境配置持久化 Checkpointer、稳定的 `thread_id`、超时和并发限制。
- `thread_id` 只用于定位执行线程，不作为用户身份或权限凭证。
- 人工确认必须由可信的确认 API 或受信任的交互事件触发，并绑定用户、会话、草稿 ID、草稿版本/金额快照和过期时间。
- 对有副作用的节点采用幂等键；重试前先查询业务结果，避免重复创建或提交。
- 如果 LangGraph API、MCP SDK 或模型集成 API 受版本影响，先检查依赖锁文件和官方文档，再按当前版本实现，禁止猜测接口。

---

## 九、Workflow 设计

行程报销必须具备明确的状态管理。

建议状态：

``` text
INIT
PARAMETER_COLLECTION
QUERYING_TRAVEL
QUERYING_INVOICES
CALCULATING
DRAFT_CREATED
WAITING_CONFIRMATION
SUBMITTING
SUBMITTED
CANCELLED
FAILED
EXPIRED
```

要求：

1.  状态转换必须明确。
2.  不允许重复提交。
3.  确认状态必须与具体用户、会话和草稿绑定。
4.  草稿必须有过期时间。
5.  网络超时和重试不能导致重复报销。
6.  失败时返回可理解的错误信息。
7.  必须支持审计和问题排查。
8.  对关键状态转换增加服务端校验。

------------------------------------------------------------------------

## 十、Tool 加载策略

请采用渐进式设计。

### 第一版

启动时读取 OpenAPI，生成 Tool Schema，并按领域或场景筛选。

行程报销场景只暴露：

``` text
query_my_travel_records
query_travel_invoices
calculate_reimbursement
create_reimbursement_draft
submit_reimbursement
```

### 第二版

支持管理接口手动刷新：

``` text
POST /internal/mcp/refresh
```

要求：

-   刷新过程可观测
-   Schema 生成失败时保留旧版本
-   不能因为一次错误导致所有 Tool 消失
-   记录刷新时间、版本和错误原因

### 第三版

支持 CI/CD 或事件通知自动同步：

``` text
OpenAPI 更新
   |
   v
Schema 校验
   |
   v
生成 Tool Registry 快照
   |
   v
自动刷新 MCP Adapter
```

不要在第一阶段就实现复杂的动态 Tool
Discovery，除非现有项目已经具备基础设施。

------------------------------------------------------------------------

## 十一、权限与安全要求

请把安全控制设计成多层防护：

``` text
Agent Gateway
  - 认证
  - 用户身份
  - 租户隔离

MCP Adapter
  - Tool 白名单
  - 风险策略
  - 参数校验
  - 审计

PHP OA API
  - 最终权限校验
  - 数据权限
  - 业务规则
  - 事务
  - 幂等

数据库
  - 数据隔离
  - 最小权限
```

必须实现或预留：

-   用户身份上下文
-   租户隔离
-   草稿归属校验
-   Tool 权限校验
-   高风险操作确认
-   幂等键
-   审计日志
-   敏感信息脱敏
-   超时和重试策略
-   错误分类
-   API 版本兼容

------------------------------------------------------------------------

## 十二、推荐的数据结构

请先检查现有 OA 数据库和 API，只有在确认不存在对应能力时才提出新增结构。

可能涉及：

``` text
travel_records
travel_invoices
reimbursement_drafts
reimbursement_requests
agent_audit_logs
```

报销草稿至少需要考虑：

-   草稿 ID
-   用户 ID
-   行程 ID
-   金额
-   明细快照
-   状态
-   过期时间
-   创建时间
-   更新时间
-   幂等标识

金额明细应保留快照，便于后续审计和问题追踪。

------------------------------------------------------------------------

## 十三、开发执行方式

请严格按照以下顺序工作，不要一次性生成大量未经验证的代码。

### Step 1：检查项目

先分析：

-   当前目录结构
-   PHP OA API 结构
-   是否已有 OpenAPI
-   是否已有认证机制
-   是否已有企业微信入口
-   是否已有 LangGraph 配置
-   是否已有 MCP Server
-   是否已有日志和缓存组件

输出：

1.  当前项目结构总结
2.  已有能力
3.  缺失能力
4.  可能的风险
5.  建议实施顺序

不要在没有检查代码之前假设文件路径和框架。

### Step 2：设计 API Contract

先选择一个最简单的只读接口，例如：

``` text
查询当前用户的出差行程
```

完成：

-   API 参数
-   API 响应
-   OpenAPI 描述
-   `x-agent` 元数据
-   权限约束
-   错误响应

### Step 3：实现自动 Tool Schema

实现：

-   OpenAPI 加载
-   Tool Schema 生成
-   参数校验
-   Tool 列表输出
-   单元测试

先不要接入所有接口。

### Step 4：实现通用执行器

实现：

-   HTTP method 映射
-   path 参数处理
-   query 参数处理
-   body 参数处理
-   当前用户身份传递
-   超时
-   错误处理
-   审计日志

### Step 5：接入 LangGraph

实现一个最小可运行的 LangGraph StateGraph，并先验证：

``` text
用户消息
  -> Agent Gateway 注入可信身份上下文
  -> LangGraph StateGraph
  -> ToolNode / 动态工具绑定
  -> MCP Client 调用 OA MCP Server
  -> PHP OA API
  -> 返回当前用户行程
```

要求：
- 使用明确的 State 类型描述 messages、用户/会话引用、当前场景、workflow_id 和错误状态。
- 使用 LangGraph 的条件边或路由节点区分普通问答与行程报销 Workflow。
- 为生产运行配置持久化 Checkpointer；开发环境可以使用内存实现。
- 通过稳定的 thread_id 关联同一会话，但不得把 thread_id 当作身份或授权凭证。
- 对需要人工确认的步骤使用 interrupt / resume 或独立确认 API；恢复时必须重新校验用户身份、草稿归属、草稿状态和金额快照。
- 不要把不可逆的提交操作放在 interrupt 之前，也不要假设中断节点恢复时只会执行后半段。
- 若当前 LangGraph 版本的 API 与示例不同，先检查项目依赖版本和官方文档，再实现，不要臆造接口。

### Step 6：增加报销流程

按顺序实现：

1.  查询行程
2.  查询发票
3.  计算金额
4.  创建草稿
5.  等待确认
6.  正式提交

### Step 7：增加测试

至少覆盖：

-   正常查询
-   无行程
-   多个行程
-   发票缺失
-   参数错误
-   无权限
-   草稿过期
-   重复确认
-   重复提交
-   OA API 超时
-   MCP Tool Schema 生成失败
-   OpenAPI 版本变化
-   LangGraph 图路由到正确的通用 Agent / 报销 Workflow
-   Checkpoint 持久化后恢复执行
-   interrupt / resume 人工确认流程
-   恢复执行时重复节点不会造成重复提交
-   不同用户不能通过复用 thread_id 访问彼此状态

------------------------------------------------------------------------

## 十四、代码质量要求

请遵循以下规则：

1.  优先复用现有项目代码。
2.  保持模块职责单一。
3.  不要复制粘贴重复的 HTTP 调用逻辑。
4.  所有外部输入都要校验。
5.  不要把密钥写入代码。
6.  使用环境变量或现有配置系统管理密钥。
7.  关键操作增加结构化日志。
8.  对外错误信息不能泄露内部实现细节。
9.  为核心逻辑编写测试。
10. 代码必须能够本地运行和验证。
11. 先实现最小闭环，再重构和扩展。
12. 不要无理由引入重量级依赖。
13. 任何新增依赖都说明用途和替代方案。
14. 对不确定的实现先检查文档、代码和现有配置。

------------------------------------------------------------------------

## 十五、每次执行后的输出格式

每完成一个步骤，请按以下格式输出：

### 1. 本次目标

说明本次准备完成什么。

### 2. 已检查内容

列出检查过的文件、模块和配置。

### 3. 实施方案

说明设计决策及原因。

### 4. 修改文件

列出：

-   新增文件
-   修改文件
-   删除文件

对于每个文件说明修改目的。

### 5. 核心代码

只展示关键代码，避免无关代码刷屏。

### 6. 测试方式

给出可执行的命令和验证步骤。

### 7. 风险与待办

列出：

-   当前限制
-   潜在风险
-   下一步建议

### 8. 是否需要我确认

涉及以下情况时，必须先暂停并请求确认：

-   删除文件
-   修改数据库结构
-   修改认证逻辑
-   修改生产配置
-   引入重大依赖
-   执行不可逆操作
-   修改核心业务规则

------------------------------------------------------------------------

## 十六、最终验收标准

当以下链路全部跑通时，才认为第一版完成：

``` text
企业微信或测试客户端
   |
   v
用户发送：
“帮我把上周深圳出差的费用报销了”
   |
   v
识别行程报销场景
   |
   v
自动加载相关 Tool
   |
   v
查询当前用户行程
   |
   v
查询发票
   |
   v
计算金额
   |
   v
生成报销草稿
   |
   v
展示明细并等待确认
   |
   v
用户明确确认
   |
   v
重新校验权限和草稿状态
   |
   v
提交 OA 报销
   |
   v
返回报销单号和审批状态
```

最终目标：

> 普通 OA API 新增或修改时，优先通过 OpenAPI 和 Agent
> 元数据自动生成或更新 MCP Tool，不要求开发人员重复编写 Skill、MCP Tool
> 和大量配置文件。

同时必须保留人工设计的部分：

-   复杂业务流程
-   财务规则
-   权限策略
-   风险控制
-   用户确认
-   审计要求
-   异常恢复

请从"检查当前项目代码和目录结构"开始，不要直接假设项目已经具备任何模块。
