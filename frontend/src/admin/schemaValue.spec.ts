import { describe, expect, it } from 'vitest'
import { buildArgsFromValues, emptyValue, mergeValuesOnSchemaChange } from './schemaValue'
import type { SchemaNode } from './schemaTree'

describe('buildArgsFromValues', () => {
  it('builds array and nested object args', () => {
    const args = buildArgsFromValues(
      {
        ids: { type: 'array', items: { type: 'integer' } },
        payload: { type: 'object', properties: { n: { type: 'string' } } },
      },
      { ids: ['1', '2'], payload: { n: 'x' } },
    )
    expect(args).toEqual({ ids: [1, 2], payload: { n: 'x' } })
  })

  it('coerces scalars and drops empty / invalid values', () => {
    const params: Record<string, SchemaNode> = {
      s: { type: 'string' },
      i: { type: 'integer' },
      f: { type: 'number' },
      b: { type: 'boolean' },
      bad: { type: 'integer' },
      blank: { type: 'string' },
      none: { type: 'string' },
    }
    const args = buildArgsFromValues(params, { s: 'a', i: '3', f: '1.5', b: false, bad: '1.5', blank: '', extra: 1 })
    expect(args).toEqual({ s: 'a', i: 3, f: 1.5, b: false })
  })

  it('keeps boolean false but drops unset boolean', () => {
    const params: Record<string, SchemaNode> = { a: { type: 'boolean' }, b: { type: 'boolean' } }
    expect(buildArgsFromValues(params, { a: false })).toEqual({ a: false })
  })

  it('keeps explicit free-form object (incl. empty {}) but omits unset one', () => {
    const params: Record<string, SchemaNode> = { ext: { type: 'object' }, ext2: { type: 'object', properties: {} } }
    expect(buildArgsFromValues(params, { ext: {}, ext2: { k: 'v' } })).toEqual({ ext: {}, ext2: { k: 'v' } })
    expect(buildArgsFromValues(params, {})).toEqual({})
  })

  it('drops empty arrays and objects, filters empty array items', () => {
    const params: Record<string, SchemaNode> = {
      tags: { type: 'array', items: { type: 'string' } },
      none: { type: 'array', items: { type: 'string' } },
      o: { type: 'object', properties: { x: { type: 'string' } } },
    }
    const args = buildArgsFromValues(params, { tags: ['a', '', 'b'], none: [''], o: { x: '' } })
    expect(args).toEqual({ tags: ['a', 'b'] })
  })

  it('maps file values (ref string) and arrays of file', () => {
    const params: Record<string, SchemaNode> = {
      doc: { type: 'file' },
      docs: { type: 'array', items: { type: 'file' } },
    }
    const args = buildArgsFromValues(params, { doc: '/tmp/a.pdf', docs: ['/tmp/1.pdf', ' /tmp/2.pdf '] })
    expect(args).toEqual({ doc: '/tmp/a.pdf', docs: ['/tmp/1.pdf', '/tmp/2.pdf'] })
  })

  it('handles array of objects', () => {
    const params: Record<string, SchemaNode> = {
      rows: { type: 'array', items: { type: 'object', properties: { id: { type: 'integer' }, name: { type: 'string' } } } },
    }
    const args = buildArgsFromValues(params, { rows: [{ id: '1', name: 'a' }, { id: '', name: '' }, { id: '2' }] })
    expect(args).toEqual({ rows: [{ id: 1, name: 'a' }, { id: 2 }] })
  })
})

describe('emptyValue', () => {
  it('returns type-appropriate blanks', () => {
    expect(emptyValue({ type: 'string' })).toBe('')
    expect(emptyValue({ type: 'integer' })).toBe('')
    expect(emptyValue({ type: 'boolean' })).toBeUndefined()
    expect(emptyValue({ type: 'array', items: { type: 'string' } })).toEqual([])
    expect(emptyValue({ type: 'object', properties: { a: { type: 'string' } } })).toEqual({})
    expect(emptyValue({ type: 'file' })).toBe('')
  })

  it('uses default when present (cloned)', () => {
    const d = { a: 1 }
    const v = emptyValue({ type: 'object', default: d }) as Record<string, unknown>
    expect(v).toEqual({ a: 1 })
    expect(v).not.toBe(d)
    expect(emptyValue({ type: 'string', default: 'x' })).toBe('x')
  })
})

describe('mergeValuesOnSchemaChange', () => {
  it('keeps values whose key and type are unchanged, drops the rest', () => {
    const oldS: Record<string, SchemaNode> = { a: { type: 'string' }, b: { type: 'string' }, c: { type: 'string' } }
    const newS: Record<string, SchemaNode> = { a: { type: 'string' }, b: { type: 'integer' } }
    expect(mergeValuesOnSchemaChange(oldS, newS, { a: 'x', b: '2', c: 'z' })).toEqual({ a: 'x' })
  })

  it('fills defaults for new keys and type-changed keys', () => {
    const oldS: Record<string, SchemaNode> = { a: { type: 'string' } }
    const newS: Record<string, SchemaNode> = { a: { type: 'integer', default: 5 }, n: { type: 'string', default: 'd' } }
    expect(mergeValuesOnSchemaChange(oldS, newS, { a: 'x' })).toEqual({ a: 5, n: 'd' })
  })

  it('merges nested objects recursively', () => {
    const oldS: Record<string, SchemaNode> = {
      p: { type: 'object', properties: { x: { type: 'string' }, y: { type: 'string' } } },
    }
    const newS: Record<string, SchemaNode> = {
      p: { type: 'object', properties: { x: { type: 'string' }, z: { type: 'string' } } },
    }
    expect(mergeValuesOnSchemaChange(oldS, newS, { p: { x: '1', y: '2' } })).toEqual({ p: { x: '1' } })
  })

  it('keeps array when items type unchanged and merges element objects', () => {
    const oldS: Record<string, SchemaNode> = {
      rows: { type: 'array', items: { type: 'object', properties: { a: { type: 'string' }, b: { type: 'string' } } } },
      ids: { type: 'array', items: { type: 'integer' } },
    }
    const newS: Record<string, SchemaNode> = {
      rows: { type: 'array', items: { type: 'object', properties: { a: { type: 'string' } } } },
      ids: { type: 'array', items: { type: 'string' } },
    }
    const out = mergeValuesOnSchemaChange(oldS, newS, { rows: [{ a: '1', b: '2' }], ids: ['1'] })
    expect(out).toEqual({ rows: [{ a: '1' }] })
  })
})
