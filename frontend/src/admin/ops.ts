type TagType = 'success' | 'danger' | 'warning' | 'info' | 'primary'

// ---------------- 人工介入 ----------------

export interface InterventionTask {
  task_id: string
  run_id: string
  kind: 'admin' | 'user_confirm'
  status: string
  reason: string
  node_name: string | null
  error_code: string | null
  expire_at: string | null
  created_at: string
  handled_by: string | null
  handled_at: string | null
  result: string | null
  handle_note: string | null
  version: number
  run: {
    run_id: string
    oa: string
    run_status: string
    workflow_id: string
    workflow_version: string
    started_at: string
    error_code: string | null
  } | null
}

export interface InterventionDetail extends InterventionTask {
  resumable: { ok: boolean; reasons: string[] }
  terminable: { ok: boolean; reasons: string[] }
}

export const TASK_STATUS: Record<string, { label: string; type: TagType }> = {
  pending: { label: '待处理', type: 'warning' },
  resolving: { label: '处理中', type: 'primary' },
  resolved: { label: '已处理', type: 'success' },
  cancelled: { label: '已取消', type: 'info' },
  expired: { label: '已过期', type: 'danger' },
}

export const TASK_KIND: Record<string, string> = {
  admin: '管理员介入',
  user_confirm: '员工确认（管理员不可代办）',
}

// ---------------- Tool / Skill ----------------

export type ToolKind = 'office' | 'builtin' | 'mcp'

export interface ToolItem {
  name: string
  kind?: ToolKind
  summary: string
  method: string | null
  path: string | null
  upstream: string | null
  source_file: string
  enabled: boolean
  spec_enabled: boolean
  risk_level: string
  requires_confirmation: boolean
  builtin_id?: string | null
  mcp_server_id?: number | null
  mcp_tool_name?: string | null
  sandbox_policy?: Record<string, unknown> | null
  registered: boolean
  unregistered_reasons: string[]
  current_version_no: number | null
  pending_version_no: number | null
  pending_compat: string | null
  last_sync_at: string | null
  last_sync_result: string | null
  last_sync_error: string | null
  updated_by: string
  updated_at: string
}

export interface ToolVersion {
  version_no: number
  spec_version: string
  schema_hash: string
  compat_level: string
  created_by: string
  created_at: string
  is_current: boolean
  is_pending: boolean
}

export interface ToolGuide {
  kind: ToolKind | string
  summary?: string
  how?: string
  constraints?: string[]
  runtime?: string
  edit_hint?: string
  builtin_id?: string
  risk_level?: string
  default_enabled?: boolean
  needs_sandbox?: boolean
  default_sandbox_policy?: Record<string, unknown>
  sandbox_policy?: Record<string, unknown> | null
  model_params?: Record<string, { type?: string; label?: string; description?: string; required?: boolean; enum?: string[] }>
  identity_params?: Record<string, unknown>
  result?: Record<string, unknown>
  http?: { method?: string | null; path?: string | null; upstream?: string; timeout_seconds?: number }
  mcp_server?: {
    id?: number
    name?: string | null
    display_name?: string | null
    transport?: string | null
    enabled?: boolean
    missing?: boolean
  } | null
  mcp_tool_name?: string | null
  description?: string | null
  input_schema?: Record<string, unknown> | null
}

export interface ToolDetail extends ToolItem {
  versions: ToolVersion[]
  current_schema: Record<string, any> | null
  guide?: ToolGuide | null
}

export interface DiffChange {
  field: string
  change: 'added' | 'removed' | 'changed'
  old: unknown
  new: unknown
  breaking: boolean
}

export interface SkillItem {
  name: string
  display_name: string
  source_file: string
  enabled: boolean
  validation_status: string
  validation_errors: string[]
  current_version_no: number | null
  workflow: string | null
  description: string | null
  instructions: string
  examples: string[]
  tools: { name: string; registered: boolean }[]
  last_sync_at: string | null
  last_sync_result: string | null
  last_sync_error: string | null
}

export const SYNC_RESULT: Record<string, { label: string; type: TagType }> = {
  initial: { label: '首次导入', type: 'success' },
  unchanged: { label: '无变化', type: 'info' },
  compatible: { label: '兼容变更·已生效', type: 'success' },
  breaking_pending: { label: '不兼容·待激活', type: 'warning' },  updated: { label: '已更新', type: 'success' },
  removed: { label: '已从规范移除', type: 'danger' },
  error: { label: '同步失败·保留旧版本', type: 'danger' },
}

