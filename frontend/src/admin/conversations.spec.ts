import { describe, expect, it } from 'vitest'
import { buildTimeline, type ConversationMessage, type ModelCall } from './conversations'

function msg(id: string, run: string, role: 'user' | 'assistant'): ConversationMessage {
  return { message_id: id, run_id: run, role, content: id, reply_type: null, data: null, error_code: null, created_at: '' }
}

function call(id: string, run: string): ModelCall {
  return {
    call_id: id, run_id: run, node_name: 'understand', provider: 'p', model: 'm', messages: [], output_text: null,
    parsed: null, usage: null, status: 'ok', error_summary: null, duration_ms: null, created_at: '',
  }
}

describe('buildTimeline', () => {
  it('模型调用排在所属运行的员工消息之后', () => {
    const items = buildTimeline({
      messages: [msg('u1', 'r1', 'user'), msg('a1', 'r1', 'assistant'), msg('u2', 'r2', 'user'), msg('a2', 'r2', 'assistant')],
      model_calls: [call('c2', 'r2'), call('c1', 'r1')],
    })
    expect(items.map((i) => i.key)).toEqual(['u1', 'c1', 'a1', 'u2', 'c2', 'a2'])
  })

  it('没有对应员工消息的模型调用放在最后，不丢失', () => {
    const items = buildTimeline({ messages: [msg('u1', 'r1', 'user')], model_calls: [call('cx', 'rx')] })
    expect(items.map((i) => i.key)).toEqual(['u1', 'cx'])
  })
})
