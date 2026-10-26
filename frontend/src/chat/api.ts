import { ApiError, newIdempotencyKey, request } from '../shared/http'

/** 管理后台配置的可用能力，用于欢迎页。 */
export interface SkillMenuItem {
  name: string
  display_name: string
  description: string
  examples: string[]
  /** Skill 首次入库时间（ISO）；欢迎示例只展示近三天新加的。 */
  created_at?: string | null
  /** 该 Skill 依赖 Tool 中最近一次「首次入库」时间（ISO）。 */
  newest_tool_created_at?: string | null
}

export interface ChatSessionInfo {
  ticket: string
  expires_in: number
  display_name: string
  thread_id: string
  skills?: SkillMenuItem[]
  /** 是否支持日常聊天（发布配置允许且有可用模型）。 */
  chat?: boolean
  /** 以下来自后台「配置中心」。 */
  message_max_chars?: number
  poll_interval_seconds?: number
  poll_max_minutes?: number
}

export type DataRow = Record<string, unknown>

export interface DataColumn {
  key: string
  label: string
}

/** 结构化结果：列名/字段名来自 Tool 配置，页面不写死业务字段。 */
export type ReplyData =
  | { kind: 'table'; tool: string; title: string; columns: DataColumn[]; items: DataRow[]; total: number | null }
  | { kind: 'record'; tool: string; title: string; fields: DataColumn[]; item: DataRow }
  | null

export interface Reply {
  type: 'markdown' | 'text' | 'error' | 'pending'
  content: string
  data: ReplyData
  error_code?: string
  /** 业务系统随结果返回的提示语 */
  notice?: string
  /** 多步查询依次调用的 Tool */
  chain?: string[]
}

export interface MessageResult {
  run_id: string
  thread_id: string
  run_status: string
  reply: Reply
}

export interface ChatThreadItem {
  thread_id: string
  title: string | null
  status: 'active' | 'archived'
  created_channel: string
  last_channel: string | null
  pinned: boolean
  created_at: string
  updated_at: string
  last_message_at: string | null
}

export interface ThreadListResponse {
  items: ChatThreadItem[]
  page: number
  page_size: number
  total: number
}

export interface ThreadMessageItem {
  message_id: string
  role: 'user' | 'assistant'
  content: string
  reply_type: string | null
  data: unknown
  error_code?: string | null
  created_at: string
  run_id: string | null
}

export interface ThreadMessagesResponse {
  items: ThreadMessageItem[]
  page: number
  page_size: number
  total: number
}

export interface SwitchThreadResult {
  thread_id: string
  skills?: SkillMenuItem[]
  chat?: boolean
  message_max_chars?: number
  poll_interval_seconds?: number
  poll_max_minutes?: number
}

export interface MappedChatMessage {
  id: string
  role: 'user' | 'assistant'
  text: string
  reply?: Reply
  runId?: string
  createdAt: number
}

// ticket 只放内存：刷新页面即失效，需要从 OA 重新进入
let ticket = ''

export function hasTicket(): boolean {
  return ticket !== ''
}

export function clearTicket() {
  ticket = ''
}

/** 读取 ?launch= 并立即从地址栏移除，避免被历史记录、Referer 或截图带出。 */
export function takeLaunchCode(loc: Location = window.location, hist: History = window.history): string {
  const url = new URL(loc.href)
  const code = url.searchParams.get('launch') ?? ''
  if (code) {
    url.searchParams.delete('launch')
    hist.replaceState(null, '', url.pathname + url.search + url.hash)
  }
  return code
}

function auth(): Record<string, string> {
  return ticket ? { Authorization: `Bearer ${ticket}` } : {}
}

export async function openSession(launchCode: string): Promise<ChatSessionInfo> {
  const s = await request<ChatSessionInfo>('POST', '/v1/chat/session', { launch_code: launchCode })
  ticket = s.ticket
  return s
}

export function refreshSession(): Promise<{ expires_in: number }> {
  return request('POST', '/v1/chat/session/refresh', {}, auth())
}

function clientMsgId(): string {
  return newIdempotencyKey().replace(/[^\w-]/g, '')
}

export function sendMessage(message: string): Promise<MessageResult> {
  return request('POST', '/v1/chat/messages', { message, client_msg_id: clientMsgId() }, auth())
}

export function listThreads(
  page = 1,
  pageSize = 50,
  status: 'active' | 'archived' = 'active',
): Promise<ThreadListResponse> {
  const q = new URLSearchParams({ page: String(page), page_size: String(pageSize), status })
  return request('GET', `/v1/chat/threads?${q}`, undefined, auth())
}

export function createThread(): Promise<ChatThreadItem> {
  return request('POST', '/v1/chat/threads', {}, auth())
}

export async function getThreadMessages(threadId: string): Promise<ThreadMessageItem[]> {
  const pageSize = 100
  let page = 1
  const all: ThreadMessageItem[] = []
  for (;;) {
    const q = new URLSearchParams({ page: String(page), page_size: String(pageSize) })
    const res = await request<ThreadMessagesResponse>(
      'GET',
      `/v1/chat/threads/${encodeURIComponent(threadId)}/messages?${q}`,
      undefined,
      auth(),
    )
    all.push(...res.items)
    if (all.length >= res.total || res.items.length < pageSize) break
    page += 1
  }
  return all
}