export const COMPAT_LEVEL: Record<string, { label: string; type: TagType }> = {
  initial: { label: '初始', type: 'info' },
  compatible: { label: '兼容', type: 'success' },
  breaking: { label: '不兼容', type: 'danger' },
}

export function syncTag(result: string | null): { label: string; type: TagType } {
  if (!result) return { label: '未同步', type: 'info' }
  return SYNC_RESULT[result] ?? { label: result, type: 'info' }
}

// ---------------- Workflow 配置 ----------------

export interface WorkflowVersion {
  version_id: string
  version_no: number | null
  status: 'draft' | 'validated' | 'published'
  content: Record<string, any>
  content_hash: string
  validation: { ok: boolean; errors: string[]; validated_at?: string } | null
  validated_hash: string | null
  created_by: string
  created_at: string
  updated_by: string
  updated_at: string
  published_at: string | null
}

export interface ConfigRelease {
  release_id: string
  version_no: number
  release_type: 'publish' | 'rollback'
  reason: string
  previous_release_id: string | null
  released_by: string
  released_at: string
}

export interface WorkflowDetail {
  workflow_id: string
  current_release: ConfigRelease | null
  current_version: WorkflowVersion | null
  draft: WorkflowVersion | null
  versions: WorkflowVersion[]
  releases: ConfigRelease[]
}

export interface FieldDef {
  key: string
  label: string
  kind: 'enum' | 'model' | 'int' | 'text' | 'skill' | 'bool'
  group?: string
  options?: { value: string; label: string }[]
  min?: number
  max?: number
  unit?: string
  default?: unknown
  help?: string
}

export interface WorkflowSchema {
  fields: FieldDef[]
  groups?: string[]
  defaults?: Record<string, unknown>
  models: { id: number; label: string; enabled: boolean }[]
  skills: { name: string; label: string; status: string }[]
}

export const DRAFT_STATUS: Record<string, { label: string; type: TagType }> = {
  draft: { label: '草稿（未校验）', type: 'warning' },
  validated: { label: '已校验，可发布', type: 'success' },
  published: { label: '已发布', type: 'info' },
}

/** 配置项的可读值（diff 与版本列表共用）。 */
export function displayValue(field: FieldDef | undefined, value: unknown, schema?: WorkflowSchema): string {
  if (value === null || value === undefined || value === '') {
    return field?.kind === 'model' ? '默认模型' : '—'
  }
  if (field?.kind === 'enum') return field.options?.find((o) => o.value === value)?.label ?? String(value)
  if (field?.kind === 'bool') return value === true ? '开启' : value === false ? '关闭' : String(value)
  if (field?.kind === 'int' && field.unit) return `${value} ${field.unit}`
  if (field?.kind === 'model') {
    const m = schema?.models.find((x) => x.id === value)
    return m ? `${m.label}（#${m.id}）` : `#${value}`
  }
  if (typeof value === 'string' && value.length > 60) return `${value.slice(0, 60)}…`
  return String(value)
}

/** 按 group 分组，保持服务端给出的组顺序；没有 group 的字段归入「其他」。 */
export function groupFields(fields: FieldDef[], groups: string[] = []): { name: string; fields: FieldDef[] }[] {
  const order = [...groups]
  for (const f of fields) if (!order.includes(f.group ?? '其他')) order.push(f.group ?? '其他')
  return order
    .map((name) => ({ name, fields: fields.filter((f) => (f.group ?? '其他') === name) }))
    .filter((g) => g.fields.length)
}

/** 前端只做提示性校验；以服务端校验结果为准。 */
export function localValidate(content: Record<string, any>, fields: FieldDef[]): string[] {
  const errors: string[] = []
  for (const f of fields) {
    const v = content[f.key]
    if (v === undefined) continue // 旧版本没有的字段按默认值运行，缺失与否以服务端校验为准
    if (f.kind === 'int') {
      if (!Number.isInteger(v) || (f.min !== undefined && v < f.min) || (f.max !== undefined && v > f.max)) {
        errors.push(`${f.label}必须是 ${f.min}～${f.max} 的整数`)
      }
    } else if (f.kind === 'text' && (typeof v !== 'string' || (f.max !== undefined && v.length > f.max))) {
      errors.push(`${f.label}必须是不超过 ${f.max ?? '—'} 字的文本`)
    } else if (f.kind === 'enum' && !f.options?.some((o) => o.value === v)) {
      errors.push(`${f.label}取值无效`)
    } else if (f.kind === 'bool' && typeof v !== 'boolean') {
      errors.push(`${f.label}必须是开或关`)
    }
  }
  return errors
}
