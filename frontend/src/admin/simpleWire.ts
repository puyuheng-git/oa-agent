/**
 * 极简模式：自动布线与测调校验（不改落库字段结构，只补齐默认）。
 */
import type { ToolForm } from './catalogForm'
import { isExportTarget } from './paramWire'
import { buildArgsFromValues } from './schemaValue'
import type { SchemaNode } from './schemaTree'

/** 常见整包袋形参名（与 Export 反射 / wizardCallArgs 对齐） */
export const SIMPLE_BAG_NAMES = new Set([
  'params', 'data', 'payload', 'opt', 'args', 'options', 'extra', 'queryparams',
])

export function isLikelyBagParamName(name: string): boolean {
  return SIMPLE_BAG_NAMES.has(name.trim().toLowerCase())
}

/**
 * 保存/测调前：补齐 placement，encoding 保持 auto。
 * 极简模式强制注入身份；专家模式尊重表单上的 inject 开关。
 * Export 的 invoke_call / 槽位仍由 callSignature 路径写入。
 */
export function ensureSimpleWireDefaults(
  form: ToolForm,
  mode: 'simple' | 'expert' = 'simple',
): void {
  if (mode === 'simple') {
    form.injectOa = true
    if (!form.identityParamName.trim()) form.identityParamName = 'oa'
  } else if (form.injectOa && !form.identityParamName.trim()) {
    form.identityParamName = 'oa'
  }

  const isExport = isExportTarget(form.invoke_service, form.invoke_method)
  const method = (form.method || 'GET').toUpperCase() === 'POST' ? 'POST' : 'GET'
  const hasBag = !!form.query_params_field.trim()
  const call = (form.invoke_call || '').trim()

  for (const [name, node] of Object.entries(form.modelParams)) {
    if (!node || typeof node !== 'object') continue
    // encoding 缺省即 auto
    if (!node.encoding || node.encoding === 'auto') delete node.encoding
    if (node.placement) continue
    if (isExport) {
      // named_args：缺省独立形参；整包 call 且袋名才 bag
      if ((call === 'one_by_params' || call === 'page_list') && isLikelyBagParamName(name)) {
        node.placement = 'bag'
      } else if (hasBag && isLikelyBagParamName(name)) {
        node.placement = 'bag'
      } else {
        node.placement = 'scalar'
      }
    } else if (hasBag && isLikelyBagParamName(name)) {
      node.placement = 'bag'
    } else {
      node.placement = method === 'POST' ? 'body' : 'query'
    }
  }
}

/** 必填且无默认值、测调值又为空的参数名 */
export function missingRequiredParamNames(
  modelParams: Record<string, SchemaNode>,
  values: Record<string, unknown>,
): string[] {
  const filled = buildArgsFromValues(modelParams, values)
  const missing: string[] = []
  for (const [name, node] of Object.entries(modelParams)) {
    if (!node?.required) continue
    if (node.default !== undefined && node.default !== null) continue
    if (!(name in filled)) missing.push(name)
  }
  return missing
}

export function formatMissingRequiredMessage(names: string[]): string {
  if (!names.length) return ''
  return `还缺少必填参数：${names.join('、')}`
}