export function patchThread(
  threadId: string,
  body: { title?: string; status?: 'active' | 'archived' },
): Promise<ChatThreadItem> {
  return request('PATCH', `/v1/chat/threads/${encodeURIComponent(threadId)}`, body, auth())
}

export function deleteThread(threadId: string): Promise<{ ok: boolean }> {
  return request('DELETE', `/v1/chat/threads/${encodeURIComponent(threadId)}`, undefined, auth())
}

export function switchThread(threadId: string): Promise<SwitchThreadResult> {
  return request('POST', '/v1/chat/session/switch', { thread_id: threadId }, auth())
}

export type MemoryKind = 'preference' | 'constraint' | 'note'

export interface MemoryItem {
  memory_id: string
  kind: MemoryKind
  text: string
  created_at: string
  updated_at: string
}

export interface MemoryListResponse {
  items: MemoryItem[]
  total: number
  page: number
  page_size: number
}

export function listMemory(page = 1, pageSize = 100): Promise<MemoryListResponse> {
  const q = new URLSearchParams({ page: String(page), page_size: String(pageSize) })
  return request('GET', `/v1/chat/memory?${q}`, undefined, auth())
}

export function deleteMemory(memoryId: string): Promise<{ ok: boolean }> {
  return request('DELETE', `/v1/chat/memory/${encodeURIComponent(memoryId)}`, undefined, auth())
}

/** 一键清空本人 active 记忆；须传 confirm=true（与后端契约一致）。 */
export function clearMemory(confirm = true): Promise<{ ok: boolean; deleted: number }> {
  return request('DELETE', '/v1/chat/memory', { confirm }, auth())
}

/** 记忆 kind 展示文案 */
export function memoryKindLabel(kind: MemoryKind | string): string {
  const map: Record<string, string> = { preference: '偏好', constraint: '约束', note: '备注' }
  return map[kind] ?? kind
}

/** 侧栏展示：无 title 时显示「新会话」。 */
export function threadDisplayTitle(title: string | null | undefined): string {
  const t = (title ?? '').trim()
  return t || '新会话'
}

/** 相对时间（侧栏可选）；无法解析时返回空字符串。 */
export function formatRelativeTime(iso: string | null | undefined, nowMs: number = Date.now()): string {
  if (!iso) return ''
  const t = Date.parse(iso)
  if (Number.isNaN(t)) return ''
  const diff = Math.max(0, nowMs - t)
  const min = Math.floor(diff / 60_000)
  if (min < 1) return '刚刚'
  if (min < 60) return `${min} 分钟前`
  const hr = Math.floor(min / 60)
  if (hr < 24) return `${hr} 小时前`
  const day = Math.floor(hr / 24)
  if (day < 30) return `${day} 天前`
  return new Date(t).toLocaleDateString('zh-CN', { month: 'numeric', day: 'numeric' })
}

function threadMessageToReply(m: ThreadMessageItem): Reply {
  const type = (m.reply_type || 'text') as Reply['type']
  return {
    type,
    content: m.content,
    data: (m.data as ReplyData) ?? null,
    error_code: m.error_code ?? undefined,
  }
}

/** 将线程历史消息映射为对话区 Message 形状。 */
export function mapThreadMessages(items: ThreadMessageItem[]): MappedChatMessage[] {
  return items.map((m) => {
    const reply = m.role === 'assistant' ? threadMessageToReply(m) : undefined
    const text = m.role === 'user' ? m.content : plainText(reply?.content ?? m.content)
    return {
      id: m.message_id,
      role: m.role,
      text,
      reply,
      runId: m.run_id ?? undefined,
      createdAt: Date.parse(m.created_at) || Date.now(),
    }
  })
}

export interface SseEvent {
  event: string
  data: any
}

/** 解析 SSE 文本：返回完整的事件与尚未结束的剩余部分；注释行（心跳）忽略。 */
export function parseSse(buffer: string): { events: SseEvent[]; rest: string } {
  const blocks = buffer.replace(/\r\n/g, '\n').split('\n\n')
  const rest = blocks.pop() ?? ''
  const events: SseEvent[] = []
  for (const block of blocks) {
    let event = 'message'
    const data: string[] = []
    for (const line of block.split('\n')) {
      if (line.startsWith('event:')) event = line.slice(6).trim()
      else if (line.startsWith('data:')) data.push(line.slice(5).trimStart())
    }
    if (!data.length) continue
    try {
      events.push({ event, data: JSON.parse(data.join('\n')) })
    } catch {
      // 不完整或非 JSON 的数据块忽略
    }
  }
  return { events, rest }
}

export class StreamAbortedError extends Error {
  constructor() {
    super('已停止生成')
    this.name = 'StreamAbortedError'
  }
}

