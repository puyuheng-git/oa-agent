import { describe, expect, it } from 'vitest'
import { NO_DATA, metadataDisplayField, routingEventMetadataDisplay } from './routing'

describe('routingEventMetadataDisplay', () => {
  it('读取 connector_id', () => {
    expect(routingEventMetadataDisplay({ connector_id: 'demo' }).connectorId).toBe('demo')
    expect(routingEventMetadataDisplay({ connector_id: 'office' }).connectorId).toBe('office')
  })

  it('缺失 metadata 或字段时为暂无数据', () => {
    expect(routingEventMetadataDisplay(null).connectorId).toBe(NO_DATA)
    expect(routingEventMetadataDisplay({}).connectorId).toBe(NO_DATA)
    expect(routingEventMetadataDisplay({ path: '/x' }).connectorId).toBe(NO_DATA)
    expect(routingEventMetadataDisplay(null).packId).toBe(NO_DATA)
    expect(routingEventMetadataDisplay({ connector_id: 'demo' }).packId).toBe(NO_DATA)
  })

  it('pack_id 仅在 metadata 存在时展示', () => {
    expect(routingEventMetadataDisplay({ pack_id: 'oa_travel' }).packId).toBe('oa_travel')
  })

  it('metadataDisplayField 不编造非标量', () => {
    expect(metadataDisplayField({ connector_id: { id: 'x' } }, 'connector_id')).toBe(NO_DATA)
    expect(metadataDisplayField({ connector_id: '' }, 'connector_id')).toBe(NO_DATA)
  })
})
