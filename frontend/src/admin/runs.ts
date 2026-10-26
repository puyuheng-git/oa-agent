export interface RunItem {
  run_id: string
  thread_id: string
  oa: string
  channel: string
  agent_id: string
  workflow_id: string
  workflow_version: string
  config_release_id: string | null
  run_status: string
  started_at: string
  ended_at: string | null
  last_event_at: string | null
  duration_ms: number | null
  error_code: string | null
  error_summary: string | null
  failed_node: string | null
  tool_call_count: number
  model_call_count: number
  business_type: string | null
  business_record_id: string | null
  suspected_stuck: boolean
}

export interface RunDetail extends RunItem {
  usage: { model?: string; provider?: string; usage?: Record<string, unknown> }[] | null
  event_count: number
  thread_run_count: number
  parent_run_id: string | null
  child_runs: { run_id: string; run_status: string; started_at: string }[]
  interventions: {
    task_id: string
    kind: string
    status: string
    reason: string
    created_at: string
    handled_by: string | null
    result: string | null
  }[]
  can_cancel: boolean
  can_retry: boolean
  waiting_human: boolean
}

export interface RunEvent {
  event_id: string
  seq: number
  event_type: string
  node_name: string | null
  status: string | null
  occurred_at: string
  duration_ms: number | null
  tool_name: string | null
  tool_version: string | null
  correlation_id: string | null
  error_code: string | null
  error_summary: string | null
  input_summary: string | null
  output_summary: string | null
  retry_count: number
  operator_id: string | null
  metadata_json: Record<string, unknown> | null
}

export interface RunStats {
  range: { start: string; end: string }
  total: number
  by_status: Record<string, number>
  success_rate: number | null
  rate_denominator: number
  in_progress: number
  suspected_stuck: number
  duration_ms: { samples: number; p50: number | null; p95: number | null; p95_insufficient: boolean }
  tool_calls: number
  model_calls: number
  tokens: {
    runs_with_usage: number
    model_calls_with_usage: number
    prompt_tokens: number
    completion_tokens: number
    total_tokens: number
  } | null
  daily: { date: string; total: number; succeeded: number; failed: number; timed_out: number }[]
  generated_at: string
  observability: Record<string, any>
}

export interface TopError {
  error_code: string
  failed_node: string | null
  count: number
  last_at: string
  sample_run_id: string | null
  sample_summary: string | null
}

type TagType = 'success' | 'danger' | 'warning' | 'info' | 'primary'

export const RUN_STATUS: Record<string, { label: string; type: TagType }> = {
  queued: { label: '排队中', type: 'info' },
  running: { label: '运行中', type: 'primary' },
  waiting_confirmation: { label: '待用户确认', type: 'warning' },
  waiting_human: { label: '待人工介入', type: 'warning' },
  cancel_requested: { label: '取消中', type: 'warning' },
  succeeded: { label: '成功', type: 'success' },
  failed: { label: '失败', type: 'danger' },
  timed_out: { label: '超时', type: 'danger' },
  cancelled: { label: '已取消', type: 'info' },
  expired: { label: '已过期', type: 'info' },
}

export function statusLabel(status: string): string {
  return RUN_STATUS[status]?.label ?? status
}

export function statusType(status: string): TagType {
  return RUN_STATUS[status]?.type ?? 'info'
}

export const EVENT_LABELS: Record<string, string> = {
  run_start: '运行开始',
  run_end: '运行结束',
  node_start: '节点开始',
  node_end: '节点结束',
  node_error: '节点出错',
  tool_call_start: 'Tool 调用',
  tool_call_end: 'Tool 返回',
  model_call: '模型调用',
  checkpoint_saved: '保存检查点',
  checkpoint_restored: '恢复检查点',
  node_interrupted: '节点挂起（等待人工）',
  run_waiting_human: '转人工介入',
  operator_resume: '管理员恢复',
  operator_terminate: '管理员终止',
  operator_cancel: '管理员取消',
  operator_retry: '管理员重试',
  run_cancel_observed: '检测到取消',
  run_superseded: '被新请求作废',
  intervention_expired: '介入任务过期',
}

