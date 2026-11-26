import { describe, expect, it } from 'vitest'
import {
  applyParamRows, emptyToolForm, paramRowsFromForm, skillPayload,
  toolFormFromSchema, toolPayload,
} from './catalogForm'

describe('catalogForm', () => {
  it('builds tool payload and round-trips from schema', () => {
    const form = emptyToolForm()
    form.name = 'query_my_leave_list'
    form.summary = '请假'
    form.path = '/hr/leave/index'
    form.identityParams = 'user_id'
    form.topLevelFields = 'limit'
    form.modelParams = {
      status: {
        type: 'integer', label: '状态', enum: [1], enum_labels: { '1': '年假' }, default: 1,
      },
      limit: { type: 'integer', maximum: 20 },
      ' ': { type: 'string' },
    }
    form.fields = [
      { key: 'id', label: '单号', inList: true },
      { key: 'days', label: '', inList: false },
    ]
    const payload = toolPayload(form) as any
    expect(payload.method).toBe('GET')
    expect(payload.inject_identity_fields).toEqual(['oa'])
    expect(payload.identity_bindings).toEqual([{ param: 'oa', from: 'identity.oa' }])
    expect(payload.identity_params).toEqual({ user_id: 'oa' })
    expect(payload.top_level_fields).toEqual(['limit'])
    expect(payload.model_params.status.type).toBe('integer')
    expect(payload.model_params.status.label).toBe('状态')
    expect(payload.model_params.status.placement).toBe('bag')
    expect(payload.model_params.limit.placement).toBe('query')
    expect(Object.keys(payload.model_params)).toEqual(['status', 'limit'])
    expect(payload.result).toEqual({ kind: 'list', fields: ['id', 'days'], labels: { id: '单号' }, list_columns: ['id'] })
    expect('schema' in payload.result).toBe(false)

    const back = toolFormFromSchema({ ...payload, timeout_seconds: 10 })
    expect(toolPayload(back)).toEqual(payload)
  })

  it('injects custom identity key into bag via bindings', () => {
    const form = emptyToolForm()
    form.name = 't'
    form.summary = 's'
    form.path = '/x'
    form.injectOa = true
    form.identityParamName = 'user_id'
    form.identityPlacement = 'bag'
    form.query_params_field = 'queryParams'
    const payload = toolPayload(form) as any
    expect(payload.inject_identity_fields).toEqual([])
    expect(payload.identity_bindings).toEqual([{ param: 'user_id', from: 'identity.oa' }])
    expect(payload.identity_params).toEqual({})
    expect(payload.query_params_field).toBe('queryParams')
    const back = toolFormFromSchema(payload)
    expect(back.injectOa).toBe(true)
    expect(back.identityParamName).toBe('user_id')
    expect(back.identityPlacement).toBe('bag')
    expect(toolPayload(back)).toEqual(payload)
  })

  it('places identity as independent query param', () => {
    const form = emptyToolForm()
    form.name = 't'
    form.summary = 's'
    form.path = '/x'
    form.injectOa = true
    form.identityParamName = 'user_id'
    form.identityPlacement = 'independent'
    form.query_params_field = ''
    const payload = toolPayload(form) as any
    expect(payload.identity_bindings).toEqual([])
    expect(payload.identity_params).toEqual({ user_id: 'oa' })
    expect(payload.query_params_field).toBeNull()
    const back = toolFormFromSchema(payload)
    expect(back.identityPlacement).toBe('independent')
    expect(back.identityParamName).toBe('user_id')
    expect(toolPayload(back)).toEqual(payload)
  })

  it('preserves array/object/file on round-trip', () => {
    const schema = {
      name: 't', summary: '', path: '/', upstream: 'open_oa',
      model_params: {
        ids: { type: 'array', items: { type: 'integer' } },
        f: { type: 'file', accept: ['.pdf'] },
        filter: { type: 'object', properties: { a: { type: 'string', required: true } } },
      },
      result: {
        kind: 'object', fields: ['id', 'user.name'], labels: { 'user.name': '名' }, list_columns: [],
      },
    }
    const form = toolFormFromSchema(schema)
    const payload = toolPayload(form) as any
    expect(payload.model_params.ids.type).toBe('array')
    expect(payload.model_params.ids.items.type).toBe('integer')
    expect(payload.model_params.f.type).toBe('file')
    expect(payload.model_params.f.accept).toEqual(['.pdf'])
    expect(payload.model_params.filter.properties.a).toEqual({ type: 'string', required: true })
    expect(payload.result.fields).toContain('user.name')
    expect(payload.result.labels['user.name']).toBe('名')
    expect('schema' in payload.result).toBe(false)
    expect(toolPayload(toolFormFromSchema(payload))).toEqual(payload)
  })

  it('omits result.schema when not declared', () => {
    const payload = toolPayload(emptyToolForm()) as any
    expect('schema' in payload.result).toBe(false)
  })

  it('syncs flat param rows with topLevel', () => {
    const form = emptyToolForm()
    form.modelParams = { limit: { type: 'integer' }, status: { type: 'integer', required: true } }
    form.topLevelFields = 'limit'
    const rows = paramRowsFromForm(form)
    expect(rows.find((r) => r.name === 'limit')?.topLevel).toBe(true)
    expect(rows.find((r) => r.name === 'status')?.required).toBe(true)
    rows.push({
      name: 'page', type: 'integer', required: false, label: '页码', description: '',
      topLevel: true, placement: 'query', encoding: 'auto',
    })
    applyParamRows(form, rows)
    expect(Object.keys(form.modelParams).sort()).toEqual(['limit', 'page', 'status'])
    expect(form.topLevelFields.split(/,\s*/).sort()).toEqual(['limit', 'page'])
  })

  it('defaults upstream to open_oa and keeps a chosen one', () => {
    expect(toolFormFromSchema({ name: 'x', result: {} }).upstream).toBe('open_oa')
    expect(toolFormFromSchema({ name: 'x', upstream: 'office', result: {} }).upstream).toBe('open_oa')
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
