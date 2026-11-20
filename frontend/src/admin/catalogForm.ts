// Tool / Skill 后台表单 ↔ 接口定义的转换（纯函数，便于测试）
import { normalizeNode } from './schemaTree'
import type { SchemaNode } from './schemaTree'

export interface FieldRow {
  /** 返回字段键；允许一层点路径，如 `user.name` */
  key: string
  label: string
  inList: boolean
}

export interface ToolForm {
  name: string
  summary: string
  description: string
  /** 业务上游标识（连接配置 → 业务上游 / 连接器中的 key；默认常为 office） */
  upstream: string
  path: string
  timeout_seconds: number
  injectOa: boolean
  query_params_field: string
  /** 由服务端填入当前员工 oa 的普通查询参数名，逗号分隔，如 `user_id` */
  identityParams: string
  result_kind: 'list' | 'object'
  /** 模型可填参数：参数名 → SchemaNode（支持 array / object / file 嵌套） */
  modelParams: Record<string, SchemaNode>
  /** 作为顶层查询参数传递的参数名，逗号分隔（其余放进 queryParams JSON） */
  topLevelFields: string
  /** 返回结果根 Schema；null 表示不声明 */
  resultSchema: SchemaNode | null
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

/** 与后端 DEFAULT_UPSTREAM 对齐；office 为历史别名，保存时会与 open_oa 视为同一上游 */
export function emptyToolForm(defaultUpstream = 'open_oa'): ToolForm {
  return {
    name: '', summary: '', description: '', upstream: defaultUpstream || 'open_oa', path: '/',
    timeout_seconds: 10, injectOa: true,
    query_params_field: 'queryParams', identityParams: '', result_kind: 'list',
    modelParams: {}, topLevelFields: '', resultSchema: null, fields: [],
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

export function toolPayload(form: ToolForm): Record<string, unknown> {
  // 参数：逐个规范化为 SchemaNode，丢弃空名；保留 array/object/file 原类型
  const model_params: Record<string, SchemaNode> = {}
  for (const [rawName, node] of Object.entries(form.modelParams)) {
    const name = rawName.trim()
    if (name) model_params[name] = normalizeNode(node)
  }
  const topLevel = splitNames(form.topLevelFields).filter((k) => k in model_params)
  // 返回：字段白名单（key 允许一层点路径）+ 可选根 Schema
  const fields = form.fields.filter((f) => f.key.trim())
  const result: Record<string, unknown> = {
    kind: form.result_kind,
    fields: fields.map((f) => f.key.trim()),
    labels: Object.fromEntries(fields.filter((f) => f.label.trim()).map((f) => [f.key.trim(), f.label.trim()])),
    list_columns: form.result_kind === 'list' ? fields.filter((f) => f.inList).map((f) => f.key.trim()) : [],
  }
  if (form.resultSchema) result.schema = normalizeNode(form.resultSchema)
  return {
    name: form.name.trim(),
    summary: form.summary.trim(),
    description: form.description.trim(),
    method: 'GET',
    upstream: form.upstream || 'open_oa',
    path: form.path.trim(),
    timeout_seconds: form.timeout_seconds,
    inject_identity_fields: form.injectOa ? ['oa'] : [],
    top_level_fields: topLevel,
    query_params_field: form.query_params_field.trim() || null,
    identity_params: Object.fromEntries(splitNames(form.identityParams).map((k) => [k, 'oa'])),
    model_params,
    result,
  }
}

export function toolFormFromSchema(schema: Record<string, any>): ToolForm {
  const top: string[] = schema.top_level_fields || []
  const result = schema.result || {}
  const labels: Record<string, string> = result.labels || {}
  const columns: string[] = result.list_columns || []
  // 库内旧版可能写 office；与 open_oa 等价，展示统一成 open_oa
  const upstream = schema.upstream === 'office' || !schema.upstream ? 'open_oa' : schema.upstream
  return {
    name: schema.name,
    summary: schema.summary || '',
    description: schema.description || '',
    upstream,
    path: schema.path || '/',
    timeout_seconds: schema.timeout_seconds ?? 10,
    injectOa: (schema.inject_identity_fields || []).includes('oa'),
    query_params_field: schema.query_params_field || '',
    identityParams: Object.keys(schema.identity_params || {}).join(', '),
    result_kind: result.kind === 'object' ? 'object' : 'list',
    modelParams: Object.fromEntries(
      Object.entries<unknown>(schema.model_params || {}).map(([name, rule]) => [name, normalizeNode(rule)]),
    ),
    topLevelFields: top.join(', '),
    resultSchema: result.schema ? normalizeNode(result.schema) : null,
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
