import { describe, expect, it } from 'vitest'
import {
  buildWirePreview, encodeFlatValue, encodeParamValue, recommendEncoding, resolveEncoding,
} from './paramWire'

describe('paramWire', () => {
  it('recommends encoding by type', () => {
    expect(recommendEncoding({ type: 'string' })).toBe('flat')
    expect(recommendEncoding({ type: 'boolean' })).toBe('flat')
    expect(recommendEncoding({ type: 'array', items: { type: 'integer' } })).toBe('repeat')
    expect(recommendEncoding({ type: 'object', properties: {} })).toBe('json')
    expect(recommendEncoding({ type: 'array', items: { type: 'object' } })).toBe('json')
  })

  it('encodes boolean as 0/1 for flat', () => {
    expect(encodeFlatValue(true)).toBe('1')
    expect(encodeFlatValue(false)).toBe('0')
    expect(encodeParamValue('ok', true, 'flat', { jsonBody: false })).toEqual({ ok: '1' })
  })

  it('encodes array as repeat keys', () => {
    expect(encodeParamValue('ids', [1, 2], 'repeat', { jsonBody: false })).toEqual({ 'ids[]': [1, 2] })
  })

  it('keeps native types in json body', () => {
    expect(encodeParamValue('n', 3, 'flat', { jsonBody: true })).toEqual({ n: 3 })
    expect(encodeParamValue('flag', true, 'flat', { jsonBody: true })).toEqual({ flag: true })
  })

  it('downgrades repeat to json when content-type is json body', () => {
    expect(resolveEncoding(
      { type: 'array', items: { type: 'integer' } },
      'repeat',
      'application/json',
      'body',
    )).toBe('json')
  })

  it('builds GET preview with bag and repeat', () => {
    const preview = buildWirePreview({
      isExport: false,
      method: 'GET',
      contentType: null,
      bagField: 'queryParams',
      identityParamName: 'oa',
      injectOa: true,
      identityPlacement: 'bag',
      modelParams: {
        limit: { type: 'integer', placement: 'query' },
        ids: { type: 'array', items: { type: 'integer' }, placement: 'query', encoding: 'auto' },
        status: { type: 'integer', placement: 'bag' },
      },
      topLevelFields: ['limit', 'ids'],
      values: { limit: 10, ids: [1, 2], status: 1 },
      previewOa: 'zhangsan',
    })
    expect(preview.query.limit).toBe('10')
    expect(preview.query['ids[]']).toEqual([1, 2])
    expect(JSON.parse(String(preview.query.queryParams))).toEqual({ status: 1, oa: 'zhangsan' })
  })

  it('builds export args with native types', () => {
    const preview = buildWirePreview({
      isExport: true,
      method: 'POST',
      contentType: null,
      bagField: 'params',
      identityParamName: 'oa',
      injectOa: true,
      identityPlacement: 'bag',
      modelParams: {
        flag: { type: 'boolean', placement: 'bag' },
        page: { type: 'integer', placement: 'scalar' },
      },
      topLevelFields: ['page'],
      values: { flag: true, page: 2 },
    })
    expect(preview.exportArgs).toEqual({
      page: 2,
      params: { flag: true, oa: '<oa>' },
    })
  })
})
