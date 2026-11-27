// 参数放置 / 编码：与后端 executor/param_wire.py 对齐（表格 UI + 请求预览）。

import type { SchemaNode, SchemaType } from './schemaTree'

export type ParamPlacement = 'scalar' | 'bag' | 'query' | 'body'
export type ParamEncoding = 'auto' | 'flat' | 'repeat' | 'json'
export type HttpContentType =
  | 'application/x-www-form-urlencoded'
  | 'application/json'

export const PLACEMENTS_EXPORT: ParamPlacement[] = ['scalar', 'bag']
export const PLACEMENTS_HTTP: ParamPlacement[] = ['query', 'body', 'bag']
export const ENCODINGS: ParamEncoding[] = ['auto', 'flat', 'repeat', 'json']

const SCALAR_TYPES: SchemaType[] = ['string', 'integer', 'number', 'boolean', 'file']

export function isExportTarget(invokeService: string, invokeMethod: string): boolean {
  return !!(invokeService.trim() && invokeMethod.trim())
}

/** 按类型推荐编码（auto 解析结果）。 */
export function recommendEncoding(node: SchemaNode): Exclude<ParamEncoding, 'auto'> {
  const t = node.type || 'string'
  if (t === 'object') return 'json'
  if (t === 'array') {
    const itemType = node.items?.type || 'string'
    if (SCALAR_TYPES.includes(itemType) && itemType !== 'file') return 'repeat'
    return 'json'
  }
  return 'flat'
}

export function resolveEncoding(
  node: SchemaNode,
  encoding: ParamEncoding | undefined,
  contentType: string | null | undefined,
  placement: ParamPlacement,
): Exclude<ParamEncoding, 'auto'> {
  const raw = (encoding || 'auto') as ParamEncoding
  if (raw !== 'auto') {
    // JSON body 内忽略仅对 form 有意义的 repeat
    if (contentType === 'application/json' && placement === 'body' && raw === 'repeat') {
      return 'json'
    }
    return raw
  }
  if (contentType === 'application/json' && placement === 'body') {
    return recommendEncoding(node) === 'repeat' ? 'flat' : recommendEncoding(node)
  }
  return recommendEncoding(node)
}

/** 旧数据 / 缺省 placement 推导。 */
export function inferPlacement(
  name: string,
  node: SchemaNode,
  opts: {
    isExport: boolean
    method: string
    topLevel: Set<string>
    hasBag: boolean
  },
): ParamPlacement {
  const explicit = (node as SchemaNode & { placement?: string }).placement
  if (explicit === 'scalar' || explicit === 'bag' || explicit === 'query' || explicit === 'body') {
    if (opts.isExport) return explicit === 'bag' ? 'bag' : 'scalar'
    if (explicit === 'scalar') return 'query'
    return explicit
  }
  if (opts.topLevel.has(name)) {
    return opts.isExport ? 'scalar' : 'query'
  }
  if (opts.hasBag) return 'bag'
  // Export 无袋时默认独立形参（named_args）；勿一律当成袋
  if (opts.isExport) return 'scalar'
  return (opts.method || 'GET').toUpperCase() === 'POST' ? 'body' : 'query'
}

/** 布尔 → PHP 友好 0/1；其余标量转字符串。 */
export function encodeFlatValue(value: unknown): string {
  if (typeof value === 'boolean') return value ? '1' : '0'
  if (value === null || value === undefined) return ''
  return String(value)
}

/**
 * 把对象/数组展成 PHP 多维表单键：a[b]=1、a[]=1。
 * OA $_GET/$_POST 可直接还原成多维数组，无需 json_decode。
 */
export function flattenPhpForm(prefix: string, value: unknown): Record<string, unknown> {
  if (value !== null && typeof value === 'object' && !Array.isArray(value)) {
    const out: Record<string, unknown> = {}
    for (const [k, v] of Object.entries(value as Record<string, unknown>)) {
      if (v === undefined || v === null || v === '') continue
      Object.assign(out, flattenPhpForm(`${prefix}[${k}]`, v))
    }
    return out
  }
  if (Array.isArray(value)) {
    const out: Record<string, unknown> = {}
    const scalars: unknown[] = []
    value.forEach((v, i) => {
      if (v === undefined || v === null || v === '') return
      if (v !== null && typeof v === 'object') {
        Object.assign(out, flattenPhpForm(`${prefix}[${i}]`, v))
      } else {
        scalars.push(encodeFlatValue(v))
      }
    })
    if (scalars.length) out[`${prefix}[]`] = scalars
    return out
  }
  return { [prefix]: encodeFlatValue(value) }
}

/**
 * 将单个参数编成 wire 片段。
 * - flat: { name: "v" }
 * - repeat: { "name[]": ["a","b"] }
 * - json: form 下为多维数组 name[key]=；JSON body 下为原生对象
 */
export function encodeParamValue(
  name: string,
  value: unknown,
  encoding: Exclude<ParamEncoding, 'auto'>,
  opts: { jsonBody: boolean },
): Record<string, unknown> {
  const jsonBody = opts.jsonBody
  if (jsonBody && encoding !== 'json') {
    // JSON body：保真类型；repeat 已在 resolve 时降级
    return { [name]: value }
  }
  if (encoding === 'json') {
    if (jsonBody) return { [name]: value }
    return flattenPhpForm(name, value)
  }
  if (encoding === 'repeat') {
    const list = Array.isArray(value) ? value : [value]
    return { [`${name}[]`]: list.map((v) => (typeof v === 'boolean' ? (v ? '1' : '0') : v)) }
  }
  // flat
  if (Array.isArray(value)) {
    return { [name]: value.map(encodeFlatValue).join(',') }
  }
  if (value !== null && typeof value === 'object') {
    return flattenPhpForm(name, value)
  }
  return { [name]: encodeFlatValue(value) }
}

