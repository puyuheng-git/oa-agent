import { describe, expect, it } from 'vitest'
import { emptyParam, emptyToolForm, parseEnum, skillPayload, toolFormFromSchema, toolPayload } from './catalogForm'

describe('catalogForm', () => {
  it('parses enum text with labels and typed values', () => {
    expect(parseEnum('0=未报销, 1=已报销', 'integer')).toEqual({ enum: [0, 1], enum_labels: { '0': '未报销', '1': '已报销' } })
    expect(parseEnum('a；b', 'string')).toEqual({ enum: ['a', 'b'] })
    expect(parseEnum('', 'string')).toEqual({})
  })

  it('builds tool payload and round-trips from schema', () => {
    const form = emptyToolForm()
    form.name = 'query_my_leave_list'
    form.summary = '请假'
    form.path = '/hr/leave/index'
    form.identityParams = 'user_id'
    form.params = [
      { ...emptyParam(), name: 'status', label: '状态', type: 'integer', enumText: '1=年假', defaultValue: '1' },
      { ...emptyParam(), name: 'limit', type: 'integer', maximum: 20, topLevel: true },
      { ...emptyParam(), name: ' ' },
    ]
    form.fields = [
      { key: 'id', label: '单号', inList: true },
      { key: 'days', label: '', inList: false },
    ]
    const payload = toolPayload(form) as any
    expect(payload.method).toBe('GET')
    expect(payload.inject_identity_fields).toEqual(['oa'])
    expect(payload.identity_params).toEqual({ user_id: 'oa' })
    expect(payload.top_level_fields).toEqual(['limit'])
    expect(payload.model_params.status).toEqual({
      type: 'integer', required: false, label: '状态', enum: [1], enum_labels: { '1': '年假' }, default: 1,
    })
    expect(Object.keys(payload.model_params)).toEqual(['status', 'limit'])
    expect(payload.result).toEqual({ kind: 'list', fields: ['id', 'days'], labels: { id: '单号' }, list_columns: ['id'] })

    const back = toolFormFromSchema({ ...payload, timeout_seconds: 10 })
    expect(toolPayload(back)).toEqual(payload)
  })

  it('defaults upstream to office and keeps a chosen one', () => {
    expect(toolFormFromSchema({ name: 'x', result: {} }).upstream).toBe('office')
    expect(emptyToolForm('hr').upstream).toBe('hr')
    const form = { ...emptyToolForm(), upstream: 'hr' }
    expect(toolPayload(form).upstream).toBe('hr')
    expect(toolFormFromSchema(toolPayload(form)).upstream).toBe('hr')
  })

  it('splits skill examples by line', () => {
    expect(skillPayload({ name: 'a_b', display_name: 'X', description: 'd', instructions: '', examplesText: '一\n\n 二 ', tools: ['t'] }).examples)
      .toEqual(['一', '二'])
  })
})
