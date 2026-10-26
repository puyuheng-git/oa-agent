export interface ConversationMessage {
  message_id: string
  run_id: string
  role: 'user' | 'assistant'
  content: string
  reply_type: string | null
  data: unknown
  error_code: string | null
  created_at: string
}

export interface ModelCall {
  call_id: string
  run_id: string
  node_name: string
  provider: string
  model: string
  messages: { role: string; content: string }[]
  output_text: string | null
  parsed: unknown
  usage: Record<string, unknown> | null
  status: string
  error_summary: string | null
  duration_ms: number | null
  created_at: string
}

export interface ThreadDetail {
  thread_id: string
  oa: string
  channel: string
  messages: ConversationMessage[]
  model_calls: ModelCall[]
  run_status: Record<string, string>
}

export type TimelineItem =
  | { kind: 'message'; key: string; message: ConversationMessage }
  | { kind: 'model'; key: string; call: ModelCall }

/** 按对话顺序排列，模型调用插在它所属运行的员工消息之后。 */
export function buildTimeline(detail: Pick<ThreadDetail, 'messages' | 'model_calls'>): TimelineItem[] {
  const callsByRun = new Map<string, ModelCall[]>()
  for (const c of detail.model_calls) {
    const list = callsByRun.get(c.run_id) ?? []
    list.push(c)
    callsByRun.set(c.run_id, list)
  }
  const items: TimelineItem[] = []
  for (const m of detail.messages) {
    items.push({ kind: 'message', key: m.message_id, message: m })
    if (m.role === 'user') {
      for (const c of callsByRun.get(m.run_id) ?? []) items.push({ kind: 'model', key: c.call_id, call: c })
      callsByRun.delete(m.run_id)
    }
  }
  for (const rest of callsByRun.values()) {
    for (const c of rest) items.push({ kind: 'model', key: c.call_id, call: c })
  }
  return items
}

export const ROLE_LABELS: Record<string, string> = { system: '系统提示词', human: '员工输入', ai: '模型', user: '员工' }