/** 流式发送：onDelta 收到回复正文的新增片段；返回与 sendMessage 相同的完整结果。可通过 signal 中止读取。 */
export async function sendMessageStream(
  message: string,
  onDelta: (piece: string) => void,
  signal?: AbortSignal,
): Promise<MessageResult> {
  try {
    const resp = await fetch('/v1/chat/messages/stream', {
      method: 'POST',
      headers: { Accept: 'text/event-stream', 'Content-Type': 'application/json', ...auth() },
      credentials: 'same-origin',
      body: JSON.stringify({ message, client_msg_id: clientMsgId() }),
      signal,
    })
    if (!resp.ok) {
      let err: any = null
      try {
        err = (await resp.json())?.error
      } catch {
        err = null
      }
      throw new ApiError(resp.status, err?.code ?? 'HTTP_ERROR', err?.message ?? `请求失败（HTTP ${resp.status}）`)
    }
    const box: { result: MessageResult | null } = { result: null }
    const handle = (events: SseEvent[]) => {
      for (const e of events) {
        if (e.event === 'delta' && typeof e.data?.text === 'string') onDelta(e.data.text)
        else if (e.event === 'done') box.result = e.data as MessageResult
        else if (e.event === 'error') throw new ApiError(500, e.data?.code ?? 'STREAM_ERROR', e.data?.message ?? '处理失败')
      }
    }
    let buffer = ''
    if (resp.body?.getReader) {
      const reader = resp.body.getReader()
      const decoder = new TextDecoder()
      for (;;) {
        if (signal?.aborted) throw new StreamAbortedError()
        const { value, done } = await reader.read()
        if (done) break
        const parsed = parseSse(buffer + decoder.decode(value, { stream: true }))
        buffer = parsed.rest
        handle(parsed.events)
      }
      buffer += decoder.decode()
    } else {
      buffer = await resp.text()
    }
    handle(parseSse(buffer + '\n\n').events)
    if (!box.result) throw new Error('连接中断，未收到完整结果，请稍后重新提问')
    return box.result
  } catch (e) {
    if (e instanceof StreamAbortedError) throw e
    if (signal?.aborted || (e as Error)?.name === 'AbortError') throw new StreamAbortedError()
    throw e
  }
}

export interface RunResult {
  run_id: string
  run_status: string
  done: boolean
  reply: Reply | null
}

/** 转人工后轮询本人运行的结果。 */
export function getRun(runId: string): Promise<RunResult> {
  return request('GET', `/v1/chat/runs/${encodeURIComponent(runId)}`, undefined, auth())
}

/** 会话未返回配置时的默认值：每 5 秒轮询；介入任务默认 30 分钟过期，多留 5 分钟余量后停止。 */
export const POLL_INTERVAL_MS = 5000
export const POLL_MAX_MS = 35 * 60 * 1000

export function pollSettings(s: Pick<ChatSessionInfo, 'poll_interval_seconds' | 'poll_max_minutes'>) {
  return {
    intervalMs: s.poll_interval_seconds ? s.poll_interval_seconds * 1000 : POLL_INTERVAL_MS,
    maxMs: s.poll_max_minutes ? s.poll_max_minutes * 60 * 1000 : POLL_MAX_MS,
  }
}

/** 在过期前 2 分钟续期，最短 30 秒。 */
export function refreshDelayMs(expiresIn: number): number {
  return Math.max(30, expiresIn - 120) * 1000
}

const THREE_DAYS_MS = 3 * 24 * 60 * 60 * 1000

/** Skill 或其依赖 Tool 是否在近三天内新加。 */
export function isRecentSkillOrTool(s: SkillMenuItem, nowMs: number = Date.now()): boolean {
  for (const raw of [s.created_at, s.newest_tool_created_at]) {
    if (!raw) continue
    const t = Date.parse(raw)
    if (!Number.isNaN(t) && nowMs - t <= THREE_DAYS_MS && nowMs - t >= -60_000) return true
  }
  return false
}

/** 欢迎页示例：仅近三天新加的 Skill/Tool；每个 Skill 先取一条再轮流补齐，最多 max 条。 */
export function welcomeExamples(skills: SkillMenuItem[], max = 6, nowMs: number = Date.now()): string[] {
  const recent = skills.filter((s) => isRecentSkillOrTool(s, nowMs))
  const out: string[] = []
  const depth = Math.max(0, ...recent.map((s) => s.examples.length))
  for (let i = 0; i < depth && out.length < max; i++) {
    for (const s of recent) {
      const ex = s.examples[i]
      if (ex && !out.includes(ex) && out.length < max) out.push(ex)
    }
  }
  return out
}

/** 单元格展示：空值显示「—」，对象转 JSON。 */
export function cellText(v: unknown): string {
  if (v === undefined || v === null || v === '') return '—'
  return typeof v === 'object' ? JSON.stringify(v) : String(v)
}

/** 回复正文按纯文本展示：去掉 HTML 与 Markdown 粗体，流式未闭合标签一并剥掉。 */
export function plainText(content: string): string {
  return content
    .replace(/<[^>]*>/g, '')
    .replace(/<[^>]*$/g, '')
    .replace(/&nbsp;/gi, ' ')
    .replace(/&lt;/gi, '<')
    .replace(/&gt;/gi, '>')
    .replace(/&amp;/gi, '&')
    .replace(/\*\*/g, '')
}
