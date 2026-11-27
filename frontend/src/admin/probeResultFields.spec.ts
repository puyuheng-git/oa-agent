import { describe, expect, it } from 'vitest'
import { fieldsFromRow, mergeProbeResultFields } from './probeResultFields'

describe('probeResultFields', () => {
  it('takes top-level and multi-level dot paths', () => {
    expect(fieldsFromRow({ id: 1, user: { name: 'a', dept: { t: 1 } }, items: [] }).map((r) => r.field))
      .toEqual(['id', 'user', 'user.name', 'user.dept', 'user.dept.t', 'items'])
  })

  it('merges without overwriting labels', () => {
    const merged = mergeProbeResultFields(
      { list: [{ id: 1, title: 'x' }], total: 1 },
      [{ field: 'id', label: '单号' }],
      'object',
    )
    expect(merged.find((r) => r.field === 'id')?.label).toBe('单号')
    expect(merged.some((r) => r.field === 'title')).toBe(true)
  })
})
