import { describe, expect, it } from 'vitest'
import { flattenBagSchema, unwrapBagArgs } from './wizardCallArgs'

describe('unwrapBagArgs', () => {
  it('flattens params bag for one_by_params', () => {
    expect(unwrapBagArgs('one_by_params', { params: { status: 1, kw: 'a' }, page: 1 })).toEqual({
      status: 1, kw: 'a', page: 1,
    })
  })

  it('keeps top-level over bag on key clash', () => {
    expect(unwrapBagArgs('page_list', { params: { limit: 99 }, limit: 5, page: 1 })).toEqual({
      limit: 5, page: 1,
    })
  })

  it('leaves named_args unchanged', () => {
    const args = { params: { a: 1 }, userId: 'x' }
    expect(unwrapBagArgs('named_args', args)).toEqual(args)
  })
})

describe('flattenBagSchema', () => {
  it('lifts bag properties to top level', () => {
    const flat = flattenBagSchema('one_by_params', {
      params: {
        type: 'object',
        properties: {
          status: { type: 'integer', label: '状态' },
        },
      },
      page: { type: 'integer', label: '页码' },
    })
    expect(flat.params).toBeUndefined()
    expect(flat.status?.type).toBe('integer')
    expect(flat.page?.type).toBe('integer')
  })

  it('infers free-object keys from values', () => {
    const flat = flattenBagSchema(
      'one_by_params',
      { params: { type: 'object' } },
      { params: { foo: 'bar', n: 1 } },
    )
    expect(flat.params).toBeUndefined()
    expect(flat.foo?.type).toBe('string')
    expect(flat.n?.type).toBe('integer')
  })

  it('keeps free object bag when no properties and no values', () => {
    const flat = flattenBagSchema('one_by_params', {
      params: { type: 'object', label: '参数' },
      page: { type: 'integer' },
    })
    expect(flat.params?.type).toBe('object')
    expect(flat.page?.type).toBe('integer')
  })

  it('converts unstructured array bag to free object instead of deleting', () => {
    const flat = flattenBagSchema('one_by_params', {
      params: { type: 'array', label: 'params' },
      page: { type: 'integer' },
    })
    expect(flat.params?.type).toBe('object')
    expect(flat.page?.type).toBe('integer')
  })

  it('keeps structured array bag as array', () => {
    const flat = flattenBagSchema('page_list', {
      data: {
        type: 'array',
        items: {
          type: 'object',
          properties: { id: { type: 'integer' } },
        },
      },
    })
    expect(flat.data?.type).toBe('array')
    expect(flat.data?.items?.properties?.id?.type).toBe('integer')
  })
})
