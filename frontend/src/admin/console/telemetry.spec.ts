import { describe, expect, it } from 'vitest'
import { buildBroadcast, buildTelemetry, buildTicker, coreMood, type ConsoleData } from './telemetry'

const okReady = {
  database: { status: 'ok' },
  redis: { status: 'ok', backend: 'redis' },
  llm: { status: '已配置（未检测）', enabled_providers: 1, enabled_models: 2 },
  observability: { status: 'ok' },
}

function data(partial: Partial<ConsoleData> = {}): ConsoleData {
  return { ready: null, readyFailed: false, stats: null, pending: null, ...partial }
}

describe('coreMood', () => {
  it('尚未取到状态为 unknown', () => {
    expect(coreMood(data()).mood).toBe('unknown')
  })
  it('请求失败为 bad', () => {
    expect(coreMood(data({ readyFailed: true })).mood).toBe('bad')
  })
  it('全部正常为 ok', () => {
    expect(coreMood(data({ ready: okReady })).mood).toBe('ok')
  })
  it('数据库异常为 bad', () => {
    expect(coreMood(data({ ready: { ...okReady, database: { status: 'error' } } })).mood).toBe('bad')
  })
  it('监控写入降级或 Redis 非 ok 为 warn', () => {
    expect(coreMood(data({ ready: { ...okReady, observability: { status: 'degraded' } } })).mood).toBe('warn')
    expect(coreMood(data({ ready: { ...okReady, redis: { status: 'error' } } })).mood).toBe('warn')
    expect(coreMood(data({ ready: { ...okReady, database: { status: 'migration_pending' } } })).mood).toBe('warn')
  })
})

describe('buildTelemetry', () => {
  it('无数据时不产生遥测', () => {
    expect(buildTelemetry(data())).toEqual({})
  })

  it('运行统计与待处理介入映射到对应模块', () => {
    const t = buildTelemetry(
      data({
        stats: { total: 128, success_rate: 0.9723, in_progress: 2, suspected_stuck: 0 },
        pending: 3,
        ready: okReady,
      }),
    )
    expect(t['/runs/overview']).toBeUndefined()
    expect(t['/runs']).toEqual({ text: '运行中 2', tone: 'normal' })
    expect(t['/interventions']).toEqual({ text: '待处理 3', tone: 'warn' })
    expect(t['/llm']).toEqual({ text: '启用模型 2', tone: 'normal' })
    expect(t['/settings'].text).toBe('数据库 ok · Redis ok')
  })

  it('疑似卡住优先显示', () => {
    const t = buildTelemetry(data({ stats: { total: 0, success_rate: null, in_progress: 0, suspected_stuck: 1 } }))
    expect(t['/runs']).toEqual({ text: '疑似卡住 1', tone: 'warn' })
  })

  it('待处理为 0 时为 normal', () => {
    expect(buildTelemetry(data({ pending: 0 }))['/interventions'].tone).toBe('normal')
  })
})

describe('buildBroadcast', () => {
  it('只播报真实事件', () => {
    const msgs = buildBroadcast(
      data({ ready: okReady, stats: { total: 5, success_rate: 1, in_progress: 0, suspected_stuck: 2 }, pending: 1 }),
    )
    expect(msgs).toContain('检测到 2 个疑似卡住的运行')
    expect(msgs).toContain('有 1 个介入任务等待处理')
    expect(msgs.some((m) => m.includes('所有子系统运行正常'))).toBe(true)
  })

  it('无数据时只给出未检测提示', () => {
    expect(buildBroadcast(data())).toEqual(['系统状态未检测'])
  })
})

describe('buildTicker', () => {
  it('拼接真实键值，缺失项不出现', () => {
    const items = buildTicker(data({ ready: okReady, pending: 0 }))
    expect(items).toContain('DB OK')
    expect(items).toContain('PENDING 0')
    expect(items.some((i) => i.startsWith('RUNS'))).toBe(false)
  })
})
