/** 内置 Tool 实现说明（与后端 builtin_guide 对齐；接口未返回 guide 时作兜底）。 */
import type { ToolDetail, ToolGuide } from './ops'

type Param = NonNullable<ToolGuide['model_params']>[string]

function p(label: string, description = '', extra: Partial<Param> = {}): Param {
  return { type: 'string', label, description, ...extra }
}

const BUILTIN: Record<string, ToolGuide> = {
  'sys.time': {
    kind: 'builtin', builtin_id: 'sys.time', summary: '当前时间 / 时区', risk_level: 'low',
    runtime: 'BuiltinRuntime（进程内）',
    how: '在 Agent 进程内取当前时刻，按 IANA 时区格式化后返回。不访问 OA、不访问外网。',
    constraints: ['缺省时区 Asia/Shanghai', '结果经不可信数据围栏后回图'],
    model_params: { timezone: p('时区', 'IANA 时区名，如 Asia/Shanghai；缺省为平台默认时区') },
    result: { kind: 'text', fields: ['text'], note: '执行结果统一围栏为文本块回图，不走 OA 接口字段白名单。' },
    edit_hint: '实现写在代码目录中，后台不能改路径/算法；可用启停与 Skill 绑定控制是否对员工开放。',
  },
  'sys.calc': {
    kind: 'builtin', builtin_id: 'sys.calc', summary: '安全表达式计算', risk_level: 'low',
    runtime: 'BuiltinRuntime（进程内）',
    how: '用 AST 解析表达式，只允许数字与 + - * / // % ** 和括号，禁止函数调用、属性访问与变量名。',
    constraints: ['表达式最长 200 字符', '指数绝对值 ≤ 64', '结果绝对值有上限，防溢出'],
    model_params: { expression: p('表达式', '只支持数字与 + - * / // % ** 括号，如 (3+4)*2', { required: true }) },
    result: { kind: 'text', fields: ['text'], note: '执行结果统一围栏为文本块回图，不走 OA 接口字段白名单。' },
    edit_hint: '实现写在代码目录中，后台不能改路径/算法；可用启停与 Skill 绑定控制是否对员工开放。',
  },
  'sys.export': {
    kind: 'builtin', builtin_id: 'sys.export', summary: '导出文件并返回下载票据', risk_level: 'medium',
    runtime: 'BuiltinRuntime（进程内）', needs_sandbox: true,
    how: '把文本写入本机 data/exports/{tenant}/，签发一次性下载票据；不直连 OA 业务库。',
    constraints: ['内容体积有上限', '票据有过期时间（见沙箱策略 export_ttl_seconds）', '文件名经清洗，禁止路径穿越'],
    default_sandbox_policy: { export_ttl_seconds: 3600 },
    model_params: { content: p('内容', '要导出的文本', { required: true }), filename: p('文件名') },
    result: { kind: 'text', fields: ['text'], note: '执行结果统一围栏为文本块回图，不走 OA 接口字段白名单。' },
    edit_hint: '实现写在代码目录中，后台不能改路径/算法；可用启停与 Skill 绑定控制是否对员工开放。',
  },
  'sys.memory': {
    kind: 'builtin', builtin_id: 'sys.memory', summary: '员工长期记忆', risk_level: 'medium',
    runtime: 'BuiltinRuntime（进程内）',
    how: '读写本系统 agent_employee_memory 表中的「当前员工」记忆；oa 只取服务端会话，模型无法指定他人。',
    constraints: ['敏感内容（身份证号、工资等）拒绝写入', '条数有上限', '与对话里「请记住」走同一套领域服务'],
    model_params: {
      action: p('操作', 'add 记住 / list 列出 / forget 忘记', { enum: ['add', 'list', 'forget'] }),
      text: p('内容', 'add 时为要记住的内容；forget 时为要忘记的内容关键字'),
      kind: p('类别'),
    },
    result: { kind: 'text', fields: ['text'], note: '执行结果统一围栏为文本块回图，不走 OA 接口字段白名单。' },
    edit_hint: '实现写在代码目录中，后台不能改路径/算法；可用启停与 Skill 绑定控制是否对员工开放。',
  },
  'sys.cron': {
    kind: 'builtin', builtin_id: 'sys.cron', summary: '定时触发已发布的流程或任务模板', risk_level: 'high',
    runtime: 'BuiltinRuntime（进程内）', needs_sandbox: true, default_enabled: false,
    how: '只在 KV 中登记「已发布 workflow 名 + cron 表达式」，本期不真正调度执行命令或脚本。',
    constraints: ['默认停用，须管理员启用', '必须配置 sandbox_policy', 'workflow 名须符合白名单字符集'],
    default_sandbox_policy: { cron_max_jobs: 20 },
    model_params: {
      action: p('操作', 'list / add / remove'), workflow: p('流程'), cron: p('cron 表达式'), job_id: p('任务 ID'),
    },
    result: { kind: 'text', fields: ['text'], note: '执行结果统一围栏为文本块回图，不走 OA 接口字段白名单。' },
    edit_hint: '实现写在代码目录中，后台不能改路径/算法；可用启停与 Skill 绑定控制是否对员工开放。',
  },
  'sys.http': {
    kind: 'builtin', builtin_id: 'sys.http', summary: '受控 HTTP 请求', risk_level: 'high',
    runtime: 'BuiltinRuntime（进程内）', needs_sandbox: true, default_enabled: false,
    how: '由 Agent 发起外呼 HTTP；主机须命中 Tool 沙箱或全局 runtime.http_allow_hosts；默认不跟随重定向，不带员工 Authorization。',
    constraints: ['默认停用', '无沙箱策略则调用失败（SANDBOX_REQUIRED）', '响应体限字节；HTML 会做诱导内容清洗'],
    default_sandbox_policy: { http_allow_hosts: [], http_methods: ['GET'], http_max_response_bytes: 65536 },
    model_params: { url: p('URL', '', { required: true }), method: p('方法') },
    result: { kind: 'text', fields: ['text'], note: '执行结果统一围栏为文本块回图，不走 OA 接口字段白名单。' },
    edit_hint: '实现写在代码目录中，后台不能改路径/算法；可用启停与 Skill 绑定控制是否对员工开放。',
  },
  'sys.web_search': {
    kind: 'builtin', builtin_id: 'sys.web_search', summary: '网络搜索', risk_level: 'high',
    runtime: 'BuiltinRuntime（进程内）', needs_sandbox: true, default_enabled: false,
    how: '调用已配置的搜索供应商 API；密钥只从 Vault 读取，不进入结果与错误信息。',
    constraints: ['默认停用', '须有 sandbox_policy', '返回条数有上限'],
    default_sandbox_policy: { search_max_results: 5 },
    model_params: { query: p('搜索词', '', { required: true }) },
    result: { kind: 'text', fields: ['text'], note: '执行结果统一围栏为文本块回图，不走 OA 接口字段白名单。' },
    edit_hint: '实现写在代码目录中，后台不能改路径/算法；可用启停与 Skill 绑定控制是否对员工开放。',
  },
  'sys.fs_read': {
    kind: 'builtin', builtin_id: 'sys.fs_read', summary: '沙箱内读文件', risk_level: 'high',
    runtime: 'BuiltinRuntime（进程内）', needs_sandbox: true, default_enabled: false,
    how: '只读 data/sandbox/{tenant}/ 下相对路径；resolve 后复核仍在沙箱根内，禁止 .. 穿越。',
    constraints: ['默认停用', '须有 sandbox_policy', '读取字节上限可配'],
    default_sandbox_policy: { fs_root: 'sandbox', fs_max_read_bytes: 65536 },
    model_params: { path: p('沙箱内路径', '', { required: true }) },
    result: { kind: 'text', fields: ['text'], note: '执行结果统一围栏为文本块回图，不走 OA 接口字段白名单。' },
    edit_hint: '实现写在代码目录中，后台不能改路径/算法；可用启停与 Skill 绑定控制是否对员工开放。',
  },
  'sys.fs_write': {
    kind: 'builtin', builtin_id: 'sys.fs_write', summary: '沙箱内写文件', risk_level: 'high',
    runtime: 'BuiltinRuntime（进程内）', needs_sandbox: true, default_enabled: false,
    how: '只写 data/sandbox/{tenant}/ 下相对路径；同样做路径规范化与沙箱根校验。',
    constraints: ['默认停用', '须有 sandbox_policy', '写入体积有上限'],
    default_sandbox_policy: { fs_root: 'sandbox' },
    model_params: {
      path: p('沙箱内路径', '', { required: true }),
      content: p('内容', '', { required: true }),
    },
    result: { kind: 'text', fields: ['text'], note: '执行结果统一围栏为文本块回图，不走 OA 接口字段白名单。' },
    edit_hint: '实现写在代码目录中，后台不能改路径/算法；可用启停与 Skill 绑定控制是否对员工开放。',
  },
}

