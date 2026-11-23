// Tool / Skill 后台表单 ↔ 接口定义的转换（纯函数，便于测试）
import { normalizeNode } from './schemaTree'
import type { SchemaNode, SchemaType } from './schemaTree'

export interface FieldRow {
  /** 返回字段键；允许一层点路径，如 `user.name` */
  key: string
  label: string
  inList: boolean
}

/** 扁平参数行（主表单）；复杂嵌套仍可经 modelParams 高级编辑保留 */
export interface ParamRow {
  name: string
  type: SchemaType
  required: boolean
  label: string
  description: string
  /** 直接作为查询参数；其余进打包字段 JSON */
  topLevel: boolean
}

/** 员工身份写入请求的位置 */
export type IdentityPlacement = 'independent' | 'bag'

export interface ToolForm {
  name: string
  summary: string
  description: string
  /** 业务上游标识（连接配置 → 业务上游；office 为历史别名） */
  upstream: string
  path: string
  timeout_seconds: number
  /** 是否由服务端注入当前员工账号 */
  injectOa: boolean
  /** 请求里的键名，默认 oa，可改为 user_id 等 */
  identityParamName: string
  /** 独立参数 = 平铺 query；bag = 写入打包字段 JSON 对象内 */
  identityPlacement: IdentityPlacement
  /** 打包字段名（如 queryParams / params）；placement=bag 时必填 */
  query_params_field: string
  /**
   * 额外的普通 query 身份键（高级）；逗号分隔。
   * 主路径用 identityParamName；此处仅兼容旧「身份查询参数」多键场景。
   */
  identityParams: string
  result_kind: 'list' | 'object'
  /** 模型可填参数：参数名 → SchemaNode */
  modelParams: Record<string, SchemaNode>
  /** 顶层查询参数名，逗号分隔（与 ParamRow.topLevel 同步） */
  topLevelFields: string
  fields: FieldRow[]
}

export interface SkillForm {
  name: string
  display_name: string
  description: string
  instructions: string
  examplesText: string
  /** 空串不限制可绑 Tool 类型 */
  category?: string
  tools: string[]
}

/** 与后端 DEFAULT_UPSTREAM 对齐；office 为历史别名 */
export function emptyToolForm(defaultUpstream = 'open_oa'): ToolForm {
  return {
    name: '', summary: '', description: '', upstream: defaultUpstream || 'open_oa', path: '/',
    timeout_seconds: 10, injectOa: true, identityParamName: 'oa', identityPlacement: 'bag',
    query_params_field: 'queryParams', identityParams: '', result_kind: 'list',
    modelParams: {}, topLevelFields: '', fields: [],
  }
}

export function emptySkillForm(): SkillForm {
  return {
    name: '', display_name: '', description: '', instructions: '', examplesText: '',
    category: '', tools: [],
  }
}

/** 逗号 / 空白分隔的名称列表 */
function splitNames(text: string): string[] {
  return text.split(/[,，\s]+/).map((s) => s.trim()).filter(Boolean)
}

/** modelParams + topLevelFields → 扁平行（便于表格编辑） */
export function paramRowsFromForm(form: ToolForm): ParamRow[] {
  const top = new Set(splitNames(form.topLevelFields))
  return Object.entries(form.modelParams).map(([name, node]) => ({
    name,
    type: (node.type || 'string') as SchemaType,
    required: !!node.required,
    label: node.label || '',
    description: node.description || '',
    topLevel: top.has(name),
  }))
}

/** 扁平行写回 modelParams / topLevelFields；表格未列出的键（高级树新增）予以保留 */
export function applyParamRows(form: ToolForm, rows: ParamRow[]): void {
  const next: Record<string, SchemaNode> = {}
  const top: string[] = []
  const seen = new Set<string>()
  for (const row of rows) {
    const name = row.name.trim()
    if (!name) continue
    seen.add(name)
    const prev = form.modelParams[name]
    const node: SchemaNode = prev ? { ...normalizeNode(prev), type: row.type } : { type: row.type }
    node.type = row.type
    if (row.required) node.required = true
    else delete node.required
    if (row.label.trim()) node.label = row.label.trim()
    else delete node.label
    if (row.description.trim()) node.description = row.description.trim()
    else delete node.description
    // 类型从 object/array 改成标量时清掉嵌套，避免脏数据
    if (row.type !== 'object') delete node.properties
    if (row.type !== 'array') delete node.items
    if (row.type === 'object' && !node.properties) node.properties = {}
    if (row.type === 'array' && !node.items) node.items = { type: 'string' }
    next[name] = normalizeNode(node)
    if (row.topLevel) top.push(name)
  }
  for (const [name, node] of Object.entries(form.modelParams)) {
    if (!seen.has(name)) next[name] = normalizeNode(node)
  }
  form.modelParams = next
  form.topLevelFields = top.join(', ')
}

