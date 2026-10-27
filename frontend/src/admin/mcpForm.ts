// MCP 连接表单 ↔ API 载荷转换（纯函数，便于单测）。

export type McpTransport = 'stdio' | 'sse' | 'http'

export interface SecretView { is_set: boolean; display: string }

export interface McpServerItem {
  name: string
  display_name: string
  enabled: boolean
  transport: McpTransport
  command: string | null
  args: string[]
  url: string | null
  tool_prefix: string
  timeout_seconds: number
  headers_set: SecretView
  env_set: SecretView
  last_sync_at: string | null
  last_sync_result: string | null
  last_sync_error: string | null
}

export interface McpServerForm {
  name: string
  display_name: string
  transport: McpTransport
  command: string
  argsText: string
  url: string
  tool_prefix: string
  timeout_seconds: number
  enabled: boolean
  /** 只写：每行 `Key: value`；留空 = 不修改 */
  headersText: string
  /** 只写：每行 `KEY=value`；留空 = 不修改 */
  envText: string
  clearHeaders: boolean
  clearEnv: boolean
}

export function emptyMcpForm(): McpServerForm {
  return {
    name: '', display_name: '', transport: 'http', command: '', argsText: '', url: '',
    tool_prefix: '', timeout_seconds: 30, enabled: false,
    headersText: '', envText: '', clearHeaders: false, clearEnv: false,
  }
}

/** 编辑：不回填任何密钥内容（密钥只写不读）。 */
export function mcpFormFromItem(item: McpServerItem): McpServerForm {
  return {
    name: item.name,
    display_name: item.display_name,
    transport: item.transport,
    command: item.command ?? '',
    argsText: (item.args || []).join('\n'),
    url: item.url ?? '',
    tool_prefix: item.tool_prefix,
    timeout_seconds: item.timeout_seconds,
    enabled: item.enabled,
    headersText: '', envText: '', clearHeaders: false, clearEnv: false,
  }
}

/** 解析多行键值；sep 为分隔符（`:` 或 `=`）。无法解析的行抛 Error。 */
export function parsePairs(text: string, sep: ':' | '='): Record<string, string> {
  const out: Record<string, string> = {}
  for (const raw of text.split(/\r?\n/)) {
    const line = raw.trim()
    if (!line) continue
    const i = line.indexOf(sep)
    if (i <= 0) throw new Error(`格式应为「名称${sep}值」：${line.slice(0, 40)}`)
    out[line.slice(0, i).trim()] = line.slice(i + 1).trim()
  }
  return out
}

function secretField(text: string, clear: boolean, sep: ':' | '='): Record<string, string> | undefined {
  if (clear) return {} // {} = 清除
  if (!text.trim()) return undefined // 省略 = 沿用
  return parsePairs(text, sep)
}

export function mcpPayload(f: McpServerForm): Record<string, unknown> {
  const stdio = f.transport === 'stdio'
  const body: Record<string, unknown> = {
    name: f.name.trim(),
    display_name: f.display_name.trim(),
    transport: f.transport,
    tool_prefix: f.tool_prefix.trim(),
    timeout_seconds: f.timeout_seconds,
    enabled: f.enabled,
    command: stdio ? f.command.trim() : null,
    args: stdio ? f.argsText.split(/\r?\n/).map((s) => s.trim()).filter(Boolean) : [],
    url: stdio ? null : f.url.trim(),
  }
  // 与 transport 不匹配的密钥一律不发（后端切换类型时会自动清除对方）
  const headers = stdio ? undefined : secretField(f.headersText, f.clearHeaders, ':')
  const env = stdio ? secretField(f.envText, f.clearEnv, '=') : undefined
  if (headers !== undefined) body.headers = headers
  if (env !== undefined) body.env = env
  return body
}