function builtinIdOf(detail: ToolDetail): string | null {
  if (detail.builtin_id) return detail.builtin_id
  if (detail.guide?.builtin_id) return detail.guide.builtin_id
  const name = detail.name || ''
  if (name.startsWith('builtin.')) return `sys.${name.slice('builtin.'.length)}`
  return null
}

/** 优先用接口 guide；内置 / MCP / OA 均保证有可读说明。 */
export function resolveToolGuide(detail: ToolDetail | null): ToolGuide | null {
  if (!detail) return null
  if (detail.guide?.how) {
    const g = { ...detail.guide }
    if (!g.sandbox_policy && detail.sandbox_policy) g.sandbox_policy = detail.sandbox_policy
    return g
  }
  const kind = detail.kind || 'office'
  if (kind === 'builtin') {
    const id = builtinIdOf(detail)
    const base = (id && BUILTIN[id]) || {
      kind: 'builtin' as const,
      builtin_id: id || undefined,
      summary: detail.summary || '',
      runtime: 'BuiltinRuntime（进程内）',
      how: '内置工具由 Agent 进程 BuiltinRuntime 执行；具体算法见代码目录 builtin_catalog / builtin_runtime。',
      constraints: ['后台不能改实现代码', '可用启停与 Skill 绑定控制是否开放'],
      edit_hint: '请用列表里的启停开关。',
      result: { kind: 'text', fields: ['text'] },
    }
    return {
      ...base,
      summary: detail.summary || base.summary,
      sandbox_policy: detail.sandbox_policy || base.sandbox_policy || base.default_sandbox_policy || null,
      risk_level: detail.risk_level || base.risk_level,
    }
  }
  if (kind === 'mcp') {
    const schema = detail.current_schema || {}
    const mcp = (schema.mcp || {}) as Record<string, unknown>
    return {
      kind: 'mcp',
      summary: detail.summary || String(schema.summary || schema.description || ''),
      runtime: 'McpRuntime（出站 MCP）',
      how: '定义来自 MCP 服务器 tools/list 同步。调用时由 McpRuntime 按连接配置向远端 tools/call；结果围栏为文本块回图。',
      constraints: [
        '不能在本页改远端工具参数定义；请到「MCP 连接」改配置并重新同步',
        '默认停用，须管理员启用后才可注册到运行时',
        '员工身份不会自动注入到 MCP 参数（与 OA Tool 不同）',
      ],
      mcp_tool_name: detail.mcp_tool_name || (mcp.tool as string) || null,
      description: typeof schema.description === 'string' ? schema.description : null,
      model_params: (schema.model_params as ToolGuide['model_params']) || {},
      input_schema: (mcp.input_schema as Record<string, unknown>) || null,
      result: { kind: 'text', fields: ['text'], note: 'MCP 原始返回会围栏为 text，不走 OA 字段白名单。' },
      edit_hint: '实现在远端 MCP 服务；本系统只同步清单与启停。',
    }
  }
  const schema = detail.current_schema || {}
  return {
    kind: 'office',
    summary: detail.summary || String(schema.summary || ''),
    runtime: 'OfficeApiClient（员工 token）',
    how: '调用时由 ToolExecutor 用员工会话里的 OA token，向所选上游 office-api 发 HTTP；路径只存相对 path。业务授权在 office-api，本系统不访问 OA 业务库。',
    constraints: [
      '身份字段由服务端注入，模型不可伪造 oa / token',
      '只允许契约内 method + path + 参数白名单',
      '结果按 result.fields 白名单回图',
    ],
    http: {
      method: detail.method || (schema.method as string) || null,
      path: detail.path || (schema.path as string) || null,
      upstream: detail.upstream || (schema.upstream as string) || 'office',
      timeout_seconds: schema.timeout_seconds as number | undefined,
    },
    model_params: (schema.model_params as ToolGuide['model_params']) || {},
    result: (schema.result as Record<string, unknown>) || {},
    edit_hint: '可在本页编辑 method/path/参数与结果字段，并走版本激活。',
  }
}
