// Tool / Skill 后台表单 ↔ 接口定义的转换（纯函数，便于测试）

export interface ParamRow {
  name: string
  label: string
  type: 'string' | 'integer'
  format: '' | 'date'
  required: boolean
  /** 可选值：`0=未报销, 1=已报销` 或 `1, 2`，逗号/分号/换行分隔 */
  enumText: string
  minimum: number | null
  maximum: number | null
  defaultValue: string
  description: string
  /** 作为顶层查询参数传递（否则放进 queryParams JSON） */
  topLevel: boolean
}

export interface FieldRow {
  key: string
  label: string
  inList: boolean
}

export interface ToolForm {
  name: string
  summary: string
  description: string
  /** 业务上游标识（「OA 对接」目录中的 key；默认常为 office） */
  upstream: string
  path: string
  timeout_seconds: number
  injectOa: boolean
  query_params_field: string
  /** 由服务端填入当前员工 oa 的普通查询参数名，逗号分隔，如 `user_id` */
  identityParams: string
  result_kind: 'list' | 'object'
  params: ParamRow[]
  fields: FieldRow[]
}

export interface SkillForm {
  name: string
  display_name: string
  description: string
  instructions: string
  examplesText: string
  tools: string[]
}

export function emptyParam(): ParamRow {
  return {
    name: '', label: '', type: 'string', format: '', required: false, enumText: '',
    minimum: null, maximum: null, defaultValue: '', description: '', topLevel: false,
  }
}

export function emptyToolForm(defaultUpstream = 'office'): ToolForm {
  return {
    name: '', summary: '', description: '', upstream: defaultUpstream || 'office', path: '/',
    timeout_seconds: 10, injectOa: true,
    query_params_field: 'queryParams', identityParams: '', result_kind: 'list', params: [], fields: [],
  }
}

export function emptySkillForm(): SkillForm {
  return { name: '', display_name: '', description: '', instructions: '', examplesText: '', tools: [] }
}

function typed(value: string, type: ParamRow['type']): string | number {
  const n = Number(value)
  return type === 'integer' && value.trim() !== '' && Number.isFinite(n) ? n : value
}

export function parseEnum(text: string, type: ParamRow['type']): {
  enum?: (string | number)[]
  enum_labels?: Record<string, string>
} {
  const items = text.split(/[,，;；\n]/).map((s) => s.trim()).filter(Boolean)
  if (!items.length) return {}
  const values: (string | number)[] = []
  const labels: Record<string, string> = {}
  for (const item of items) {
    const i = item.indexOf('=')
    const raw = (i >= 0 ? item.slice(0, i) : item).trim()
    const value = typed(raw, type)
    values.push(value)
    if (i >= 0 && item.slice(i + 1).trim()) labels[String(value)] = item.slice(i + 1).trim()
  }
  return Object.keys(labels).length ? { enum: values, enum_labels: labels } : { enum: values }
}

export function enumText(rule: { enum?: unknown[]; enum_labels?: Record<string, string> }): string {
  if (!rule.enum?.length) return ''
  return rule.enum
    .map((v) => (rule.enum_labels?.[String(v)] ? `${v}=${rule.enum_labels[String(v)]}` : String(v)))
    .join(', ')
}

export function toolPayload(form: ToolForm): Record<string, unknown> {
  const model_params: Record<string, Record<string, unknown>> = {}
  for (const p of form.params) {
    const name = p.name.trim()
    if (!name) continue
    const rule: Record<string, unknown> = { type: p.type, required: p.required }
    if (p.format) rule.format = p.format
    if (p.label.trim()) rule.label = p.label.trim()
    if (p.description.trim()) rule.description = p.description.trim()
    Object.assign(rule, parseEnum(p.enumText, p.type))
    if (p.minimum !== null && p.minimum !== undefined) rule.minimum = p.minimum
    if (p.maximum !== null && p.maximum !== undefined) rule.maximum = p.maximum
    if (p.defaultValue.trim()) rule.default = typed(p.defaultValue.trim(), p.type)
    model_params[name] = rule
  }
  const fields = form.fields.filter((f) => f.key.trim())
  return {
    name: form.name.trim(),
    summary: form.summary.trim(),
    description: form.description.trim(),
    method: 'GET',
    upstream: form.upstream || 'office',
    path: form.path.trim(),
    timeout_seconds: form.timeout_seconds,
    inject_identity_fields: form.injectOa ? ['oa'] : [],
    top_level_fields: form.params.filter((p) => p.topLevel && p.name.trim()).map((p) => p.name.trim()),
    query_params_field: form.query_params_field.trim() || null,
    identity_params: Object.fromEntries(
      form.identityParams.split(/[,，\s]+/).map((s) => s.trim()).filter(Boolean).map((k) => [k, 'oa']),
    ),
    model_params,
    result: {
      kind: form.result_kind,
      fields: fields.map((f) => f.key.trim()),
      labels: Object.fromEntries(fields.filter((f) => f.label.trim()).map((f) => [f.key.trim(), f.label.trim()])),
      list_columns: form.result_kind === 'list' ? fields.filter((f) => f.inList).map((f) => f.key.trim()) : [],
    },
  }
}

export function toolFormFromSchema(schema: Record<string, any>): ToolForm {
  const top: string[] = schema.top_level_fields || []
  const result = schema.result || {}
  const labels: Record<string, string> = result.labels || {}
  const columns: string[] = result.list_columns || []
  return {
    name: schema.name,
    summary: schema.summary || '',
    description: schema.description || '',
    upstream: schema.upstream || 'office',
    path: schema.path || '/',
    timeout_seconds: schema.timeout_seconds ?? 10,
    injectOa: (schema.inject_identity_fields || []).includes('oa'),
    query_params_field: schema.query_params_field || '',
    identityParams: Object.keys(schema.identity_params || {}).join(', '),
    result_kind: result.kind === 'object' ? 'object' : 'list',
    params: Object.entries<Record<string, any>>(schema.model_params || {}).map(([name, rule]) => ({
      name,
      label: rule.label || '',
      type: rule.type === 'integer' ? 'integer' : 'string',
      format: rule.format === 'date' ? 'date' : '',
      required: !!rule.required,
      enumText: enumText(rule),
      minimum: rule.minimum ?? null,
      maximum: rule.maximum ?? null,
      defaultValue: rule.default === undefined || rule.default === null ? '' : String(rule.default),
      description: rule.description || '',
      topLevel: top.includes(name),
    })),
    fields: (result.fields || []).map((key: string) => ({
      key,
      label: labels[key] || '',
      inList: columns.includes(key),
    })),
  }
}

export function skillPayload(form: SkillForm): Record<string, unknown> {
  return {
    name: form.name.trim(),
    display_name: form.display_name.trim(),
    description: form.description.trim(),
    instructions: form.instructions.trim(),
    examples: form.examplesText.split('\n').map((s) => s.trim()).filter(Boolean),
    tools: form.tools,
  }
}
