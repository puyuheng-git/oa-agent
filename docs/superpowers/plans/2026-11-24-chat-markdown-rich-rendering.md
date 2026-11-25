# 员工对话 Markdown 富渲染 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将助手回复 Markdown 升级为 `markdown-it` 富渲染（任务列表/容器/公式/Mermaid/代码高亮等），并在系统提示中告知模型可用写法；保留导出文件名点击下载。

**Architecture:** 前端把 `marked` 换成 `markdown-it` 插件栈；基础渲染同步，Shiki/KaTeX/Mermaid 在非 streaming 时异步增强；DOMPurify 消毒。后端在 `AGENT_PROMPT` 组装路径追加短「回复排版」段。

**Tech Stack:** Vue 3 / Vitest / `markdown-it` + 插件 / Shiki / KaTeX / Mermaid / DOMPurify；后端 Python pytest / `oa_assistant.py` 提示常量。

**Spec:** [`docs/superpowers/specs/2026-11-24-chat-markdown-rich-rendering-design.md`](../specs/2026-11-24-chat-markdown-rich-rendering-design.md)

## Global Constraints

- 双仓库：前端 `E:\python_project\oa-agent-chat`；后端/规格本仓 `E:\python_project\oa-langGraph`。
- 流式中只做基础 Markdown；`streaming === true` 时不跑 Shiki/KaTeX/Mermaid（D5）。
- 任务列表仅展示，不回写服务端（D6）。
- 导出 `#ds-export:` 下载逻辑保留在 `delivery.ts` + `AssistantMessage`。
- 金额：不成对的裸 `$12` 不当公式；仅成对 `$...$` / `$$...$$`。
- Mermaid 一期验收：`mindmap`、`flowchart`/`graph`、`sequenceDiagram`、`classDiagram`、`stateDiagram-v2`、`erDiagram`、`gantt`；`securityLevel: 'strict'`。
- **Commit 仅在用户明确要求时执行**；计划中的 commit 步骤默认跳过。
- 前端测试：`npm test`（cwd = oa-agent-chat）。后端测试：`uv run pytest … -v`（cwd = oa-langGraph/backend）。

---

## File map

| 文件 | 职责 |
|------|------|
| `oa-agent-chat/src/chat/markdown/source.ts` | 迁入并导出 `markdownSource` |
| `oa-agent-chat/src/chat/markdown/sanitize.ts` | DOMPurify 白名单 |
| `oa-agent-chat/src/chat/markdown/parse.ts` | markdown-it 实例 + 插件 |
| `oa-agent-chat/src/chat/markdown/enhance.ts` | Shiki / KaTeX / Mermaid 后处理（动态 import） |
| `oa-agent-chat/src/chat/markdown/index.ts` | `renderMarkdown` / `renderMarkdownEnhanced` |
| `oa-agent-chat/src/chat/markdown.ts` | 薄 re-export，兼容旧 import |
| `oa-agent-chat/src/chat/markdown/*.spec.ts` | 单元测试 |
| `oa-agent-chat/src/chat/components/AssistantMessage.vue` | 异步增强、复制/灯箱、样式 |
| `oa-agent-chat/package.json` | 依赖变更（去 `marked`，加新库） |
| `oa-langGraph/backend/oa_agent/runtime/graphs/oa_assistant.py` | `REPLY_FORMAT_PROMPT` 注入 system |
| `oa-langGraph/backend/tests/test_reply_format_prompt.py` | 断言提示含排版关键词 |

---

### Task 1: 脚手架 — `markdownSource` + 消毒 + markdown-it 基础渲染（替换 marked）

**Files:**
- Create: `oa-agent-chat/src/chat/markdown/source.ts`
- Create: `oa-agent-chat/src/chat/markdown/sanitize.ts`
- Create: `oa-agent-chat/src/chat/markdown/parse.ts`
- Create: `oa-agent-chat/src/chat/markdown/index.ts`
- Create: `oa-agent-chat/src/chat/markdown/markdown.spec.ts`
- Modify: `oa-agent-chat/src/chat/markdown.ts` → re-export
- Modify: `oa-agent-chat/package.json` — 添加 `markdown-it`、`@types/markdown-it`；后续任务再加其余依赖。本任务可先只加 `markdown-it`。