export const RANGE_PRESETS = [
  { value: '24h', label: '最近 24 小时', ms: 24 * 3600_000 },
  { value: '7d', label: '最近 7 天', ms: 7 * 86400_000 },
  { value: '30d', label: '最近 30 天', ms: 30 * 86400_000 },
] as const

export type RangePreset = (typeof RANGE_PRESETS)[number]['value']

/** 相对范围按分钟取整，配合后端 30 秒统计缓存。 */
export function rangeParams(preset: RangePreset, now: Date = new Date()): { start: string; end: string } {
  const ms = RANGE_PRESETS.find((p) => p.value === preset)!.ms
  const end = new Date(Math.floor(now.getTime() / 60_000) * 60_000 + 60_000)
  return { start: new Date(end.getTime() - ms).toISOString(), end: end.toISOString() }
}

export const NO_DATA = '暂无数据'

export function formatDuration(ms: number | null | undefined): string {
  if (ms === null || ms === undefined) return NO_DATA
  if (ms < 1000) return `${ms} ms`
  if (ms < 60_000) return `${(ms / 1000).toFixed(ms < 10_000 ? 2 : 1)} s`
  const m = Math.floor(ms / 60_000)
  return `${m} 分 ${Math.round((ms % 60_000) / 1000)} 秒`
}

export function formatRate(rate: number | null | undefined): string {
  return rate === null || rate === undefined ? NO_DATA : `${(rate * 100).toFixed(1)}%`
}

export function formatP95(d: RunStats['duration_ms']): string {
  if (d.samples === 0) return NO_DATA
  return d.p95_insufficient ? `样本不足（${d.samples}/20）` : formatDuration(d.p95)
}

export const NODE_LABELS: Record<string, string> = {
  understand: '理解意图',
  call_tool: '调用业务接口',
  human_handoff: '人工介入',
  respond: '生成回复',
}

const INTENT_LABELS: Record<string, string> = { list: '列表查询', detail: '详情查询', tool: '调用 Tool', help: '帮助 / 无关问题' }
const INTENT_SOURCE: Record<string, string> = { llm: '模型解析', rules: '规则解析' }
const PARAM_LABELS: Record<string, string> = {
  date_gte: '开始日期',
  date_lte: '结束日期',
  status: '状态',
  source: '来源',
  id: '单号',
  limit: '条数',
}
const PARAM_VALUES: Record<string, Record<string, string>> = {
  status: { '0': '未报销', '1': '已报销' },
  source: { '1': '外出', '2': '191 请款' },
}

export type LineTone = 'user' | 'reply' | 'code'

export interface EventLine {
  label: string
  text: string
  tone?: LineTone
}

/** 摘要按 JSON 解析；截断或非 JSON 时原样返回字符串。 */
export function parseSummary(value: unknown): any {
  if (typeof value !== 'string') return value ?? null
  try {
    return JSON.parse(value)
  } catch {
    return value
  }
}

export function formatParams(params: unknown): string {
  if (!params || typeof params !== 'object') return '无'
  const parts = Object.entries(params as Record<string, unknown>)
    .filter(([, v]) => v !== null && v !== undefined && v !== '')
    .map(([k, v]) => `${PARAM_LABELS[k] ?? k}：${PARAM_VALUES[k]?.[String(v)] ?? String(v)}`)
  return parts.length ? parts.join('，') : '无'
}

function asText(value: unknown): string {
  return typeof value === 'string' ? value : JSON.stringify(value, null, 2)
}

