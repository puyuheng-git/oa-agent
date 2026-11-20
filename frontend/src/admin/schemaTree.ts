// SchemaNode 纯函数：与后端 executor/catalog.py::_normalize_schema_node 对齐
// （深度上限 8；file+multiple → array of file；非法 type 降为 string）。

export type SchemaType = 'string' | 'integer' | 'number' | 'boolean' | 'object' | 'array' | 'file'

export interface SchemaNode {
  type: SchemaType
  label?: string
  description?: string
  required?: boolean
  format?: string
  enum?: unknown[]
  enum_labels?: Record<string, string>
  minimum?: number
  maximum?: number
  default?: unknown
  accept?: string[]
  multiple?: boolean
  properties?: Record<string, SchemaNode>
  items?: SchemaNode
}

export const SCHEMA_TYPES: SchemaType[] = ['string', 'integer', 'number', 'boolean', 'object', 'array', 'file']
export const SCHEMA_MAX_DEPTH = 8

// 直接透传的标量/简单字段（与后端白名单一致，properties/items 另行递归）
const PASSTHROUGH_KEYS = [
  'format', 'enum', 'minimum', 'maximum', 'default', 'description', 'label', 'enum_labels', 'accept',
] as const

function isPlainObject(v: unknown): v is Record<string, unknown> {
  return typeof v === 'object' && v !== null && !Array.isArray(v)
}

/** 后端同款“空值”判定：null/undefined、空串、空数组、空对象。 */
function isEmptyValue(v: unknown): boolean {
  if (v === null || v === undefined || v === '') return true
  if (Array.isArray(v)) return v.length === 0
  if (isPlainObject(v)) return Object.keys(v).length === 0
  return false
}

/** 新建空节点；array 默认 items=string，object 默认 properties={}。 */
export function emptyNode(type: SchemaType = 'string'): SchemaNode {
  const node: SchemaNode = { type }
  if (type === 'array') node.items = { type: 'string' }
  if (type === 'object') node.properties = {}
  return node
}

/** file+multiple 转为 array of file，仅保留 label/description/required，accept 下沉到 items。 */
export function fileMultipleToArray(node: SchemaNode): SchemaNode {
  if (node.type !== 'file' || !node.multiple) return node
  const items: SchemaNode = { type: 'file' }
  if (node.accept && node.accept.length) items.accept = node.accept
  const out: SchemaNode = { type: 'array', items }
  if (node.label) out.label = node.label
  if (node.description) out.description = node.description
  if (node.required) out.required = true
  return out
}

/** 递归规范化任意输入为 SchemaNode；超过深度上限的子节点降为 string 叶子。 */
export function normalizeNode(n: unknown, depth = 0): SchemaNode {
  if (!isPlainObject(n) || depth > SCHEMA_MAX_DEPTH) return { type: 'string' }
  // 非法 type 降为 string
  const type = SCHEMA_TYPES.includes(n.type as SchemaType) ? (n.type as SchemaType) : 'string'
  const out: SchemaNode = { type }
  const bag = out as unknown as Record<string, unknown>
  for (const k of PASSTHROUGH_KEYS) {
    if (k in n && !isEmptyValue(n[k])) bag[k] = n[k]
  }
  if (n.required === true) out.required = true
  if (type === 'file' && n.multiple === true) out.multiple = true
  if (out.accept && !Array.isArray(out.accept)) delete out.accept
  if (out.enum && !Array.isArray(out.enum)) delete out.enum
  if (Array.isArray(out.accept)) out.accept = out.accept.map(String).filter((s) => s.trim())
  if (out.enum_labels) {
    if (isPlainObject(out.enum_labels)) {
      out.enum_labels = Object.fromEntries(
        Object.entries(out.enum_labels).map(([k, v]) => [String(k), String(v)]),
      )
    } else {
      delete out.enum_labels
    }
  }
  // file + multiple → array of file
  if (type === 'file' && out.multiple) return fileMultipleToArray(out)
  if (type === 'object' && isPlainObject(n.properties) && Object.keys(n.properties).length) {
    out.properties = Object.fromEntries(
      Object.entries(n.properties).map(([k, v]) => [k, normalizeNode(v, depth + 1)]),
    )
  }
  if (type === 'array') {
    out.items = n.items == null ? { type: 'string' } : normalizeNode(n.items, depth + 1)
  }
  return out
}

/**
 * 解析枚举文本：每项 `值` 或 `值=显示名`，按换行 / 逗号 / 分号分隔。
 * 数字类型会丢弃非数字项；仅保留 enum 中存在的值对应的 labels。
 */
export function parseEnumText(
  text: string,
  type: SchemaType,
): { enum?: (string | number)[]; enum_labels?: Record<string, string> } {
  const isNum = type === 'integer' || type === 'number'
  const values: (string | number)[] = []
  const labels: Record<string, string> = {}
  for (const item of text.split(/[,，;；\n]/).map((s) => s.trim()).filter(Boolean)) {
    const i = item.indexOf('=')
    const raw = (i >= 0 ? item.slice(0, i) : item).trim()
    const label = i >= 0 ? item.slice(i + 1).trim() : ''
    const value = isNum ? Number(raw) : raw
    // 空值 / 非数字跳过
    if (raw === '' || (isNum && Number.isNaN(value))) continue
    values.push(value)
    if (label) labels[String(value)] = label
  }
  if (!values.length) return {}
  return Object.keys(labels).length ? { enum: values, enum_labels: labels } : { enum: values }
}

/** 枚举回显文本：每行 `值` 或 `值=显示名`。 */
export function enumToText(node: Pick<SchemaNode, 'enum' | 'enum_labels'>): string {
  if (!node.enum?.length) return ''
  return node.enum
    .map((v) => (node.enum_labels?.[String(v)] ? `${v}=${node.enum_labels[String(v)]}` : String(v)))
    .join('\n')
}

/** 解析 JSON 文本为 {name → SchemaNode}；根必须是对象。 */
export function parseSchemaJson(
  text: string,
): { ok: true; value: Record<string, SchemaNode> } | { ok: false; error: string } {
  let raw: unknown
  try {
    raw = JSON.parse(text)
  } catch (e) {
    return { ok: false, error: `JSON 解析失败：${(e as Error).message}` }
  }
  if (!isPlainObject(raw)) return { ok: false, error: '根节点必须是对象（参数名 → Schema）' }
  const value: Record<string, SchemaNode> = {}
  for (const [k, v] of Object.entries(raw)) value[k] = normalizeNode(v)
  return { ok: true, value }
}

/** 序列化为带缩进的 JSON 文本。 */
export function stringifySchema(map: Record<string, SchemaNode>): string {
  return JSON.stringify(map, null, 2)
}