function identityParamFromSchema(schema: Record<string, any>): { name: string; inject: boolean } {
  const bindings = schema.identity_bindings
  if (Array.isArray(bindings) && bindings.length) {
    const first = bindings[0]
    const param = String(first?.param || '').trim()
    if (param) return { name: param, inject: true }
  }
  const inject = schema.inject_identity_fields || []
  if (Array.isArray(inject) && inject.includes('oa')) return { name: 'oa', inject: true }
  const idParams = schema.identity_params || {}
  const keys = Object.keys(idParams)
  if (keys.length) return { name: keys[0], inject: true }
  return { name: 'oa', inject: false }
}

export function toolPayload(form: ToolForm): Record<string, unknown> {
  const model_params: Record<string, SchemaNode> = {}
  for (const [rawName, node] of Object.entries(form.modelParams)) {
    const name = rawName.trim()
    if (name) model_params[name] = normalizeNode(node)
  }
  const topLevel = splitNames(form.topLevelFields).filter((k) => k in model_params)
  const fields = form.fields.filter((f) => f.key.trim())
  const result: Record<string, unknown> = {
    kind: form.result_kind,
    fields: fields.map((f) => f.key.trim()),
    labels: Object.fromEntries(fields.filter((f) => f.label.trim()).map((f) => [f.key.trim(), f.label.trim()])),
    list_columns: form.result_kind === 'list' ? fields.filter((f) => f.inList).map((f) => f.key.trim()) : [],
  }
  const paramName = (form.identityParamName || 'oa').trim() || 'oa'
  const bagName = form.query_params_field.trim()
  const useBag = form.identityPlacement === 'bag'
  // 打包：身份进 JSON；独立：身份平铺（identity_params），不写 bindings 以免进袋
  const inject = form.injectOa
  const identity_bindings = inject && useBag
    ? [{ param: paramName, from: 'identity.oa' }]
    : []
  const identity_params: Record<string, string> = {}
  if (inject && !useBag) identity_params[paramName] = 'oa'
  for (const k of splitNames(form.identityParams)) {
    if (k !== paramName) identity_params[k] = 'oa'
  }
  return {
    name: form.name.trim(),
    summary: form.summary.trim(),
    description: form.description.trim(),
    method: 'GET',
    upstream: form.upstream || 'open_oa',
    path: form.path.trim(),
    timeout_seconds: form.timeout_seconds,
    inject_identity_fields: inject && useBag && paramName === 'oa' ? ['oa'] : [],
    identity_bindings,
    top_level_fields: topLevel,
    query_params_field: useBag ? (bagName || 'queryParams') : (bagName || null),
    identity_params,
    model_params,
    result,
  }
}

export function toolFormFromSchema(schema: Record<string, any>): ToolForm {
  const top: string[] = schema.top_level_fields || []
  const result = schema.result || {}
  const labels: Record<string, string> = result.labels || {}
  const columns: string[] = result.list_columns || []
  const upstream = schema.upstream === 'office' || !schema.upstream ? 'open_oa' : schema.upstream
  const id = identityParamFromSchema(schema)
  const bag = String(schema.query_params_field || '').trim()
  const hasBindings = Array.isArray(schema.identity_bindings) && schema.identity_bindings.length > 0
  const hasInject = (schema.inject_identity_fields || []).includes('oa')
  const flatIdentityOnly = Object.keys(schema.identity_params || {}).length > 0 && !hasBindings && !hasInject
  // 旧数据：queryParams+inject → bag；仅 identity_params → independent
  const identityPlacement: IdentityPlacement = flatIdentityOnly ? 'independent' : (bag ? 'bag' : 'independent')
  const idKeys = Object.keys(schema.identity_params || {})
  const extraKeys = idKeys.filter((k) => k !== id.name)
  return {
    name: schema.name,
    summary: schema.summary || '',
    description: schema.description || '',
    upstream,
    path: schema.path || '/',
    timeout_seconds: schema.timeout_seconds ?? 10,
    injectOa: id.inject,
    identityParamName: id.name,
    identityPlacement,
    query_params_field: bag,
    identityParams: extraKeys.join(', '),
    result_kind: result.kind === 'object' ? 'object' : 'list',
    modelParams: Object.fromEntries(
      Object.entries<unknown>(schema.model_params || {}).map(([name, rule]) => [name, normalizeNode(rule)]),
    ),
    topLevelFields: top.join(', '),
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
    category: (form.category || '').trim(),
    tools: form.tools,
  }
}
