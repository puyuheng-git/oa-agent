import { describe, expect, it } from 'vitest'
import {
  emptyNode,
  enumToText,
  parseEnumText,
  fileMultipleToArray,
  normalizeNode,
  parseSchemaJson,
  stringifySchema,
  SCHEMA_MAX_DEPTH,
  type SchemaNode,
} from './schemaTree'

describe('schemaTree', () => {
  it('normalizes nested object', () => {
    const n = normalizeNode({
      type: 'object',
      properties: { a: { type: 'array', items: { type: 'integer' } } },
    })
    expect(n.properties!.a.items!.type).toBe('integer')
  })

  it('file multiple → array of file', () => {
    const n = fileMultipleToArray({ type: 'file', multiple: true, accept: ['.pdf'] } as any)
    expect(n).toEqual({ type: 'array', items: { type: 'file', accept: ['.pdf'] } })
  })

  it('rejects bad json', () => {
    const r = parseSchemaJson('{')
    expect(r.ok).toBe(false)
  })

  it('invalid type falls back to string', () => {
    expect(normalizeNode({ type: 'weird' }).type).toBe('string')
    expect(normalizeNode(null).type).toBe('string')
  })

  it('array without items defaults to string items', () => {
    expect(normalizeNode({ type: 'array' }).items).toEqual({ type: 'string' })
  })

  it('normalizeNode converts file+multiple and keeps label/required', () => {
    const n = normalizeNode({ type: 'file', multiple: true, accept: ['.pdf'], label: '附件', required: true })
    expect(n).toEqual({
      type: 'array',
      label: '附件',
      required: true,
      items: { type: 'file', accept: ['.pdf'] },
    })
  })

  it('stops descending beyond max depth', () => {
    let raw: any = { type: 'string' }
    for (let i = 0; i < SCHEMA_MAX_DEPTH + 3; i++) raw = { type: 'object', properties: { c: raw } }
    let n: SchemaNode | undefined = normalizeNode(raw)
    let depth = 0
    while (n?.properties?.c) {
      n = n.properties.c
      depth++
    }
    expect(depth).toBeLessThanOrEqual(SCHEMA_MAX_DEPTH + 1)
  })

  it('parse + stringify roundtrip', () => {
    const r = parseSchemaJson('{"a":{"type":"integer","label":"数量"}}')
    expect(r.ok).toBe(true)
    if (r.ok) {
      expect(r.value.a.type).toBe('integer')
      expect(parseSchemaJson(stringifySchema(r.value))).toEqual(r)
    }
  })

  it('parse rejects non-object root', () => {
    expect(parseSchemaJson('[]').ok).toBe(false)
    expect(parseSchemaJson('1').ok).toBe(false)
  })

  it('emptyNode', () => {
    expect(emptyNode().type).toBe('string')
    expect(emptyNode('array').items).toEqual({ type: 'string' })
    expect(emptyNode('object').properties).toEqual({})
  })

  it('parses enum lines with value=label and round-trips', () => {
    const r = parseEnumText('0=未报销\n1=已报销', 'integer')
    expect(r).toEqual({ enum: [0, 1], enum_labels: { '0': '未报销', '1': '已报销' } })
    expect(enumToText(r)).toBe('0=未报销\n1=已报销')
    expect(parseEnumText('a；b', 'string')).toEqual({ enum: ['a', 'b'] })
    expect(parseEnumText('x\n1', 'integer')).toEqual({ enum: [1] })
    expect(parseEnumText('', 'string')).toEqual({})
  })
})