**Interfaces:**
- Produces:
  - `markdownSource(content: string): string`
  - `sanitizeHtml(html: string): string`
  - `parseMarkdown(src: string): string` — markdown-it → HTML（未消毒）
  - `renderMarkdown(content: string): string` — source → parse → sanitize（同步、无增强）
- Consumes: 无

- [ ] **Step 1: 安装 markdown-it**

```bash
cd E:\python_project\oa-agent-chat
npm install markdown-it
npm install -D @types/markdown-it
```

- [ ] **Step 2: 写失败测试**

```ts
// src/chat/markdown/markdown.spec.ts
import { describe, expect, it } from 'vitest'
import { markdownSource, renderMarkdown } from './index'

describe('markdown basics', () => {
  it('剥 think 标签保留正文 Markdown', () => {
    expect(markdownSource('<think>x</think>**你好**')).toBe('**你好**')
  })

  it('渲染标题与粗体且无 script', () => {
    const html = renderMarkdown('# 标题\n\n**粗** <script>alert(1)</script>')
    expect(html).toContain('<h1')
    expect(html).toContain('<strong>')
    expect(html).not.toMatch(/<script/i)
  })

  it('GFM 表格', () => {
    const html = renderMarkdown('| a | b |\n| --- | --- |\n| 1 | 2 |')
    expect(html).toContain('<table')
    expect(html).toContain('<td')
  })
})
```

- [ ] **Step 3: 跑测试确认失败**

Run: `npm test -- src/chat/markdown/markdown.spec.ts`  
Expected: FAIL（模块不存在或仍走旧 marked 路径未满足结构）

- [ ] **Step 4: 实现 source / sanitize / parse / index**

```ts
// source.ts — 从旧 markdown.ts 迁入 markdownSource，行为保持一致

// sanitize.ts
import DOMPurify from 'dompurify'
export function sanitizeHtml(html: string): string {
  return DOMPurify.sanitize(html, { USE_PROFILES: { html: true } })
}

// parse.ts
import MarkdownIt from 'markdown-it'
const md = new MarkdownIt({ html: false, linkify: true, breaks: true })
export function parseMarkdown(src: string): string {
  return md.render(src)
}

// index.ts
import { markdownSource } from './source'
import { parseMarkdown } from './parse'
import { sanitizeHtml } from './sanitize'
export { markdownSource } from './source'
export function renderMarkdown(content: string): string {
  const src = markdownSource(content)
  if (!src) return ''
  return sanitizeHtml(parseMarkdown(src))
}
```

```ts
// markdown.ts（根）
export { markdownSource, renderMarkdown } from './markdown/index'
```

- [ ] **Step 5: 卸载 marked，跑测试通过**

```bash
npm uninstall marked
npm test -- src/chat/markdown/markdown.spec.ts
```

Expected: PASS

- [ ] **Step 6: Commit（仅用户要求时）**

```bash
git add src/chat/markdown src/chat/markdown.ts package.json package-lock.json
git commit -m "feat(chat): replace marked with markdown-it base renderer"
```

---

### Task 2: 语法插件 — 任务列表、删除线、脚注、定义列表、容器

**Files:**
- Modify: `oa-agent-chat/src/chat/markdown/parse.ts`
- Modify: `oa-agent-chat/src/chat/markdown/markdown.spec.ts`
- Modify: `oa-agent-chat/package.json`

**Interfaces:**
- Consumes: Task 1 的 `parseMarkdown` / `renderMarkdown`
- Produces: 同一 API；HTML 中出现 task checkbox、`del`、footnote、`dl`、`.md-container` 类

- [ ] **Step 1: 安装插件**

```bash
cd E:\python_project\oa-agent-chat
npm install markdown-it-task-lists markdown-it-footnote markdown-it-deflist markdown-it-container
```

（删除线：markdown-it 启用 `typographer` 不够；用内置 `strikethrough` —— `MarkdownIt` 默认启用 `strikethrough` 规则，确认 `~~a~~` → `<s>`。）

- [ ] **Step 2: 写失败测试（追加到 markdown.spec.ts）**

