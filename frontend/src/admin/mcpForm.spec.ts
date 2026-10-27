import { describe, expect, it } from 'vitest'
import { emptyMcpForm, mcpPayload, parsePairs } from './mcpForm'

describe('mcpForm', () => {
  it('远程类型：不带 command，密钥留空则不发送', () => {
    const f = { ...emptyMcpForm(), name: 'demo', transport: 'http' as const, url: ' https://mcp.example.com/mcp ' }
    const p = mcpPayload(f)
    expect(p.url).toBe('https://mcp.example.com/mcp')
    expect(p.command).toBeNull()
    expect(p.args).toEqual([])
    expect('headers' in p).toBe(false)
    expect('env' in p).toBe(false)
  })

  it('远程类型：填写请求头则整体替换，清除则发送空对象', () => {
    const f = { ...emptyMcpForm(), name: 'demo', url: 'https://a.b/c', headersText: 'Authorization: Bearer x:y' }
    expect(mcpPayload(f).headers).toEqual({ Authorization: 'Bearer x:y' })
    expect(mcpPayload({ ...f, clearHeaders: true }).headers).toEqual({})
  })

  it('stdio：command/args 生效，不发送 url 与 headers', () => {
    const f = {
      ...emptyMcpForm(), name: 'local', transport: 'stdio' as const, command: 'npx',
      argsText: '-y\n\n pkg ', envText: 'TOKEN=a=b', headersText: 'X: 1', url: 'https://ignored',
    }
    const p = mcpPayload(f)
    expect(p.command).toBe('npx')
    expect(p.args).toEqual(['-y', 'pkg'])
    expect(p.url).toBeNull()
    expect(p.env).toEqual({ TOKEN: 'a=b' })
    expect('headers' in p).toBe(false)
  })

  it('解析失败的行抛错', () => {
    expect(() => parsePairs('bad line', ':')).toThrow()
  })
})
