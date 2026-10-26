export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
  ) {
    super(message)
  }
}

let csrfToken = ''
let onUnauthenticated: (() => void) | null = null

export function setCsrfToken(token: string) {
  csrfToken = token
}

export function setUnauthenticatedHandler(fn: (() => void) | null) {
  onUnauthenticated = fn
}

export function newIdempotencyKey(): string {
  return globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random().toString(16).slice(2)}`
}

type Method = 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE'

export async function request<T = unknown>(
  method: Method,
  url: string,
  body?: unknown,
  extraHeaders: Record<string, string> = {},
): Promise<T> {
  const headers: Record<string, string> = { Accept: 'application/json', ...extraHeaders }
  if (body !== undefined) headers['Content-Type'] = 'application/json'
  if (method !== 'GET') {
    if (csrfToken) headers['X-CSRF-Token'] = csrfToken
    headers['Idempotency-Key'] = newIdempotencyKey()
  }
  const resp = await fetch(url, {
    method,
    headers,
    credentials: 'same-origin',
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  const text = await resp.text()
  let data: any = null
  try {
    data = text ? JSON.parse(text) : null
  } catch {
    data = null
  }
  if (!resp.ok) {
    const err = data?.error
    const apiErr = new ApiError(resp.status, err?.code ?? 'HTTP_ERROR', err?.message ?? `请求失败（HTTP ${resp.status}）`)
    if (resp.status === 401 && onUnauthenticated) onUnauthenticated()
    throw apiErr
  }
  return data as T
}

export const http = {
  get: <T = unknown>(url: string, params?: Record<string, string | number | undefined | null>) => {
    const qs = params
      ? new URLSearchParams(
          Object.entries(params)
            .filter(([, v]) => v !== undefined && v !== null && v !== '')
            .map(([k, v]) => [k, String(v)]),
        ).toString()
      : ''
    return request<T>('GET', qs ? `${url}?${qs}` : url)
  },
  post: <T = unknown>(url: string, body?: unknown) => request<T>('POST', url, body ?? {}),
  put: <T = unknown>(url: string, body?: unknown) => request<T>('PUT', url, body ?? {}),
  del: <T = unknown>(url: string) => request<T>('DELETE', url),
}

export function errorMessage(e: unknown): string {
  if (e instanceof ApiError) return e.status === 403 && e.code === 'FORBIDDEN' ? `无权限：${e.message}` : e.message
  return e instanceof Error ? e.message : String(e)
}
