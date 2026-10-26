import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  cellText, clearMemory, clearTicket, deleteMemory, formatRelativeTime, hasTicket, listMemory,
  mapThreadMessages, memoryKindLabel, openSession, parseSse, plainText,
  pollSettings, refreshDelayMs, sendMessage, sendMessageStream, StreamAbortedError, takeLaunchCode,
  threadDisplayTitle, welcomeExamples,
} from './api'

describe('streaming', () => {
  it('parseSse 返回完整事件与未结束部分，忽略心跳注释', () => {
    const { events, rest } = parseSse(': ping\n\nevent: delta\ndata: {"text":"你"}\n\nevent: done\ndata: {"run')
    expect(events).toEqual([{ event: 'delta', data: { text: '你' } }])
    expect(rest).toBe('event: done\ndata: {"run')
  })

  it('sendMessageStream 逐段回调并返回 done 结果', async () => {
    const body = 'event: delta\ndata: {"text":"你好"}\n\nevent: delta\ndata: {"text":"！"}\n\n'
      + 'event: done\ndata: {"run_id":"r1","thread_id":"t","run_status":"succeeded","reply":{"type":"markdown","content":"你好！","data":null}}\n\n'
    vi.stubGlobal('fetch', vi.fn(async () => new Response(body, { status: 200, headers: { 'Content-Type': 'text/event-stream' } })))
    const pieces: string[] = []
    const r = await sendMessageStream('hi', (p) => pieces.push(p))
    expect(pieces.join('')).toBe('你好！')
    expect(r.reply.content).toBe('你好！')
  })

  it('sendMessageStream 支持 AbortSignal 中止', async () => {
    const ctrl = new AbortController()
    ctrl.abort()
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => {
        throw new DOMException('Aborted', 'AbortError')
      }),
    )
    await expect(sendMessageStream('hi', () => {}, ctrl.signal)).rejects.toBeInstanceOf(StreamAbortedError)
  })

  it('sendMessageStream 校验失败按普通错误抛出；error 事件也抛出', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ error: { code: 'RATE_LIMITED', message: '发送太频繁' } }), { status: 429 })))
    await expect(sendMessageStream('hi', () => {})).rejects.toMatchObject({ status: 429, message: '发送太频繁' })
    vi.stubGlobal('fetch', vi.fn(async () => new Response('event: error\ndata: {"code":"X","message":"处理失败"}\n\n', { status: 200 })))
    await expect(sendMessageStream('hi', () => {})).rejects.toMatchObject({ message: '处理失败' })
    vi.stubGlobal('fetch', vi.fn(async () => new Response('event: delta\ndata: {"text":"半"}\n\n', { status: 200 })))
    await expect(sendMessageStream('hi', () => {})).rejects.toThrow('连接中断')
  })

  it('pollSettings 使用会话下发的值，缺省时用默认值', () => {
    expect(pollSettings({ poll_interval_seconds: 10, poll_max_minutes: 60 })).toEqual({ intervalMs: 10000, maxMs: 3600000 })
    expect(pollSettings({})).toEqual({ intervalMs: 5000, maxMs: 35 * 60 * 1000 })
  })
})

afterEach(() => {
  vi.unstubAllGlobals()
  clearTicket()
})

function mockFetch(responses: unknown[]) {
  const fn = vi.fn()
  for (const body of responses) fn.mockImplementationOnce(async () => new Response(JSON.stringify(body), { status: 200 }))
  vi.stubGlobal('fetch', fn)
  return fn
}

