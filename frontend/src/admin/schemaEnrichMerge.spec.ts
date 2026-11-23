import { describe, expect, it } from 'vitest'
import { emptyToolForm } from './catalogForm'
import { mergeEnrichSuggestion } from './schemaEnrichMerge'

describe('mergeEnrichSuggestion', () => {
  it('fills empty name/summary and merges fields', () => {
    const form = emptyToolForm()
    form.name = ''
    form.summary = ''
    form.fields = [{ key: 'id', label: '编号', inList: true }]
    form.modelParams = {
      status: { type: 'integer', label: '', description: '' },
    }
    const stats = mergeEnrichSuggestion(form, {
      name: 'query_demo',
      summary: '演示',
      description: '查演示数据',
      result_kind: 'list',
      fields: [
        { field: 'id', label: 'ID' },
        { field: 'name', label: '名称' },
      ],
      list_columns: ['id', 'name'],
      params: { status: { label: '状态', description: '筛选状态' } },
    })
    expect(form.name).toBe('query_demo')
    expect(form.summary).toBe('演示')
    expect(form.description).toBe('查演示数据')
    expect(form.fields.map((f) => f.key)).toEqual(['id', 'name'])
    expect(form.fields[0].label).toBe('编号') // 已有非空保留
    expect(form.fields[1].label).toBe('名称')
    expect(form.modelParams.status.label).toBe('状态')
    expect(stats.paramHints).toBe(1)
  })

  it('keeps non-empty name', () => {
    const form = emptyToolForm()
    form.name = 'query_keep'
    mergeEnrichSuggestion(form, { name: 'query_other', fields: [] })
    expect(form.name).toBe('query_keep')
  })
})