```ts
it('任务列表与删除线', () => {
  const html = renderMarkdown('- [ ] 待办\n- [x] 完成\n\n~~旧~~')
  expect(html).toMatch(/checkbox|task-list|type="checkbox"/i)
  expect(html).toMatch(/<s>|<del>/i)
})

it('脚注与定义列表', () => {
  const html = renderMarkdown('注[^1]\n\n[^1]: 说明\n\n术语\n: 定义')
  expect(html).toMatch(/footnote|fn-/i)
  expect(html).toContain('<dl')
})

it('tip 容器', () => {
  const html = renderMarkdown('::: tip\n注意\n:::')
  expect(html).toMatch(/tip|md-container/i)
  expect(html).toContain('注意')
})
```

- [ ] **Step 3: 跑测试确认失败**

Run: `npm test -- src/chat/markdown/markdown.spec.ts`  
Expected: FAIL on new cases

- [ ] **Step 4: 装配插件**

在 `parse.ts` 中：

```ts
import MarkdownIt from 'markdown-it'
import taskLists from 'markdown-it-task-lists'
import footnote from 'markdown-it-footnote'
import deflist from 'markdown-it-deflist'
import markdownItContainer from 'markdown-it-container'

const md = new MarkdownIt({ html: false, linkify: true, breaks: true })
md.use(taskLists, { enabled: true, label: true })
md.use(footnote)
md.use(deflist)

function addContainer(name: string) {
  md.use(markdownItContainer, name, {
    render(tokens: any[], idx: number) {
      if (tokens[idx].nesting === 1) {
        return `<div class="md-container md-container--${name}" data-kind="${name}"><div class="md-container__body">\n`
      }
      return `</div></div>\n`
    },
  })
}
;['tip', 'info', 'warning', 'danger', 'details'].forEach(addContainer)
```

`details`：若要用 `<details><summary>`，为本任务单独 `markdownItContainer` 配置，从 info 字符串取标题；否则先与 tip 同结构，Task 7 再换成原生 details。

- [ ] **Step 5: 跑测试通过**

Run: `npm test -- src/chat/markdown/markdown.spec.ts`  
Expected: PASS

- [ ] **Step 6: Commit（仅用户要求时）**

---

### Task 3: 外链安全改写 + 消毒白名单扩展

**Files:**
- Modify: `oa-agent-chat/src/chat/markdown/parse.ts` — 自定义 `link_open` 规则
- Modify: `oa-agent-chat/src/chat/markdown/sanitize.ts`
- Modify: `oa-agent-chat/src/chat/markdown/markdown.spec.ts`

**Interfaces:**
- Produces: 外链带 `target="_blank" rel="noopener noreferrer"`；`javascript:` 被拒绝或剥离

- [ ] **Step 1: 写失败测试**

```ts
it('外链 noopener，拒绝 javascript', () => {
  const ok = renderMarkdown('[开](https://example.com)')
  expect(ok).toContain('noopener')
  expect(ok).toContain('_blank')
  const bad = renderMarkdown('[x](javascript:alert(1))')
  expect(bad).not.toMatch(/javascript:/i)
})
```

- [ ] **Step 2: 实现 link 规则 + sanitize ADD_ATTR**

```ts
// parse.ts link_open renderer: 非 # / 相对 的 http(s) 链接加 target/rel；javascript: 改成 # 或去掉 href
// sanitize.ts: ADD_ATTR: ['target', 'rel', 'class', 'data-kind']
```

- [ ] **Step 3: 测试通过**

---

### Task 4: 异步增强管道骨架 + Shiki 代码高亮与复制外壳

**Files:**
- Create: `oa-agent-chat/src/chat/markdown/enhance.ts`
- Modify: `oa-agent-chat/src/chat/markdown/index.ts`
- Modify: `oa-agent-chat/src/chat/markdown/sanitize.ts` — 允许 `pre/code` 的 shiki class
- Create: `oa-agent-chat/src/chat/markdown/enhance.spec.ts`
- Modify: `package.json` — `shiki`

**Interfaces:**
- Produces:
  - `renderMarkdownEnhanced(content: string): Promise<string>`
  - `enhanceHtml(html: string): Promise<string>` — 对已 parse 的 HTML 做代码块增强