/** 把一条事件翻译成时间线上直接可读的几行；原始摘要仍在折叠区可看。 */
export function describeEvent(e: RunEvent): EventLine[] {
  const input = parseSummary(e.input_summary)
  const output = parseSummary(e.output_summary)
  const meta = e.metadata_json ?? {}
  const lines: EventLine[] = []
  switch (e.event_type) {
    case 'run_start':
      if (input && typeof input === 'object' && 'message' in input) {
        lines.push({ label: '用户输入', text: String(input.message), tone: 'user' })
      } else if (typeof input === 'string') {
        lines.push({ label: '用户输入', text: input, tone: 'user' })
      }
      break
    case 'node_start':
      if (e.node_name === 'call_tool' && input && typeof input === 'object') {
        lines.push({ label: '查询条件', text: formatParams(input.params) })
      }
      break
    case 'node_end':
      if (!output || typeof output !== 'object') {
        if (typeof output === 'string') lines.push({ label: '输出', text: output, tone: 'code' })
        break
      }
      if (e.node_name === 'understand') {
        const intent = output.intent === 'ask'
          ? `${output.tool} 缺少必填参数`
          : output.tool ? `调用 ${output.tool}` : (INTENT_LABELS[output.intent] ?? output.intent ?? '—')
        const source = INTENT_SOURCE[output.intent_source] ?? output.intent_source
        lines.push({ label: '识别意图', text: source ? `${intent}（${source}）` : intent })
        if (output.intent === 'ask') lines.push({ label: '待补充', text: (output.missing ?? []).join('、') || '—' })
        else if (output.intent !== 'help') lines.push({ label: '查询条件', text: formatParams(output.params) })
      } else if (e.node_name === 'call_tool') {
        if (output.handoff) {
          lines.push({ label: '转人工', text: `${output.handoff.error_code ?? ''} ${output.handoff.error_summary ?? ''}`.trim() })
        } else {
          const total = output.total !== null && output.total !== undefined ? `，共 ${output.total} 条` : ''
          lines.push({ label: '查询结果', text: `${output.tool ?? ''} 返回 ${output.result_count ?? 0} 条${total}` })
        }
      } else if (e.node_name === 'human_handoff') {
        lines.push({ label: '管理员决定', text: asText(output.decision) })
      } else if (e.node_name === 'respond') {
        lines.push({ label: '回复员工', text: String(output.content ?? ''), tone: 'reply' })
      }
      break
    case 'tool_call_start':
      if (meta.path) lines.push({ label: '接口', text: String(meta.path) })
      lines.push({ label: '参数', text: formatParams(input) })
      if (Array.isArray(meta.dropped_fields) && meta.dropped_fields.length) {
        lines.push({ label: '已丢弃字段', text: meta.dropped_fields.join('、') })
      }
      break
    case 'tool_call_end':
      if (meta.http_status) lines.push({ label: 'HTTP', text: String(meta.http_status) })
      if (output && typeof output === 'object') {
        const total = output.total !== null && output.total !== undefined ? `，共 ${output.total} 条` : ''
        lines.push({ label: '返回', text: `${output.result_count ?? 0} 条${total}` })
      }
      break
    case 'model_call': {
      if (meta.provider || meta.model) lines.push({ label: '模型', text: `${meta.provider ?? ''} / ${meta.model ?? ''}` })
      const human = input?.messages?.filter?.((m: any) => m.role === 'human').pop()
      if (human) lines.push({ label: '发送给模型', text: String(human.content), tone: 'user' })
      if (output) lines.push({ label: '模型输出', text: asText(output), tone: 'code' })
      if (meta.usage) lines.push({ label: 'Token', text: asText(meta.usage) })
      break
    }
    case 'operator_resume':
    case 'operator_terminate':
    case 'operator_cancel':
    case 'operator_retry':
      if (e.operator_id) lines.push({ label: '操作人', text: e.operator_id })
      if (meta.reason) lines.push({ label: '原因', text: String(meta.reason) })
      break
  }
  if (e.error_summary) lines.push({ label: '错误', text: e.error_summary })
  return lines
}

export function formatSummary(value: unknown): string {
  if (value === null || value === undefined || value === '') return ''
  if (typeof value === 'string') {
    try {
      return JSON.stringify(JSON.parse(value), null, 2)
    } catch {
      return value
    }
  }
  return JSON.stringify(value, null, 2)
}
