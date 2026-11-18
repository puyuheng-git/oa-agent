// SchemaNode 试调值的纯函数：编辑态值 ↔ 调用参数，以及 Schema 变更时的值迁移。
// 编辑态约定：string/integer/number/file 为字符串（file 存 ref 路径），boolean 为 boolean|undefined，
// object 为对象，array 为数组。

import type { SchemaNode } from './schemaTree'

type Values = Record<string, unknown>

function isPlainObject(v: unknown): v is Record<string, unknown> {
  return typeof v === 'object' && v !== null && !Array.isArray(v)
}

function clone<T>(v: T): T {
  return v === undefined ? v : (JSON.parse(JSON.stringify(v)) as T)
}

/** 新增一项 / 初始化时的空值：优先 default（深拷贝）。 */
export function emptyValue(node: SchemaNode): unknown {
  if (node.default !== undefined && node.default !== null) return clone(node.default)
  switch (node.type) {
    case 'boolean':
      return undefined
    case 'array':
      return []
    case 'object':
      return {}
    default:
      return ''
  }
}

/** 编辑态值转调用值；空值/非法值返回 undefined（调用方据此省略该键）。 */
function convertValue(node: SchemaNode, v: unknown): unknown {
  if (v === undefined || v === null) return undefined
  switch (node.type) {
    case 'string': {
      const s = String(v)
      return s === '' ? undefined : s
    }
    case 'integer':
    case 'number': {
      if (typeof v === 'string' && v.trim() === '') return undefined
      const n = typeof v === 'number' ? v : Number(String(v).trim())
      if (!Number.isFinite(n)) return undefined
      // integer 只接受整数，小数视为非法并省略
      if (node.type === 'integer' && !Number.isInteger(n)) return undefined
      return n
    }
    case 'boolean': {
      if (typeof v === 'boolean') return v
      if (v === 'true') return true
      if (v === 'false') return false
      return undefined
    }
    case 'file': {
      // 兼容 {ref} 形态；正常情况下为 ref 字符串
      const raw = isPlainObject(v) ? v.ref : v
      const s = typeof raw === 'string' ? raw.trim() : ''
      return s === '' ? undefined : s
    }
    case 'array': {
      if (!Array.isArray(v)) return undefined
      const items: SchemaNode = node.items ?? { type: 'string' }
      const out = v.map((x) => convertValue(items, x)).filter((x) => x !== undefined)
      return out.length ? out : undefined
    }
    case 'object': {
      if (!isPlainObject(v)) return undefined
      // 未声明 properties 的自由对象：原样透传，显式填写的 `{}` 也保留（用户有意传空对象，
      // 如上游要求可选 object 参数必须存在）；有 properties 的对象全空时仍省略
      if (!node.properties || !Object.keys(node.properties).length) return v
      const out = buildArgsFromValues(node.properties, v)
      return Object.keys(out).length ? out : undefined
    }
    default:
      return undefined
  }
}

/** 按 Schema 把表单编辑值转成调用 args；仅输出 Schema 中声明的键，空值省略。 */
export function buildArgsFromValues(params: Record<string, SchemaNode>, values: Values): Record<string, unknown> {
  const out: Record<string, unknown> = {}
  for (const [key, node] of Object.entries(params)) {
    const val = convertValue(node, values?.[key])
    if (val !== undefined) out[key] = val
  }
  return out
}

/** 单值迁移：类型不一致返回 undefined；object/array 递归保留可保留的部分。 */
function mergeValue(oldNode: SchemaNode, newNode: SchemaNode, v: unknown): unknown {
  if (v === undefined || oldNode.type !== newNode.type) return undefined
  if (newNode.type === 'object') {
    if (!isPlainObject(v)) return undefined
    if (!newNode.properties) return v
    return mergeValuesOnSchemaChange(oldNode.properties ?? {}, newNode.properties, v)
  }
  if (newNode.type === 'array') {
    if (!Array.isArray(v)) return undefined
    const oldItems: SchemaNode = oldNode.items ?? { type: 'string' }
    const newItems: SchemaNode = newNode.items ?? { type: 'string' }
    // items 类型变了则整体丢弃，避免残留错类型元素
    if (oldItems.type !== newItems.type) return undefined
    return v.map((x) => mergeValue(oldItems, newItems, x)).filter((x) => x !== undefined)
  }
  return v
}

/** Schema 变更后迁移已填值：同名同类型保留，其余丢弃；新增/类型变化的键用 default 补齐。 */
export function mergeValuesOnSchemaChange(
  oldSchema: Record<string, SchemaNode>,
  newSchema: Record<string, SchemaNode>,
  oldValues: Values,
): Record<string, unknown> {
  const out: Record<string, unknown> = {}
  for (const [key, newNode] of Object.entries(newSchema)) {
    const oldNode = oldSchema[key]
    let val = oldNode ? mergeValue(oldNode, newNode, oldValues?.[key]) : undefined
    if (val === undefined && newNode.default !== undefined && newNode.default !== null) val = clone(newNode.default)
    if (val !== undefined) out[key] = val
  }
  return out
}
