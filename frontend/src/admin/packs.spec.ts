import { beforeEach, describe, expect, it, vi } from 'vitest'

const mockGet = vi.fn()
const mockPost = vi.fn()

vi.mock('@/shared/http', () => ({
  http: {
    get: (...args: unknown[]) => mockGet(...args),
    post: (...args: unknown[]) => mockPost(...args),
  },
}))

import {
  PACKS_BASE,
  disablePack,
  enablePack,
  listPacks,
  packDisablePath,
  packEnablePath,
  packPath,
  type PackItem,
} from './packs'

const sample: PackItem = {
  id: 'oa_travel',
  display_name: '差旅',
  version: '1.0.0',
  enabled: true,
  default_enabled: true,
  connectors: ['office'],
  validation_errors: [],
}

describe('packs API paths', () => {
  it('pack id 路径编码', () => {
    expect(packPath('oa_travel')).toBe(`${PACKS_BASE}/oa_travel`)
    expect(packEnablePath('a/b')).toBe(`${PACKS_BASE}/a%2Fb/enable`)
    expect(packDisablePath('a/b')).toBe(`${PACKS_BASE}/a%2Fb/disable`)
  })
})

describe('packs API calls', () => {
  beforeEach(() => {
    mockGet.mockReset()
    mockPost.mockReset()
  })

  it('listPacks 调用 GET /v1/admin/packs', async () => {
    mockGet.mockResolvedValue({ items: [sample] })
    const r = await listPacks()
    expect(mockGet).toHaveBeenCalledWith(PACKS_BASE)
    expect(r.items).toHaveLength(1)
    expect(r.items[0].id).toBe('oa_travel')
  })

  it('enable/disable 经 POST 写链', async () => {
    mockPost.mockResolvedValue({ ...sample, enabled: false })
    await disablePack('oa_travel', { reason: '维护' })
    expect(mockPost).toHaveBeenCalledWith(`${PACKS_BASE}/oa_travel/disable`, { reason: '维护' })

    mockPost.mockResolvedValue(sample)
    await enablePack('oa_travel', { reason: '恢复' })
    expect(mockPost).toHaveBeenCalledWith(`${PACKS_BASE}/oa_travel/enable`, { reason: '恢复' })
  })
})
