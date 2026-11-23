// 向导 / open_oa_invoke：one_by_params、page_list 时把 PHP 形参袋 params|data 摊平到顶层。
// Service 侧 one_by_params 是 $method($clean)，page_list 是 $method($clean,$page,$limit)；
// 若 args 仍带 { params: { a: 1 } }，业务方法收到的是多套一层的数组。

import type { SchemaNode } from './schemaTree'
import { normalizeNode } from './schemaTree'

/** 常见「整包参数」形参名（与 Export 反射 describe 一致） */
export const BAG_PARAM_NAMES = ['params', 'data'] as const

export function isBagCall(call: string): boolean {
  return call === 'one_by_params' || call === 'page_list'
}

/**
 * 试调 / 入库 / 运行时：若 call 为整包模式且存在 params|data 对象，将其字段合并到顶层。
 * 顶层已有键（如 page/limit）优先，不被袋内同名覆盖。
 */
export function unwrapBagArgs(call: string, args: Record<string, unknown>): Record<string, unknown> {
  if (!isBagCall(call) || !args || typeof args !== 'object') return args || {}
  const out: Record<string, unknown> = { ...args }
  for (const bag of BAG_PARAM_NAMES) {
    const inner = out[bag]
    if (!inner || typeof inner !== 'object' || Array.isArray(inner)) continue
    delete out[bag]
    return { ...(inner as Record<string, unknown>), ...out }
  }
  return out
}

function inferTypeFromValue(v: unknown): SchemaNode['type'] {
  if (typeof v === 'number') return Number.isInteger(v) ? 'integer' : 'number'
  if (typeof v === 'boolean') return 'boolean'
  if (Array.isArray(v)) return 'array'
  if (v && typeof v === 'object') return 'object'
  return 'string'
}

/**
 * describe 预填或入库前：
 * - object 袋有 properties → 提升为顶层并删除袋键
 * - 无结构 array 袋 → 转为可编辑自由 object（不再静默删光）
 * - 自由 object 无 properties：有试调值则推断字段后删袋；否则保留自由 object 袋供键值编辑
 */
export function flattenBagSchema(
  call: string,
  schema: Record<string, SchemaNode>,
  values?: Record<string, unknown>,
): Record<string, SchemaNode> {
  if (!isBagCall(call)) return schema
  const out: Record<string, SchemaNode> = { ...schema }
  for (const bag of BAG_PARAM_NAMES) {
    const node = out[bag]
    if (!node || (node.type !== 'object' && node.type !== 'array')) continue

    // 无结构 array 袋（PHP assoc / 自由对象）：改成可编辑自由 object，勿删
    if (node.type === 'array') {
      const itemProps = node.items?.properties
      if (itemProps && Object.keys(itemProps).length) {
        // 真列表：保留 array，不提升、不删除
        continue
      }
      out[bag] = normalizeNode({
        type: 'object',
        label: node.label || bag,
        description: node.description || '',
        required: !!node.required,
      })
      continue
    }

    const props = node.properties || {}
    for (const [k, v] of Object.entries(props)) {
      if (k === bag) continue
      if (!(k in out)) out[k] = v
    }
    // 自由对象：从当前试调值推断顶层字段
    if (!Object.keys(props).length && values && values[bag] && typeof values[bag] === 'object' && !Array.isArray(values[bag])) {
      for (const [k, v] of Object.entries(values[bag] as Record<string, unknown>)) {
        if (k in out || k === bag) continue
        out[k] = normalizeNode({ type: inferTypeFromValue(v), label: k })
      }
      delete out[bag]
      continue
    }
    if (Object.keys(props).length) {
      delete out[bag]
      continue
    }
    // 无 properties、无试调值：保留自由 object 袋，供测调键值编辑
    out[bag] = normalizeNode({
      type: 'object',
      label: node.label || bag,
      description: node.description || '',
      required: !!node.required,
    })
  }
  return out
}
