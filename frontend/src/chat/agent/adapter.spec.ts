import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import { MockAgentAdapter } from './adapter'

describe('MockAgentAdapter.syncLiveStatus elapsedMs', () => {
  beforeEach(() => {
    vi.useFakeTimers()
  })
  afterEach(() => {
    vi.useRealTimers()
  })

  it('结束后保留已走时长，不因重建任务变成 0ms', () => {
    const tasks: { elapsedMs: number; status: string }[] = []
    const adapter = new MockAgentAdapter({
      onTask: (t) => {
        if (t) tasks.push({ elapsedMs: t.elapsedMs, status: t.status })
      },
    })
    adapter.syncLiveStatus('running', '问时间')
    vi.advanceTimersByTime(1200)
    adapter.syncLiveStatus('completed')
    const last = tasks[tasks.length - 1]
    expect(last.status).toBe('completed')
    expect(last.elapsedMs).toBeGreaterThanOrEqual(1000)
    adapter.dispose()
  })
})
