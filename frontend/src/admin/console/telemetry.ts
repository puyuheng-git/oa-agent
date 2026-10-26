import { formatRate } from '../runs'

export interface ReadyInfo {
  database?: { status?: string; [k: string]: unknown }
  redis?: { status?: string; backend?: string; [k: string]: unknown }
  llm?: { status?: string; enabled_providers?: number; enabled_models?: number }
  observability?: { status?: string; [k: string]: unknown }
  [k: string]: unknown
}

export interface StatsLite {
  total: number
  success_rate: number | null
  in_progress: number
  suspected_stuck: number
}

export interface ConsoleData {
  ready: ReadyInfo | null
  readyFailed: boolean
  stats: StatsLite | null
  pending: number | null
}

export type Mood = 'ok' | 'warn' | 'bad' | 'unknown'
export type Tone = 'normal' | 'warn'

export interface Telemetry {
  text: string
  tone: Tone
}

/** /readyz 在数据库异常时返回 503 但带明细，所以不走 http.get（非 2xx 会丢弃响应体）。 */
export async function fetchReady(): Promise<ReadyInfo> {
  const resp = await fetch('/readyz', { headers: { Accept: 'application/json' }, credentials: 'same-origin' })
  const body = await resp.json().catch(() => null)
  if (!body || typeof body !== 'object' || !('database' in body)) throw new Error(`HTTP ${resp.status}`)
  return body as ReadyInfo
}

export function coreMood(d: ConsoleData): { mood: Mood; text: string } {
  if (d.readyFailed) return { mood: 'bad', text: '状态检测失败' }
  const r = d.ready
  if (!r) return { mood: 'unknown', text: '未检测' }
  const db = r.database?.status
  if (db !== 'ok' && db !== 'migration_pending') return { mood: 'bad', text: '数据库异常' }
  if (db === 'migration_pending' || r.redis?.status !== 'ok' || r.observability?.status === 'degraded') {
    return { mood: 'warn', text: '部分降级' }
  }
  return { mood: 'ok', text: '系统正常' }
}

export function buildTelemetry(d: ConsoleData): Record<string, Telemetry> {
  const t: Record<string, Telemetry> = {}
  if (d.stats) {
    const s = d.stats
    t['/runs'] = s.suspected_stuck > 0
      ? { text: `疑似卡住 ${s.suspected_stuck}`, tone: 'warn' }
      : { text: `运行中 ${s.in_progress}`, tone: 'normal' }
  }
  if (d.pending !== null) {
    t['/interventions'] = { text: `待处理 ${d.pending}`, tone: d.pending > 0 ? 'warn' : 'normal' }
  }
  const r = d.ready
  if (r) {
    if (r.llm?.enabled_models !== undefined) {
      t['/llm'] = { text: `启用模型 ${r.llm.enabled_models}`, tone: r.llm.enabled_models ? 'normal' : 'warn' }
    }
    if (r.database?.status || r.redis?.status) {
      const db = r.database?.status ?? '未检测'
      const redis = r.redis?.status ?? '未检测'
      t['/settings'] = { text: `数据库 ${db} · Redis ${redis}`, tone: db === 'ok' && redis === 'ok' ? 'normal' : 'warn' }
    }
  }
  return t
}

/** HUD 播报：只陈述接口返回的事实。 */
export function buildBroadcast(d: ConsoleData): string[] {
  const msgs: string[] = []
  if (d.readyFailed) msgs.push('状态检测失败：无法访问 /readyz')
  const r = d.ready
  if (r) {
    if (coreMood(d).mood === 'ok') msgs.push('神经核心在线 · 所有子系统运行正常')
    if (r.database?.status !== 'ok') msgs.push(`数据库状态：${r.database?.status ?? '未检测'}`)
    if (r.redis?.status !== 'ok') msgs.push(`Redis 状态：${r.redis?.status ?? '未检测'}`)
    if (r.observability?.status === 'degraded') msgs.push('运行监控写入降级，事件已落本地补写队列')
  }
  if (d.stats) {
    msgs.push(`最近 24 小时运行 ${d.stats.total} 次，成功率 ${formatRate(d.stats.success_rate)}`)
    if (d.stats.suspected_stuck > 0) msgs.push(`检测到 ${d.stats.suspected_stuck} 个疑似卡住的运行`)
  }
  if (d.pending) msgs.push(`有 ${d.pending} 个介入任务等待处理`)
  return msgs.length ? msgs : ['系统状态未检测']
}

const up = (s: string | undefined) => (s ? (s === 'ok' ? 'OK' : s.toUpperCase()) : 'N/A')

/** 底部数据带：真实键值，缺失项不出现。 */
export function buildTicker(d: ConsoleData): string[] {
  const items: string[] = []
  const r = d.ready
  if (r) {
    items.push(`DB ${up(r.database?.status)}`, `REDIS ${up(r.redis?.status)}`)
    if (r.llm?.enabled_models !== undefined) items.push(`LLM MODELS ${r.llm.enabled_models}`)
    if (r.observability?.status) items.push(`OBS ${up(r.observability.status)}`)
  }
  if (d.stats) {
    const rate = d.stats.success_rate === null ? 'NO DATA' : formatRate(d.stats.success_rate)
    items.push(`RUNS·24H ${d.stats.total}`, `SUCCESS ${rate}`, `ACTIVE ${d.stats.in_progress}`, `STUCK ${d.stats.suspected_stuck}`)
  }
  if (d.pending !== null) items.push(`PENDING ${d.pending}`)
  return items
}
