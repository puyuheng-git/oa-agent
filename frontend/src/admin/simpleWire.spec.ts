import { describe, expect, it } from 'vitest'
import { emptyToolForm, toolPayload } from './catalogForm'
import type { SchemaNode } from './schemaTree'
import {
  ensureSimpleWireDefaults,
  formatMissingRequiredMessage,
  isLikelyBagParamName,
  missingRequiredParamNames,
} from './simpleWire'

describe('simpleWire', () => {
  it('recognizes bag param names', () => {
    expect(isLikelyBagParamName('params')).toBe(true)
    expect(isLikelyBagParamName('field')).toBe(false)
    expect(isLikelyBagParamName('userId')).toBe(false)
  })

  it('fills HTTP placement defaults and keeps inject on', () => {
    const form = emptyToolForm()
    form.injectOa = false
    form.identityParamName = ''
    form.query_params_field = ''
    form.identityPlacement = 'independent'
    form.method = 'GET'
    form.modelParams = {
      keyword: { type: 'string', required: true },
    }
    ensureSimpleWireDefaults(form, 'simple')
    expect(form.injectOa).toBe(true)
    expect(form.identityParamName).toBe('oa')
    expect(form.modelParams.keyword.placement).toBe('query')
    const payload = toolPayload(form) as { model_params: Record<string, { placement?: string }> }
    expect(payload.model_params.keyword.placement).toBe('query')
  })

  it('expert mode does not force injectOa back on', () => {
    const form = emptyToolForm()
    form.injectOa = false
    form.query_params_field = ''
    form.identityPlacement = 'independent'
    form.modelParams = { q: { type: 'string' } }
    ensureSimpleWireDefaults(form, 'expert')
    expect(form.injectOa).toBe(false)
    expect(form.modelParams.q.placement).toBe('query')
  })

  it('fills Export named_args scalar placement', () => {
    const form = emptyToolForm()
    form.invoke_service = 'oa/hr'
    form.invoke_method = 'getStaffInfoByUserID'
    form.invoke_call = 'named_args'
    form.query_params_field = ''
    form.identityPlacement = 'independent'
    form.modelParams = {
      userId: { type: 'string', required: true },
      field: { type: 'array', items: { type: 'string' }, default: ['*'] },
    }
    ensureSimpleWireDefaults(form)
    expect(form.modelParams.userId.placement).toBe('scalar')
    expect(form.modelParams.field.placement).toBe('scalar')
  })

  it('reports missing required without default', () => {
    const params: Record<string, SchemaNode> = {
      userId: { type: 'string', required: true },
      field: { type: 'array', items: { type: 'string' }, default: ['*'], required: false },
    }
    expect(missingRequiredParamNames(params, {})).toEqual(['userId'])
    expect(missingRequiredParamNames(params, { userId: '37047' })).toEqual([])
    expect(formatMissingRequiredMessage(['userId', 'field'])).toBe('还缺少必填参数：userId、field')
  })
})