- Consumes: `renderMarkdown` 的同步路径逻辑（先 parse+sanitize 基础，再 enhance，再 sanitize）

- [ ] **Step 1: 安装 shiki**

```bash
npm install shiki
```

- [ ] **Step 2: 写失败测试**

```ts
import { describe, expect, it } from 'vitest'
import { renderMarkdownEnhanced } from './index'

describe('enhance code', () => {
  it('代码块带复制按钮与高亮 class 或 style', async () => {
    const html = await renderMarkdownEnhanced('```ts\nconst a = 1\n```')
    expect(html).toMatch(/md-code|复制|data-lang|shiki|foreground/i)
    expect(html).toContain('const')
  })
})
```

- [ ] **Step 3: 实现 enhance（动态 import shiki）**

对 HTML 中 `pre code`：包一层 `.md-code`，加 `data-lang`、button.`.md-code__copy`（文案「复制」），用 Shiki `codeToHtml` 替换内部；未知语言 catch 后保留原文。最后再 `sanitizeHtml`。

`index.ts`:

```ts
export async function renderMarkdownEnhanced(content: string): Promise<string> {
  const src = markdownSource(content)
  if (!src) return ''
  const base = sanitizeHtml(parseMarkdown(src))
  const enhanced = await enhanceHtml(base)
  return sanitizeHtml(enhanced)
}
```

- [ ] **Step 4: 测试通过**

---

### Task 5: KaTeX 公式

**Files:**
- Modify: `oa-agent-chat/src/chat/markdown/parse.ts` 或 `enhance.ts`（二选一：插件出 math 占位，enhance 调 KaTeX）
- Modify: `oa-agent-chat/src/chat/markdown/sanitize.ts` — 放行 `.katex` 相关标签/class
- Modify: `oa-agent-chat/src/chat/markdown/enhance.spec.ts` 或 `markdown.spec.ts`
- Modify: `package.json` — `katex`、数学插件（推荐 `markdown-it-texmath` + katex，或 `@traptitech/markdown-it-katex`）

**Interfaces:**
- 行内 `$a^2$`、块级 `$$\nE=mc^2\n$$` 进入 KaTeX HTML
- 裸 `$12.5` 不切开

- [ ] **Step 1: 安装**

```bash
npm install katex markdown-it-texmath
```

（若 texmath API 不合，改用 `@traptitech/markdown-it-katex`，测试断言不变。）

- [ ] **Step 2: 写失败测试**

```ts
it('行内与块级公式', async () => {
  const html = await renderMarkdownEnhanced('面积 $a^2$ \n\n$$\nE=mc^2\n$$')
  expect(html).toMatch(/katex/i)
  expect(html).not.toContain('<script')
})

it('裸货币不按公式', async () => {
  const html = await renderMarkdownEnhanced('报销 $12.5 元')
  expect(html).toContain('$12.5')
  expect(html).not.toMatch(/katex/i)
})
```

- [ ] **Step 3: 配置 delimiters + 失败降级（try/catch 保留源码）**

- [ ] **Step 4: 测试通过；在 `AssistantMessage` 或全局引入 `katex/dist/katex.min.css`（main 或组件 import）**

---

### Task 6: Mermaid（含 mindmap）

**Files:**
- Modify: `oa-agent-chat/src/chat/markdown/enhance.ts`
- Modify: `oa-agent-chat/src/chat/markdown/sanitize.ts` — SVG 安全子集
- Modify: `oa-agent-chat/src/chat/markdown/enhance.spec.ts`
- Modify: `package.json` — `mermaid`

**Interfaces:**
- ` ```mermaid ` 代码块渲染为 SVG，外包 `.md-mermaid`
- 失败时保留代码块并加 `.md-mermaid__error` 文案「图表渲染失败」

- [ ] **Step 1: 安装**

```bash
npm install mermaid
```

- [ ] **Step 2: 写失败测试**

```ts
it('渲染 mindmap', async () => {
  const src = '```mermaid\nmindmap\n  root((报销))\n    行程\n    金额\n```'
  const html = await renderMarkdownEnhanced(src)
  expect(html).toMatch(/svg|md-mermaid/i)
})

