import { describe, expect, it } from 'vitest'
import { displayValue, groupFields, localValidate, syncTag, type FieldDef, type WorkflowSchema } from './ops'

describe('workflow field groups and bool', () => {
  const fields: FieldDef[] = [
    { key: 'a', label: 'A', kind: 'int', group: '多轮对话', min: 0, max: 30, unit: '轮' },
    { key: 'b', label: 'B', kind: 'bool', group: '基础' },
    { key: 'c', label: 'C', kind: 'text' },
  ]
  it('按服务端组顺序分组，未分组归入其他', () => {
    expect(groupFields(fields, ['基础', '多轮对话']).map((g) => [g.name, g.fields.map((f) => f.key)])).toEqual([
      ['基础', ['b']], ['多轮对话', ['a']], ['其他', ['c']],
    ])
  })
  it('开关与单位的展示和校验', () => {
    expect(displayValue(fields[1], false)).toBe('关闭')
    expect(displayValue(fields[0], 6)).toBe('6 轮')
    expect(localValidate({ b: 'yes' }, fields)).toEqual(['B必须是开或关'])
    expect(localValidate({ a: 31 }, fields)).toEqual(['A必须是 0～30 的整数'])
  })
})

const FIELDS: FieldDef[] = [
  { key: 'intent_mode', label: '意图解析方式', kind: 'enum', options: [{ value: 'auto', label: '自动' }, { value: 'rules', label: '仅规则' }] },
  { key: 'llm_model_id', label: '指定模型', kind: 'model' },
  { key: 'list_default_limit', label: '列表默认条数', kind: 'int', min: 1, max: 20 },
  { key: 'help_text', label: '帮助回复', kind: 'text', max: 10 },
]
const SCHEMA: WorkflowSchema = { fields: FIELDS, models: [{ id: 3, label: 'qwen', enabled: true }], skills: [] }

describe('ops helpers', () => {
  it('同步结果标签：未同步与未知值不编造', () => {
    expect(syncTag(null)).toEqual({ label: '未同步', type: 'info' })
    expect(syncTag('error').type).toBe('danger')
    expect(syncTag('weird')).toEqual({ label: 'weird', type: 'info' })
  })

  it('配置值可读化', () => {
    expect(displayValue(FIELDS[0], 'rules')).toBe('仅规则')
    expect(displayValue(FIELDS[1], null)).toBe('默认模型')
    expect(displayValue(FIELDS[1], 3, SCHEMA)).toBe('qwen（#3）')
    expect(displayValue(FIELDS[1], 9, SCHEMA)).toBe('#9')
    expect(displayValue(FIELDS[2], 10)).toBe('10')
    expect(displayValue(FIELDS[3], 'x'.repeat(80))).toHaveLength(61)
    expect(displayValue(undefined, '')).toBe('—')
  })

  it('本地校验只做提示', () => {
    const ok = { intent_mode: 'auto', llm_model_id: null, list_default_limit: 10, help_text: '帮助' }
    expect(localValidate(ok, FIELDS)).toEqual([])
    expect(localValidate({ ...ok, help_text: '' }, FIELDS)).toEqual([])
    const bad = { intent_mode: 'x', list_default_limit: 21, help_text: '超长'.repeat(6) }
    expect(localValidate(bad, FIELDS)).toEqual(['意图解析方式取值无效', '列表默认条数必须是 1～20 的整数', '帮助回复必须是不超过 10 字的文本'])
    expect(localValidate({ ...ok, list_default_limit: 2.5 }, FIELDS)).toHaveLength(1)
    const { help_text: _omit, ...older } = ok
    expect(localValidate(older, FIELDS)).toEqual([])
  })
})
