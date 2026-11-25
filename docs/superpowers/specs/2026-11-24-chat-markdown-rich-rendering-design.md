# 员工对话 Markdown 富渲染设计

| 项 | 内容 |
|----|------|
| 日期 | 2026-11-24 |
| 状态 | **已确认** |
| 范围 | 助手回复只读 Markdown 能力扩展（语法 / 展示 / 公式 / Mermaid）+ 模型提示告知可用写法；保留导出文件名点击下载 |
| 前端仓库 | `oa-agent-chat`（`src/chat/markdown*`、`AssistantMessage.vue`） |
| 后端仓库 | `oa-langGraph`（员工助手系统提示中的「回复排版」说明） |
| 前置 | 已移除交付卡；回答内 `#ds-export:` 文件名下载已落地 |

### 已锁定决断

| ID | 选择 | 含义 |
|----|------|------|
| **D1** | 方案 A | 用 `markdown-it` 插件栈替换 `marked`；体验优先，不限制合理依赖 |
| **D2** | 一期尽量全做 | 语法扩展 + 展示增强 + 业务容器语法 + 公式 + Mermaid（含 mindmap 及常用图） |
| **D3** | Mermaid 方案 1 | 支持 `mindmap`，并开启 flowchart / sequence / class / state / er / gantt 等常用图 |
| **D4** | 模型知情 | 在员工助手系统提示中增加简短「回复排版」说明与示例 |
| **D5** | 流式策略 | 流式中用轻量 Markdown；`streaming` 结束后再跑公式 / Mermaid / Shiki 完整管道 |
| **D6** | 任务列表 | 仅展示态勾选样式，不回写消息或服务端 |

---

## 1. 目标

助手气泡内支持更完整、更接近「阅读器」的 Markdown 体验，并让模型主动使用这些写法，减少「模型写了语法但前端不认」或「能渲染但模型不知道」的错位。

验收：

1. 普通 GFM（标题、列表、表格、代码、引用、链接等）观感不回退。
2. 任务列表、删除线、脚注、定义列表、`::: tip|info|warning|danger|details` 可正确渲染。
3. 围栏代码块有语言角标、Shiki 高亮、一键复制。
4. `$...$` / `$$...$$`（及约定的块级写法）经 KaTeX 渲染；失败时降级为源码。
5. ` ```mermaid ` 可渲染 mindmap 与约定常用图；失败时降级为源码 + 简短提示。
6. 导出回复中文件名仍可点击下载（`#ds-export:` + 鉴权 blob）。
7. 系统提示含排版说明后，模型在「请画思维导图 / 写公式」类请求下会主动使用对应语法（以提示词 + 抽样人工验收为准）。

---

## 2. 非目标

- 所见即所得 Markdown 编辑器（员工输入区不改）。
- 把 Mermaid / 公式结果持久化为图片附件。
- 任务列表勾选写回历史消息或后端。
- 任意 HTML 原样透出；一切仍经 DOMPurify（或等价）消毒。
- 一期不做：PlantUML、Graphviz、完整 slide 主题、暗色双主题包全量语言。

---

## 3. 架构

```
助手正文
  → markdownSource（剥 <think> / 危险残片）
  → linkifyExportFilename（业务下载锚点）
  → markdown-it（GFM + 任务列表 / 脚注 / 容器等）
  → 后处理（仅非 streaming 完整态）：
       · 代码块 → Shiki + 复制按钮外壳
       · math → KaTeX
       · ```mermaid → Mermaid（失败回退源码）
  → DOMPurify（放行 KaTeX / Mermaid 所需安全标签与 class）
  → AssistantMessage：v-html + 点击委托（导出下载 / 外链 / 复制）
```

### 3.1 前端模块边界（`oa-agent-chat`）

| 模块 | 职责 |
|------|------|
| `src/chat/markdown/index.ts` | 对外 `renderMarkdown(content, options?)`；兼容旧导入路径可 re-export |
| `src/chat/markdown/parse.ts` | `markdown-it` 实例与插件装配 |
| `src/chat/markdown/enhance.ts` | Shiki / KaTeX / Mermaid 后处理；动态 import |
| `src/chat/markdown/sanitize.ts` | DOMPurify 配置（白名单） |
| `src/chat/markdown/source.ts` | 现有 `markdownSource` 逻辑迁入 |
| `delivery.ts` | 继续负责 `linkifyExportFilename` / `parseExportDownloadHref`（业务，不进解析器内核） |
| `AssistantMessage.vue` | 样式、复制/灯箱交互；streaming 时跳过重增强 |

依赖（计划）：`markdown-it` 及插件（task-lists、footnote、deflist、container、attrs 等按需）、`shiki`、`katex`、`mermaid`、现有 `dompurify`；移除对 `marked` 的运行时依赖（测试同步改）。

### 3.2 后端模型知情（`oa-langGraph`）

在员工助手系统提示中增加固定短段「回复排版」（与现有 persona / 工具规则并列），说明：

- 回答使用 Markdown；复杂结构优先用表格、列表、任务列表。
- 行内/块级公式：`$...$`、`$$...$$`。
- 结构图 / 思维导图：用 ` ```mermaid `，优先 `mindmap`；流程用 `flowchart`，时序用 `sequenceDiagram` 等。
- 提示框：`::: tip|info|warning|danger` / `::: details 标题`。
- **不要**为了排版编造业务数据；办公明细仍以系统表格/工具结果为准。
- 控制长度：示例各 1 个极简样例，避免提示膨胀。

