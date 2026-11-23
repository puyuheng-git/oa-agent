/**
 * Export / Tool 调用形参槽位：预设、预览、与 invoke_call / ToolForm 互相同步。
 * 覆盖：method($oa)、($oa,$array)、($array)、多袋、($array,$page,$limit)。
 */

import type { IdentityPlacement, ToolForm } from './catalogForm'

export type CallSlotRole = 'identity' | 'bag' | 'scalar'
export type InvokeCall = 'one_by_params' | 'page_list' | 'named_args'

export interface CallSlot {
  role: CallSlotRole
  /** 形参名，如 oa / params / page */
  name: string
}

export interface CallPreset {
  id: string
  label: string
  /** 预览示例用的方法名 */
  sampleMethod: string
  slots: CallSlot[]
}

export const CALL_PRESETS: CallPreset[] = [
  {
    id: 'identity_only',
    label: '仅身份 method($oa)',
    sampleMethod: 'method1',
    slots: [{ role: 'identity', name: 'oa' }],
  },
  {
    id: 'identity_bag',
    label: '身份 + 参数袋 method($oa, $params)',
    sampleMethod: 'method2',
    slots: [
      { role: 'identity', name: 'oa' },
      { role: 'bag', name: 'params' },
    ],
  },
  {
    id: 'bag_only',
    label: '仅参数袋 method($params)',
    sampleMethod: 'method3',
    slots: [{ role: 'bag', name: 'params' }],
  },
  {
    id: 'two_bags',
    label: '两个参数袋 method($params, $data)',
    sampleMethod: 'method4',
    slots: [
      { role: 'bag', name: 'params' },
      { role: 'bag', name: 'data' },
    ],
  },
  {
    id: 'three_bags',
    label: '三个参数袋',
    sampleMethod: 'method4',
    slots: [
      { role: 'bag', name: 'params' },
      { role: 'bag', name: 'data' },
      { role: 'bag', name: 'extra' },
    ],
  },
  {
    id: 'bag_page_limit',
    label: '参数袋 + 分页 method($params, $page, $limit)',
    sampleMethod: 'method5',
    slots: [
      { role: 'bag', name: 'params' },
      { role: 'scalar', name: 'page' },
      { role: 'scalar', name: 'limit' },
    ],
  },
]

/** 生成 PHP 风格调用预览，如 getFoo($oa, $params) */
export function previewCall(methodName: string, slots: CallSlot[]): string {
  const method = (methodName || '').trim() || 'method'
  const args = slots
    .map((s) => {
      const n = (s.name || '').trim()
      return n ? `$${n}` : '$?'
    })
    .join(', ')
  return `${method}(${args})`
}

/**
 * 由槽位推断 invoke_call。
 * - 仅一袋（可带标量 page/limit）→ page_list 或 one_by_params
 * - 含身份或多个袋 → named_args
 */
export function inferInvokeCall(slots: CallSlot[]): InvokeCall {
  const roles = slots.map((s) => s.role)
  const bags = slots.filter((s) => s.role === 'bag')
  const hasIdentity = roles.includes('identity')
  const scalars = slots.filter((s) => s.role === 'scalar').map((s) => s.name.trim())
  const hasPageLimit = scalars.includes('page') && scalars.includes('limit')

  if (!hasIdentity && bags.length === 1 && hasPageLimit) return 'page_list'
  if (!hasIdentity && bags.length === 1 && scalars.length === 0) return 'one_by_params'
  if (!hasIdentity && bags.length === 1 && hasPageLimit && scalars.every((n) => n === 'page' || n === 'limit')) {
    return 'page_list'
  }
  // 单袋 + 其它标量、多袋、或带身份 → named_args
  if (!hasIdentity && bags.length === 1 && !hasPageLimit) return 'one_by_params'
  return 'named_args'
}

export function findPresetId(slots: CallSlot[]): string | '' {
  const key = JSON.stringify(slots.map((s) => [s.role, s.name.trim()]))
  for (const p of CALL_PRESETS) {
    const pk = JSON.stringify(p.slots.map((s) => [s.role, s.name.trim()]))
    if (pk === key) return p.id
  }
  return ''
}

export function slotsFromPresetId(id: string): CallSlot[] {
  const p = CALL_PRESETS.find((x) => x.id === id)
  return p ? p.slots.map((s) => ({ ...s })) : CALL_PRESETS[2].slots.map((s) => ({ ...s }))
}