export interface WirePreview {
  method: string
  contentType: string | null
  query: Record<string, unknown>
  body: Record<string, unknown> | null
  /** Export：原生 args（类型保真） */
  exportArgs: Record<string, unknown> | null
  note: string
}

/** 根据 modelParams + 测试值生成请求预览（测调前可见）。 */
export function buildWirePreview(opts: {
  isExport: boolean
  method: string
  contentType: string | null
  bagField: string
  identityParamName: string
  injectOa: boolean
  identityPlacement: 'independent' | 'bag'
  modelParams: Record<string, SchemaNode>
  topLevelFields: string[]
  values: Record<string, unknown>
  /** 预览用假身份 */
  previewOa?: string
}): WirePreview {
  const method = (opts.method || 'GET').toUpperCase()
  const hasBag = !!opts.bagField.trim()
  const top = new Set(opts.topLevelFields)
  const previewOa = opts.previewOa || '<oa>'

  if (opts.isExport) {
    const args: Record<string, unknown> = { ...opts.values }
    const bag: Record<string, unknown> = {}
    const out: Record<string, unknown> = {}
    for (const [name, node] of Object.entries(opts.modelParams)) {
      const placement = inferPlacement(name, node, {
        isExport: true, method: 'POST', topLevel: top, hasBag,
      })
      if (!(name in args) && args[name] !== 0 && args[name] !== false) continue
      const val = args[name]
      if (val === undefined || val === null || val === '') continue
      if (placement === 'bag' && hasBag) bag[name] = val
      else out[name] = val
    }
    if (opts.injectOa) {
      const key = opts.identityParamName || 'oa'
      if (opts.identityPlacement === 'bag' && hasBag) bag[key] = previewOa
      else out[key] = previewOa
    }
    if (hasBag && Object.keys(bag).length) out[opts.bagField.trim()] = bag
    return {
      method: 'POST',
      contentType: 'application/json',
      query: {},
      body: null,
      exportArgs: out,
      note: 'ANew Export：JSON 传参，类型保真',
    }
  }

  const contentType =
    method === 'POST'
      ? (opts.contentType || 'application/x-www-form-urlencoded')
      : null
  const jsonBody = contentType === 'application/json'
  const query: Record<string, unknown> = {}
  const body: Record<string, unknown> = {}
  const bagObj: Record<string, unknown> = {}

  for (const [name, node] of Object.entries(opts.modelParams)) {
    const placement = inferPlacement(name, node, {
      isExport: false, method, topLevel: top, hasBag,
    })
    const val = opts.values[name]
    if (val === undefined || val === null || val === '') continue
    // POST form：全部进 body（$_POST）；POST JSON：仅显式 query 留 query
    let targetPlacement: ParamPlacement
    if (method === 'POST') {
      const explicit = (node as SchemaNode & { placement?: string }).placement
      if (placement === 'bag') targetPlacement = 'bag'
      else if (jsonBody && explicit === 'query') targetPlacement = 'query'
      else targetPlacement = 'body'
    } else {
      targetPlacement = placement === 'body' ? 'query' : placement
    }
    const enc = resolveEncoding(
      node,
      (node as SchemaNode & { encoding?: ParamEncoding }).encoding,
      contentType,
      targetPlacement === 'bag' ? 'bag' : targetPlacement,
    )
    const encoded = encodeParamValue(name, val, enc, { jsonBody: jsonBody && targetPlacement === 'body' })

    if (targetPlacement === 'bag' && hasBag) {
      bagObj[name] = val
    } else if (targetPlacement === 'body' && method === 'POST') {
      Object.assign(body, encoded)
    } else {
      Object.assign(query, encoded)
    }
  }

  if (opts.injectOa) {
    const key = opts.identityParamName || 'oa'
    if (opts.identityPlacement === 'bag' && hasBag) bagObj[key] = previewOa
    else if (method === 'POST') {
      // POST 独立身份进 body（$_POST）
      body[key] = previewOa
    } else {
      query[key] = previewOa
    }
  }

  if (hasBag && Object.keys(bagObj).length) {
    const bagName = opts.bagField.trim()
    if (jsonBody && method === 'POST') {
      body[bagName] = bagObj
    } else {
      // form/query：queryParams[status]=1，不用 JSON 字符串
      const flat = flattenPhpForm(bagName, bagObj)
      if (method === 'POST') Object.assign(body, flat)
      else Object.assign(query, flat)
    }
  }

  return {
    method,
    contentType,
    query,
    body: method === 'POST' ? body : null,
    exportArgs: null,
    note: method === 'GET'
      ? 'GET：参数在 query；袋/对象用 name[key]= 多维数组；中文默认 GBK'
      : jsonBody
        ? 'POST JSON：body 类型保真（UTF-8）'
        : 'POST form：参数在 $_POST；袋/对象用 name[key]= 多维数组；中文默认 GBK',
  }
}

export function formatWirePreview(preview: WirePreview): string {
  if (preview.exportArgs) {
    return JSON.stringify({ call: 'export', args: preview.exportArgs }, null, 2)
  }
  const out: Record<string, unknown> = {
    method: preview.method,
    content_type: preview.contentType,
    query: preview.query,
  }
  if (preview.body) out.body = preview.body
  return JSON.stringify(out, null, 2)
}
