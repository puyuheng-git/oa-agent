import { describe, expect, it } from 'vitest'
import { STATUS_HUE, arcPath, gaugeTicks, statusRings, trendOption } from './charts'
import { RUN_STATUS, type RunStats } from './runs'

function stats(partial: Partial<RunStats> = {}): RunStats {
  return {
    range: { start: '', end: '' },
    total: 0,
    by_status: {},
    success_rate: null,
    rate_denominator: 0,
    in_progress: 0,
    suspected_stuck: 0,
    duration_ms: { samples: 0, p50: null, p95: null, p95_insufficient: true },
    tool_calls: 0,
    model_calls: 0,
    tokens: null,
    daily: [],
    generated_at: '',
    observability: {},
    ...partial,
  }
}

describe('trendOption', () => {
  it('无按天数据时返回 null', () => {
    expect(trendOption(stats())).toBeNull()
  })

  it('按天生成成功 / 失败 / 超时堆叠柱与总数折线', () => {
    const opt: any = trendOption(
      stats({
        daily: [
          { date: '2026-10-12', total: 5, succeeded: 3, failed: 1, timed_out: 1 },
          { date: '2026-10-13', total: 2, succeeded: 2, failed: 0, timed_out: 0 },
        ],
      }),
    )
    expect(opt.xAxis.data).toEqual(['10-12', '10-13'])
    const byName = Object.fromEntries(opt.series.map((s: any) => [s.name, s]))
    expect(byName['成功'].data).toEqual([3, 2])
    expect(byName['失败'].data).toEqual([1, 0])
    expect(byName['超时'].data).toEqual([1, 0])
    expect(byName['运行总数'].data).toEqual([5, 2])
    expect(byName['运行总数'].type).toBe('line')
    expect(byName['成功'].stack).toBe(byName['失败'].stack)
    expect(byName['最新'].data).toEqual([['10-13', 2]])
    expect(byName['流光'].data[0].coords).toEqual([['10-12', 5], ['10-13', 2]])
  })

  it('只有一天数据时不加流光线', () => {
    const opt: any = trendOption(stats({ daily: [{ date: '2026-10-13', total: 1, succeeded: 1, failed: 0, timed_out: 0 }] }))
    expect(opt.series.some((s: any) => s.name === '流光')).toBe(false)
  })
})

describe('statusRings', () => {
  it('所有状态均为 0 时返回空数组', () => {
    expect(statusRings(stats({ by_status: { succeeded: 0 } }))).toEqual([])
  })

  it('仅含数量大于 0 的状态，按数量降序，占比与弧长按总数计算', () => {
    const rings = statusRings(stats({ by_status: { failed: 1, succeeded: 3, running: 0 } }))
    expect(rings.map((r) => r.id)).toEqual(['succeeded', 'failed'])
    expect(rings[0]).toMatchObject({ label: '成功', value: 3, ratio: 0.75 })
    expect(rings[1].ratio).toBeCloseTo(0.25)
    expect(rings[0].color).toBe(STATUS_HUE.succeeded)
    expect(rings[1].color).toBe(STATUS_HUE.failed)
  })
})

describe('STATUS_HUE', () => {
  it('每个运行状态都有 HUD 配色', () => {
    for (const id of Object.keys(RUN_STATUS)) expect(STATUS_HUE[id]).toMatch(/^#[0-9a-f]{6}$/)
  })
})

describe('gaugeTicks', () => {
  it('成功率为 null 时没有点亮的刻度', () => {
    expect(gaugeTicks(null, 40).filter((t) => t.on)).toHaveLength(0)
  })

  it('按成功率点亮刻度，角度覆盖 240°', () => {
    const ticks = gaugeTicks(0.5, 40)
    expect(ticks).toHaveLength(40)
    expect(ticks.filter((t) => t.on)).toHaveLength(20)
    expect(ticks[0].angle).toBeCloseTo(-120)
    expect(ticks[39].angle).toBeCloseTo(120)
  })
})

describe('arcPath', () => {
  it('从正上方顺时针画 90° 弧', () => {
    expect(arcPath(50, 50, 10, 0, 90)).toBe('M 50.00 40.00 A 10 10 0 0 1 60.00 50.00')
  })

  it('超过 180° 使用大弧标记', () => {
    expect(arcPath(0, 0, 10, 0, 270)).toContain(' 0 1 1 ')
  })
})
