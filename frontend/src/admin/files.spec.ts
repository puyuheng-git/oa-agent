import { beforeEach, describe, expect, it, vi } from 'vitest'

const mockGet = vi.fn()

vi.mock('@/shared/http', () => ({
  http: {
    get: (...args: unknown[]) => mockGet(...args),
  },
}))

import {
  EXPORT_FILES_BASE,
  conversationLink,
  exportOriginLabel,
  listExportFiles,
} from './files'

describe('listExportFiles', () => {
  beforeEach(() => {
    mockGet.mockReset()
  })

  it('可选 origin 作为查询参数传给 GET', async () => {
    mockGet.mockResolvedValue({ items: [], total: 0, page: 1, page_size: 20 })
    await listExportFiles({ origin: 'upload', page: 1 })
    expect(mockGet).toHaveBeenCalledWith(EXPORT_FILES_BASE, { origin: 'upload', page: 1 })
  })
})

describe('exportOriginLabel', () => {
  it('upload 显示用户上传', () => {
    expect(exportOriginLabel('upload')).toBe('用户上传')
  })

  it('export 显示助手导出', () => {
    expect(exportOriginLabel('export')).toBe('助手导出')
  })

  it('空值显示暂无数据', () => {
    expect(exportOriginLabel(null)).toBe('暂无数据')
    expect(exportOriginLabel(undefined)).toBe('暂无数据')
  })
})

describe('conversationLink', () => {
  it('有 thread_id 时跳转到对话记录', () => {
    expect(conversationLink('thr_1')).toEqual({ path: '/conversations', query: { thread: 'thr_1' } })
  })

  it('无 thread_id 时不可跳转', () => {
    expect(conversationLink(null)).toBeNull()
  })
})