it('非法 mermaid 降级', async () => {
  const html = await renderMarkdownEnhanced('```mermaid\nnot_a_diagram@@@\n```')
  expect(html).toMatch(/图表渲染失败|md-mermaid__error|```|mermaid/i)
})
```

- [ ] **Step 3: enhance 中识别 language=mermaid；`mermaid.initialize({ securityLevel: 'strict', startOnLoad: false })`；`mermaid.render(id, text)`；超时用 `Promise.race`（如 3s）**

- [ ] **Step 4: 测试通过**

---

### Task 7: AssistantMessage — streaming 门闸、异步渲染、复制点击、样式

**Files:**
- Modify: `oa-agent-chat/src/chat/components/AssistantMessage.vue`
- Modify: 可选抽 `oa-agent-chat/src/chat/markdown/markdown.css` 或继续 scoped `:deep`

**Interfaces:**
- Consumes: `renderMarkdown`（streaming）、`renderMarkdownEnhanced`（完成后）
- 保留 `onAnswerClick` 导出下载；扩展点击：`.md-code__copy` → clipboard

- [ ] **Step 1: 将 `answerHtml` 从纯 computed 改为 `ref` + `watch`**

```ts
import { computed, ref, watch } from 'vue'
import { renderMarkdown, renderMarkdownEnhanced } from '../markdown'

const answerHtml = ref('')
watch(
  () => [props.message.text, props.message.streaming, exportFile.value?.exportTicket, exportFile.value?.name] as const,
  async ([text, streaming, ticket, name]) => {
    const raw = text || ''
    const linked = ticket ? linkifyExportFilename(raw, name || '', ticket) : raw
    if (streaming) {
      answerHtml.value = renderMarkdown(linked)
      return
    }
    answerHtml.value = renderMarkdown(linked) // 先即时基础态
    answerHtml.value = await renderMarkdownEnhanced(linked)
  },
  { immediate: true },
)
```

- [ ] **Step 2: `onAnswerClick` 增加复制按钮分支**

```ts
const copyBtn = el.closest('.md-code__copy')
if (copyBtn instanceof HTMLElement) {
  e.preventDefault()
  const pre = copyBtn.closest('.md-code')?.querySelector('code, pre')
  const t = pre?.textContent || ''
  try {
    await navigator.clipboard.writeText(t)
    ElMessage.success('已复制代码')
  } catch {
    ElMessage.error('复制失败')
  }
  return
}
```

- [ ] **Step 3: 补充 `:deep` 样式** — `.md-container--*`、`.md-code`、`.md-mermaid`、task-list、footnote、`img` max-width、katex 溢出滚动

- [ ] **Step 4: 手工或组件级确认：streaming 时无长时间卡住；结束后公式/图出现**

- [ ] **Step 5: `npm test` 全量通过**

---

### Task 8: 图片灯箱（轻量）

**Files:**
- Modify: `oa-agent-chat/src/chat/components/AssistantMessage.vue`

- [ ] **Step 1: 点击 `.md img` 时 `preventDefault`，用 `ref` 打开简单全屏遮罩显示同 src；点击遮罩关闭**
- [ ] **Step 2: 样式：图片 `max-width:100%; border-radius:8px; cursor:zoom-in`**

（不做相册、不做双指缩放。）

---

### Task 9: 后端 — 模型「回复排版」提示

**Files:**
- Modify: `oa-langGraph/backend/oa_agent/runtime/graphs/oa_assistant.py`
- Create: `oa-langGraph/backend/tests/test_reply_format_prompt.py`

**Interfaces:**
- Produces: 常量 `REPLY_FORMAT_PROMPT: str`；在 `allow_chat` 组装 `prompt = AGENT_PROMPT.format(...)` 之后、`_with_export_hint` 前后追加 `prompt += REPLY_FORMAT_PROMPT`（或 format 进 AGENT_PROMPT 新占位符 `{reply_format}`）

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/test_reply_format_prompt.py
from oa_agent.runtime.graphs import oa_assistant as m

def test_reply_format_prompt_mentions_mermaid_and_math():
    text = m.REPLY_FORMAT_PROMPT
    assert "mermaid" in text.lower()
    assert "mindmap" in text.lower()
    assert "$" in text or "公式" in text
    assert ":::" in text or "tip" in text.lower()


def test_agent_prompt_assembly_includes_reply_format(monkeypatch):
    # 若有现成 understand/prompt 单测夹具则复用；否则至少断言
    # AGENT_PROMPT 模板含 {reply_format} 或模块在拼接函数中使用 REPLY_FORMAT_PROMPT
    assert "REPLY_FORMAT_PROMPT" in open(m.__file__, encoding="utf-8").read() or hasattr(m, "REPLY_FORMAT_PROMPT")
```

更稳妥：抽出纯函数 `def build_system_prompt_for_test(...)-> str` 仅当改动小；否则断言常量内容 + 源码中 `prompt` 拼接包含 `REPLY_FORMAT_PROMPT`：

```python
def test_reply_format_wired_into_oa_assistant_source():
    src = open(m.__file__, encoding="utf-8").read()
    assert "REPLY_FORMAT_PROMPT" in src
    assert "回复排版" in m.REPLY_FORMAT_PROMPT
```

- [ ] **Step 2: 跑测失败**

```bash
cd E:\python_project\oa-langGraph\backend
uv run pytest tests/test_reply_format_prompt.py -v
```

- [ ] **Step 3: 实现常量（短小）**

```python
REPLY_FORMAT_PROMPT = """
## 回复排版
给员工的 reply 使用 Markdown。需要时主动使用：
- 公式：行内 `$a^2$`，块级 `$$...$$`
- 结构图/思维导图：用 mermaid 围栏；思维导图用 `mindmap`，流程用 `flowchart`，时序用 `sequenceDiagram`
- 提示：`::: tip` / `::: warning` / `::: danger`；折叠用 `::: details 标题`
- 任务列表、表格整理步骤或对比
不要为排版编造 OA 业务数据；明细以工具/系统表格为准。
"""
```

在 `allow_chat` 分支 `prompt = AGENT_PROMPT.format(...)` 后：`prompt += REPLY_FORMAT_PROMPT`。

- [ ] **Step 4: 测试通过**

```bash
uv run pytest tests/test_reply_format_prompt.py -v
```

---

### Task 10: 回归与收尾

**Files:**
- Modify: 任何仍引用 `marked` 的文件清掉
- Verify: `delivery.spec.ts`、全量前端测试、导出下载手工路径

- [ ] **Step 1: 前端**

```bash
cd E:\python_project\oa-agent-chat
npm test
npm run build
```

Expected: 测试全绿；`vue-tsc` + build 成功。

- [ ] **Step 2: 后端相关测**

```bash
cd E:\python_project\oa-langGraph\backend
uv run pytest tests/test_reply_format_prompt.py -v
```

- [ ] **Step 3: 手工清单**
  - 普通 Markdown 回答
  - 导出文件名可下载
  - 粘贴含 mindmap / 公式的助手回复（或临时 mock）能渲染
  - streaming 过程不因半截 `$$` 报错刷屏

- [ ] **Step 4: 将规格状态改为已确认（若尚未）**

`docs/superpowers/specs/2026-11-24-chat-markdown-rich-rendering-design.md` 状态 → **已确认**

- [ ] **Step 5: Commit（仅用户要求时）** — 分前端仓 / 后端仓分别提交

---

## Spec coverage checklist

| 规格项 | 任务 |
|--------|------|
| markdown-it 替换 marked | T1 |
| 任务列表/删除线/脚注/定义列表/容器 | T2 |
| 外链 noopener + 消毒 | T3 |
| Shiki + 复制 | T4、T7 |
| KaTeX + 货币歧义 | T5 |
| Mermaid mindmap 等 + strict + 降级 | T6 |
| 流式门闸 D5 | T7 |
| 图片灯箱 | T8 |
| 导出下载保留 | T7（不改 delivery 契约）+ T10 |
| 模型知情提示 | T9 |
| 动态 import / 性能 | T4–T6 |
| 单测与 build 回归 | T1–T6、T10 |

## Placeholder / 一致性自检

- 无 TBD；`renderMarkdown` / `renderMarkdownEnhanced` 命名在 T1/T4/T7 一致。
- `REPLY_FORMAT_PROMPT` 在 T9 定义并注入。
- Commit 步骤受 Global Constraints 约束，默认跳过。
