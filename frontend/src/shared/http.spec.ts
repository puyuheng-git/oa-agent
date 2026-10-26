import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiError, http, setCsrfToken } from './http'

function mockFetch(status: number, body: unknown) {
  const fn = vi.fn().mockImplementation(async () => new Response(JSON.stringify(body), { status }))
  vi.stubGlobal('fetch', fn)
  return fn
}

afterEach(() => vi.unstubAllGlobals())

describe('http', () => {
  it('写请求带 CSRF 与 Idempotency-Key，读请求不带', async () => {
    setCsrfToken('csrf-1')
    const fn = mockFetch(200, { ok: true })
    await http.put('/v1/x', { a: 1 })
    const headers = fn.mock.calls[0][1].headers
    expect(headers['X-CSRF-Token']).toBe('csrf-1')
    expect(headers['Idempotency-Key']).toBeTruthy()

    await http.get('/v1/y', { page: 1, empty: '' })
    expect(fn.mock.calls[1][0]).toBe('/v1/y?page=1')
    expect(fn.mock.calls[1][1].headers['X-CSRF-Token']).toBeUndefined()
  })

  it('每次写请求生成不同的 Idempotency-Key', async () => {
    const fn = mockFetch(200, {})
    await http.post('/v1/a')
    await http.post('/v1/a')
    expect(fn.mock.calls[0][1].headers['Idempotency-Key']).not.toBe(fn.mock.calls[1][1].headers['Idempotency-Key'])
  })

  it('统一错误体转换为 ApiError', async () => {
    mockFetch(403, { error: { code: 'FORBIDDEN', message: '无权限：sys.setting.edit' } })
    await expect(http.get('/v1/z')).rejects.toMatchObject({ status: 403, code: 'FORBIDDEN' })
    mockFetch(500, null)
    await expect(http.get('/v1/z')).rejects.toBeInstanceOf(ApiError)
  })
})
