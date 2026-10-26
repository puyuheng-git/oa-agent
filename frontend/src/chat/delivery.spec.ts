import { describe, expect, it } from 'vitest'
import { buildDelivery, deliveryFromReply } from './delivery'
import type { AgentTask } from './types'

describe('delivery', () => {
  it('从真实表格结果生成交付摘要', () => {
    const d = deliveryFromReply({
      type: 'markdown',
      content: '查到了',
      data: {
        kind: 'table',
        tool: 'travel.list',
        title: '行程报销列表',
        columns: [{ key: 'id', label: 'ID' }],
        items: [{ id: 1 }, { id: 2 }],
        total: 12,
      },
    })
    expect(d?.mock).toBe(false)
    expect(d?.title).toBe('行程报销列表')
    expect(d?.highlights.some((h) => h.value.includes('12'))).toBe(true)
    expect(d?.hasStructuredData).toBe(true)
  })

  it('无结构化数据时可用 Mock 任务生成演示摘要', () => {
    const task: AgentTask = {
      id: 't1',
      name: '演示',
      status: 'completed',
      progress: 100,
      createdAt: Date.now(),
      elapsedMs: 1000,
      steps: [
        { id: 'a', title: '理解需求', status: 'completed' },
        { id: 'b', title: '制定计划', status: 'completed' },
      ],
      tools: [{ id: '1', name: 'x', status: 'succeeded', durationMs: 10 }],
      artifacts: [
        {
          id: 'f1',
          name: '清单.xlsx',
          kind: 'xlsx',
          sizeLabel: '1 KB',
          status: 'ready',
          previewable: false,
        },
      ],
      approvals: [],
      mock: true,
    }
    const d = buildDelivery({ type: 'text', content: 'ok', data: null }, task)
    expect(d?.mock).toBe(true)
    expect(d?.artifacts?.length).toBe(1)
  })
})