注入点：与现有 `DEFAULT_PERSONA` / 组装 system 消息的同一路径（`oa_assistant.py` 或抽取的 prompt 常量），保证 chat / help 等员工可见通道都能读到。

---

## 4. 语法与展示明细

### 4.1 解析层

- 保留并加强 GFM：标题、强调、列表、表格、引用、链接、图片、水平线、围栏代码
- 任务列表、删除线、脚注、定义列表、更好的自动链接
- 容器：`::: tip|info|warning|danger` … `:::`；`::: details 标题` … `:::`

### 4.2 展示层

- 代码：Shiki 高亮 + 语言角标 + 复制
- 表格：横向滚动、表头区分
- 图片：最大宽度、圆角；点击轻量放大
- 容器：色条 + 简短标签区
- 外链：`target=_blank` + `rel=noopener noreferrer`

### 4.3 公式

- KaTeX；行内 `$...$`、块级 `$$...$$`（与 markdown-it 数学插件约定一致）
- 金额歧义：单个裸 `$` 后跟数字（如 `报销 $12.5`）不按公式切开；仅成对 `$...$` / `$$...$$` 进入 KaTeX（插件或预处理按此规则配置）
- 解析失败：保留原文，不打断整段

### 4.4 Mermaid

- 一期明确开启并验收：`mindmap`、`flowchart`（含 `graph`）、`sequenceDiagram`、`classDiagram`、`stateDiagram-v2`、`erDiagram`、`gantt`
- 其它 Mermaid 图类型：能渲染则展示，不做单独验收；渲染失败走统一降级
- 安全：仅渲染文本源；输出 SVG 再消毒；使用 `securityLevel: 'strict'`（或当前 Mermaid 大版本等价安全项）
- 失败 / 超时：原始代码块 +「图表渲染失败」

### 4.5 业务保留

- `linkifyExportFilename` + 回答内点击 → `downloadExportFile`
- 剥 `<think>` 行为不变

---

## 5. 流式、性能与安全

**流式（D5）**  
streaming 中：只做 markdown-it 基础 HTML（或继续轻量路径），不跑 Shiki/KaTeX/Mermaid。结束后对最终正文跑完整管道，避免半截公式/图报错闪烁。

**性能**  
Shiki 语言包、Mermaid、KaTeX 按需动态 import；同 `message.id + text` 可 memo 渲染结果。

**安全**  
- DOMPurify 白名单覆盖 KaTeX / Mermaid 所需标签与 class，禁止 script / 事件处理器 / `javascript:`  
- Mermaid 使用官方推荐的安全配置（如 `securityLevel: 'strict'` 或当前版等价项）  
- 用户/模型文本不信任；导出票据仍只来自结构化 `data.kind=file`，不从任意链接信任

---

## 6. 测试与验收

**前端单测**

- `markdownSource`、容器/任务列表/脚注关键 HTML 节点
- 含 `$a^2$`、` ```mermaid` + `mindmap`、`::: tip` 的渲染断言
- 消毒后无 `script`；导出 linkify 回归
- 增强失败降级（mock KaTeX/Mermaid throw）

**后端**

- 系统提示组装测试：断言含「回复排版」关键词与 mermaid / 公式提示片段（不要求全文快照过脆）

**手工**

- 普通问答、带表、带导出下载
- 「画一个关于报销流程的思维导图」「用公式表示 …」抽样看模型是否用约定语法且前端可渲染

---

## 7. 风险与缓解

| 风险 | 缓解 |
|------|------|
| 包体变大 | 动态 import；不预置全量 Shiki 主题/语言 |
| Mermaid 卡住 UI | 超时 / try-catch；流式结束后再渲染 |
| 提示词变长影响工具选择 | 排版段短小、示例极简；放在固定区块末尾或独立小节 |
| DOMPurify 误杀 SVG/公式 | 单测锁白名单；失败时降级源码而非空白 |

---

## 8. 实现顺序（概要）

1. `oa-agent-chat`：搭 `markdown/` 模块，markdown-it + 消毒 + 样式，替换 `marked`
2. 增强：Shiki 复制 → KaTeX → Mermaid；streaming 门闸
3. `AssistantMessage` 样式与交互
4. `oa-langGraph`：系统提示「回复排版」+ 单测
5. 回归导出下载与全量 vitest / 相关后端测试

详细步骤在用户审阅本规格通过后，写入 `docs/superpowers/plans/2026-11-24-chat-markdown-rich-rendering.md`。