describe('chat api', () => {
  it('读取 launch 参数后立即从地址栏移除', () => {
    const hist = { replaceState: vi.fn() } as unknown as History
    const code = takeLaunchCode({ href: 'https://agent.example.com/chat/?launch=abc123&x=1#/' } as Location, hist)
    expect(code).toBe('abc123')
    expect(hist.replaceState).toHaveBeenCalledWith(null, '', '/chat/?x=1#/')

    const hist2 = { replaceState: vi.fn() } as unknown as History
    expect(takeLaunchCode({ href: 'https://agent.example.com/chat/' } as Location, hist2)).toBe('')
    expect(hist2.replaceState).not.toHaveBeenCalled()
  })

  it('ticket 只在内存，消息请求带 Bearer 与 client_msg_id', async () => {
    const fn = mockFetch([
      { ticket: 't-1', expires_in: 1800, display_name: '张三', thread_id: 'thr_1' },
      { run_id: 'run_1', thread_id: 'thr_1', run_status: 'succeeded', reply: { type: 'text', content: 'ok', data: null } },
    ])
    expect(hasTicket()).toBe(false)
    await openSession('code-1')
    expect(hasTicket()).toBe(true)
    await sendMessage('查上周行程报销')
    const [url, init] = fn.mock.calls[1]
    expect(url).toBe('/v1/chat/messages')
    expect(init.headers.Authorization).toBe('Bearer t-1')
    const body = JSON.parse(init.body)
    expect(body.message).toBe('查上周行程报销')
    expect(body.client_msg_id).toMatch(/^[\w-]{8,64}$/)
    expect(JSON.stringify(body)).not.toContain('"oa"')
  })

  it('续期时间与纯文本处理', () => {
    expect(refreshDelayMs(1800)).toBe(1680_000)
    expect(refreshDelayMs(60)).toBe(30_000)
    expect(plainText('共有 **3** 张<script>alert(1)</script>')).toBe('共有 3 张alert(1)')
    expect(plainText('你好<p>世界</p>')).toBe('你好世界')
    expect(plainText('流式中未闭合<div')).toBe('流式中未闭合')
  })

  it('欢迎页示例只取近三天新加的 Skill/Tool，并按 Skill 轮流取', () => {
    const now = Date.now()
    const recent = new Date(now - 24 * 3600_000).toISOString()
    const old = new Date(now - 10 * 24 * 3600_000).toISOString()
    const skills = [
      { name: 'a', display_name: 'A', description: '', examples: ['a1', 'a2'], created_at: recent },
      { name: 'b', display_name: 'B', description: '', examples: ['b1'], created_at: old },
      {
        name: 'c',
        display_name: 'C',
        description: '',
        examples: ['c1'],
        created_at: old,
        newest_tool_created_at: recent,
      },
    ]
    expect(welcomeExamples(skills, 3, now)).toEqual(['a1', 'c1', 'a2'])
    expect(welcomeExamples(skills.map((s) => ({ ...s, created_at: old, newest_tool_created_at: undefined })), 3, now)).toEqual([])
    expect(welcomeExamples([])).toEqual([])
    expect(cellText(null)).toBe('—')
    expect(cellText({ x: 1 })).toBe('{"x":1}')
    expect(cellText(0)).toBe('0')
  })

  it('线程标题与历史消息映射', () => {
    expect(threadDisplayTitle(null)).toBe('新会话')
    expect(threadDisplayTitle('  报销  ')).toBe('报销')
    const now = Date.parse('2026-01-02T12:00:00Z')
    expect(formatRelativeTime('2026-01-02T11:59:30Z', now)).toBe('刚刚')
    expect(formatRelativeTime('2026-01-02T11:00:00Z', now)).toBe('1 小时前')

    const mapped = mapThreadMessages([
      {
        message_id: 'm1',
        role: 'user',
        content: '你好',
        reply_type: null,
        data: null,
        created_at: '2026-01-01T00:00:00Z',
        run_id: null,
      },
      {
        message_id: 'm2',
        role: 'assistant',
        content: '**OK**',
        reply_type: 'markdown',
        data: null,
        created_at: '2026-01-01T00:00:01Z',
        run_id: 'run_1',
      },
    ])
    expect(mapped[0].text).toBe('你好')
    expect(mapped[1].text).toBe('OK')
    expect(mapped[1].runId).toBe('run_1')
    expect(mapped[1].reply?.type).toBe('markdown')
  })

  it('记忆 API 映射与 Bearer 鉴权', async () => {
    const fn = mockFetch([
      { ticket: 't-mem', expires_in: 1800, display_name: '李四', thread_id: 'thr_1' },
      {
        items: [
          {
            memory_id: 'mem_abc',
            kind: 'preference',
            text: '只关心九月报销',
            created_at: '2026-01-01T00:00:00Z',
            updated_at: '2026-01-02T00:00:00Z',
          },
        ],
        total: 1,
        page: 1,
        page_size: 100,
      },
      { ok: true },
      { ok: true, deleted: 2 },
    ])
    await openSession('launch-1')
    const listed = await listMemory(1, 50)
    expect(listed.items[0].memory_id).toBe('mem_abc')
    expect(listed.total).toBe(1)

    const [listUrl, listInit] = fn.mock.calls[1]
    expect(listUrl).toBe('/v1/chat/memory?page=1&page_size=50')
    expect(listInit.method).toBe('GET')
    expect(listInit.headers.Authorization).toBe('Bearer t-mem')

    await deleteMemory('mem_abc')
    const [delUrl, delInit] = fn.mock.calls[2]
    expect(delUrl).toBe('/v1/chat/memory/mem_abc')
    expect(delInit.method).toBe('DELETE')

    await clearMemory(true)
    const [, clearInit] = fn.mock.calls[3]
    expect(JSON.parse(clearInit.body)).toEqual({ confirm: true })

    expect(memoryKindLabel('preference')).toBe('偏好')
    expect(memoryKindLabel('constraint')).toBe('约束')
    expect(memoryKindLabel('unknown')).toBe('unknown')
  })
})
