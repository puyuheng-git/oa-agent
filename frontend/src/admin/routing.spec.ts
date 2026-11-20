import { describe, expect, it } from 'vitest'
import {
  CONTRACT_FALLBACK,
  CONTRACT_MODE,
  NO_DATA,
  auditReasonError,
  contractMigrateDiff,
  metadataDisplayField,
  routingEventMetadataDisplay,
  routingModeLabel,
} from './routing'

describe('routingEventMetadataDisplay', () => {
  it('读取 connector_id', () => {
    expect(routingEventMetadataDisplay({ connector_id: 'demo' }).connectorId).toBe('demo')
    expect(routingEventMetadataDisplay({ connector_id: 'office' }).connectorId).toBe('office')
  })

  it('缺失 metadata 或字段时为暂无数据', () => {
    expect(routingEventMetadataDisplay(null).connectorId).toBe(NO_DATA)
    expect(routingEventMetadataDisplay({}).connectorId).toBe(NO_DATA)
    expect(routingEventMetadataDisplay({ path: '/x' }).connectorId).toBe(NO_DATA)
  })

  it('metadataDisplayField 不编造非标量', () => {
    expect(metadataDisplayField({ connector_id: { id: 'x' } }, 'connector_id')).toBe(NO_DATA)
    expect(metadataDisplayField({ connector_id: '' }, 'connector_id')).toBe(NO_DATA)
  })
})

describe('routingModeLabel', () => {
  it('已知模式带中文名，未知模式原样，空值为暂无数据', () => {
    expect(routingModeLabel('legacy_prompt')).toBe('提示词海选（兼容/待迁移）（legacy_prompt）')
    expect(routingModeLabel('deterministic_first')).toContain('确定性优先')
    expect(routingModeLabel('custom_mode')).toBe('custom_mode')
    expect(routingModeLabel('')).toBe(NO_DATA)
    expect(routingModeLabel(null)).toBe(NO_DATA)
  })
})

describe('contractMigrateDiff', () => {
  it('只对照契约三项，未知的变更前不编造', () => {
    const lines = contractMigrateDiff('legacy_prompt')
    expect(lines.map((l) => l.key)).toEqual([
      'tool_routing_mode',
      'deterministic_fallback_mode',
      'routing_clarify_on_low_confidence',
    ])
    expect(lines[0].before).toBe('legacy_prompt')
    expect(lines[0].after).toBe(CONTRACT_MODE)
    expect(lines[1].before).toBe(NO_DATA)
    expect(lines[1].after).toBe(CONTRACT_FALLBACK)
    expect(lines[2].before).toBe(NO_DATA)
    expect(lines[2].after).toBe('true')
    expect(contractMigrateDiff('  ').find((l) => l.key === 'tool_routing_mode')?.before).toBe(NO_DATA)
  })
})

describe('auditReasonError', () => {
  it('原因须为 2～200 字', () => {
    expect(auditReasonError('好')).toBe('原因需为 2～200 个字')
    expect(auditReasonError('  迁到契约默认  ')).toBeNull()
    expect(auditReasonError('字'.repeat(201))).toBe('原因需为 2～200 个字')
  })
})
