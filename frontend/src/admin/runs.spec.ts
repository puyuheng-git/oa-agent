import { describe, expect, it } from 'vitest'
import {
  describeEvent,
  formatDuration,
  formatP95,
  formatRate,
  formatSummary,
  rangeParams,
  statusLabel,
  type RunEvent,
} from './runs'

function ev(partial: Partial<RunEvent>): RunEvent {
  return {
    event_id: 'e', seq: 1, event_type: 'run_start', node_name: null, status: null, occurred_at: '',
    duration_ms: null, tool_name: null, tool_version: null, correlation_id: null, error_code: null,
    error_summary: null, input_summary: null, output_summary: null, retry_count: 0, operator_id: null,
    metadata_json: null, ...partial,
  }
}

describe('describeEvent', () => {
  it('运行开始显示用户输入', () => {
    expect(describeEvent(ev({ input_summary: '{"message":"本月未报销的行程"}' }))).toEqual([
      { label: '用户输入', text: '本月未报销的行程', tone: 'user' },
    ])
  })

  it('理解意图节点显示意图、来源与中文查询条件', () => {
    const lines = describeEvent(ev({
      event_type: 'node_end', node_name: 'understand',
      output_summary: '{"intent":"list","intent_source":"rules","params":{"date_gte":"2026-10-01","status":0,"limit":10}}',
    }))
    expect(lines[0].text).toBe('列表查询（规则解析）')
    expect(lines[1].text).toBe('开始日期：2026-10-01，状态：未报销，条数：10')
    const picked = describeEvent(ev({
      event_type: 'node_end', node_name: 'understand',
      output_summary: '{"intent":"tool","tool":"query_my_leave_list","intent_source":"llm","params":{}}',
    }))
    expect(picked[0].text).toBe('调用 query_my_leave_list（模型解析）')
  })

  it('Tool 调用显示接口与参数，回复节点显示回复内容', () => {
    const call = describeEvent(ev({
      event_type: 'tool_call_start', input_summary: '{"id":12345}', metadata_json: { path: '/travel/detail' },
    }))
    expect(call).toEqual([{ label: '接口', text: '/travel/detail' }, { label: '参数', text: '单号：12345' }])
    const reply = describeEvent(ev({ event_type: 'node_end', node_name: 'respond', output_summary: '{"type":"markdown","content":"没有查到"}' }))
    expect(reply).toEqual([{ label: '回复员工', text: '没有查到', tone: 'reply' }])
  })

  it('摘要被截断成非 JSON 时原样显示，不报错', () => {
    const lines = describeEvent(ev({ event_type: 'node_end', node_name: 'respond', output_summary: '{"type":"mark…[截断]' }))
    expect(lines[0].text).toContain('[截断]')
  })
})

describe('runs helpers', () => {
  it('无数据时显示「暂无数据」，不编造数值', () => {
    expect(formatRate(null)).toBe('暂无数据')
    expect(formatDuration(null)).toBe('暂无数据')
    expect(formatP95({ samples: 0, p50: null, p95: null, p95_insufficient: true })).toBe('暂无数据')
    expect(formatP95({ samples: 6, p50: 200, p95: null, p95_insufficient: true })).toBe('样本不足（6/20）')
    expect(formatP95({ samples: 20, p50: 10, p95: 1900, p95_insufficient: false })).toBe('1.90 s')
  })

  it('格式化', () => {
    expect(formatRate(0.6)).toBe('60.0%')
    expect(formatDuration(482)).toBe('482 ms')
    expect(formatDuration(60_000)).toBe('1 分 0 秒')
    expect(statusLabel('timed_out')).toBe('超时')
    expect(statusLabel('unknown_x')).toBe('unknown_x')
    expect(formatSummary('{"a":1}')).toBe('{\n  "a": 1\n}')
    expect(formatSummary('plain')).toBe('plain')
  })

  it('相对时间范围按分钟取整', () => {
    const r = rangeParams('24h', new Date('2026-10-09T10:26:31.500Z'))
    expect(r.end).toBe('2026-10-09T10:27:00.000Z')
    expect(r.start).toBe('2026-10-08T10:27:00.000Z')
  })
})
