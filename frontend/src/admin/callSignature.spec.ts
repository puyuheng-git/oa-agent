import { describe, expect, it } from 'vitest'
import {
  applySlotsToToolForm,
  CALL_PRESETS,
  findPresetId,
  inferInvokeCall,
  previewCall,
  slotsFromDescribe,
  slotsFromPresetId,
  slotsFromToolForm,
} from './callSignature'
import { emptyToolForm } from './catalogForm'

describe('callSignature', () => {
  it('previews all locked signatures', () => {
    expect(previewCall('method1', [{ role: 'identity', name: 'oa' }])).toBe('method1($oa)')
    expect(previewCall('method2', [
      { role: 'identity', name: 'oa' },
      { role: 'bag', name: 'params' },
    ])).toBe('method2($oa, $params)')
    expect(previewCall('method3', [{ role: 'bag', name: 'params' }])).toBe('method3($params)')
    expect(previewCall('method4', [
      { role: 'bag', name: 'params' },
      { role: 'bag', name: 'data' },
    ])).toBe('method4($params, $data)')
    expect(previewCall('method4', [
      { role: 'bag', name: 'params' },
      { role: 'bag', name: 'data' },
      { role: 'bag', name: 'extra' },
    ])).toBe('method4($params, $data, $extra)')
    expect(previewCall('method5', [
      { role: 'bag', name: 'params' },
      { role: 'scalar', name: 'page' },
      { role: 'scalar', name: 'limit' },
    ])).toBe('method5($params, $page, $limit)')
  })

  it('infers invoke_call from presets', () => {
    expect(inferInvokeCall(slotsFromPresetId('identity_only'))).toBe('named_args')
    expect(inferInvokeCall(slotsFromPresetId('identity_bag'))).toBe('named_args')
    expect(inferInvokeCall(slotsFromPresetId('bag_only'))).toBe('one_by_params')
    expect(inferInvokeCall(slotsFromPresetId('two_bags'))).toBe('named_args')
    expect(inferInvokeCall(slotsFromPresetId('three_bags'))).toBe('named_args')
    expect(inferInvokeCall(slotsFromPresetId('bag_page_limit'))).toBe('page_list')
  })

  it('finds preset id', () => {
    for (const p of CALL_PRESETS) {
      expect(findPresetId(p.slots)).toBe(p.id)
    }
  })

  it('builds slots from describe', () => {
    const slots = slotsFromDescribe(
      [
        { name: 'oa', kind: 'identity' },
        { name: 'params', type: 'array' },
      ],
      'named_args',
    )
    expect(previewCall('foo', slots)).toBe('foo($oa, $params)')
    expect(inferInvokeCall(slots)).toBe('named_args')
  })

  it('syncs slots with ToolForm', () => {
    const form = emptyToolForm()
    applySlotsToToolForm(form, slotsFromPresetId('identity_bag'))
    expect(form.injectOa).toBe(true)
    expect(form.identityPlacement).toBe('independent')
    expect(form.identityParamName).toBe('oa')
    expect(form.query_params_field).toBe('params')
    expect(inferInvokeCall(slotsFromToolForm(form))).toBe('named_args')

    applySlotsToToolForm(form, slotsFromPresetId('bag_only'))
    expect(form.query_params_field).toBe('params')
    // bag_only 无 identity 槽 → 关闭注入
    expect(form.injectOa).toBe(false)
    expect(inferInvokeCall(slotsFromToolForm(form))).toBe('one_by_params')

    applySlotsToToolForm(form, slotsFromPresetId('bag_page_limit'))
    expect(form.topLevelFields.split(/,\s*/).sort()).toEqual(['limit', 'page'])
    expect(inferInvokeCall(slotsFromToolForm(form))).toBe('page_list')
  })
})