/** describe 返回的形参 → 初始槽位 */
export function slotsFromDescribe(
  params: { name?: string; kind?: string; type?: string }[] | undefined,
  callSuggest?: string,
): CallSlot[] {
  const list = params || []
  if (!list.length) {
    if (callSuggest === 'page_list') return slotsFromPresetId('bag_page_limit')
    if (callSuggest === 'named_args') return slotsFromPresetId('identity_bag')
    return slotsFromPresetId('bag_only')
  }
  const slots: CallSlot[] = []
  for (const p of list) {
    const name = String(p.name || '').trim()
    if (!name) continue
    const kind = String(p.kind || '').toLowerCase()
    const type = String(p.type || '').toLowerCase()
    if (name === 'oa' || name === 'user_id' || kind === 'identity') {
      slots.push({ role: 'identity', name })
    } else if (
      kind === 'bag' || type === 'array' || type === 'object'
      || name === 'params' || name === 'data'
    ) {
      slots.push({ role: 'bag', name })
    } else {
      slots.push({ role: 'scalar', name })
    }
  }
  // page_list 建议且缺 page/limit 时补上
  if (callSuggest === 'page_list') {
    const names = new Set(slots.map((s) => s.name))
    if (!names.has('page')) slots.push({ role: 'scalar', name: 'page' })
    if (!names.has('limit')) slots.push({ role: 'scalar', name: 'limit' })
  }
  return slots.length ? slots : slotsFromPresetId('bag_only')
}

/** ToolForm 身份/打包 → 槽位（B 侧回填） */
export function slotsFromToolForm(form: Pick<
  ToolForm,
  'injectOa' | 'identityParamName' | 'identityPlacement' | 'query_params_field' | 'topLevelFields' | 'modelParams' | 'invoke_call'
>): CallSlot[] {
  const call = (form.invoke_call || '').trim()
  // open-oa 常无 query_params_field，按 invoke_call 回落预设
  if (!form.query_params_field?.trim() && call === 'page_list') {
    return slotsFromPresetId('bag_page_limit')
  }
  if (!form.query_params_field?.trim() && call === 'one_by_params' && !form.injectOa) {
    return slotsFromPresetId('bag_only')
  }
  if (!form.query_params_field?.trim() && call === 'named_args' && form.injectOa) {
    return slotsFromPresetId('identity_bag')
  }

  const slots: CallSlot[] = []
  const idName = (form.identityParamName || 'oa').trim() || 'oa'
  const bag = (form.query_params_field || '').trim()
  const top = (form.topLevelFields || '').split(/[,，\s]+/).map((s) => s.trim()).filter(Boolean)

  // 身份在袋内 → 预览 method($params)，inject 仍由 form.injectOa 表达
  if (form.injectOa && form.identityPlacement === 'independent') {
    slots.push({ role: 'identity', name: idName })
    if (bag) slots.push({ role: 'bag', name: bag })
  } else if (bag) {
    slots.push({ role: 'bag', name: bag })
  } else if (form.injectOa) {
    slots.push({ role: 'identity', name: idName })
  }

  for (const n of top) {
    if (slots.some((s) => s.name === n)) continue
    slots.push({ role: 'scalar', name: n })
  }
  if (!slots.length) return slotsFromPresetId('bag_only')
  return slots
}

/**
 * 槽位写回 ToolForm 的身份/打包字段。
 * - 有 identity 且其后有 bag、且 infer 为 named_args 且身份独立 → independent + bag 字段名
 * - 仅 bag → 不注入或仅 token；query_params_field=袋名
 * - identity 在 bag 场景（one_by_params 且 inject）：placement=bag
 */
export function applySlotsToToolForm(form: ToolForm, slots: CallSlot[]): void {
  const identity = slots.find((s) => s.role === 'identity')
  const bags = slots.filter((s) => s.role === 'bag')
  const scalars = slots.filter((s) => s.role === 'scalar')
  const call = inferInvokeCall(slots)

  form.injectOa = !!identity
  form.identityParamName = identity ? (identity.name.trim() || 'oa') : 'oa'
  form.topLevelFields = scalars.map((s) => s.name.trim()).filter(Boolean).join(', ')

  if (call === 'one_by_params' || call === 'page_list') {
    // 单袋：身份若存在，默认写入袋内
    form.identityPlacement = (identity ? 'bag' : 'independent') as IdentityPlacement
    form.query_params_field = bags[0]?.name.trim() || (call === 'one_by_params' ? 'params' : 'params')
    if (!identity) form.identityPlacement = 'independent'
    if (identity && call === 'one_by_params') form.identityPlacement = 'bag'
  } else if (identity && bags.length) {
    // named_args：身份独立形参 + 另有袋
    form.identityPlacement = 'independent'
    form.query_params_field = bags[0].name.trim()
  } else if (identity && !bags.length) {
    form.identityPlacement = 'independent'
    form.query_params_field = ''
  } else if (bags.length) {
    form.identityPlacement = 'independent'
    form.query_params_field = bags[0].name.trim()
  } else {
    form.query_params_field = ''
  }
}
