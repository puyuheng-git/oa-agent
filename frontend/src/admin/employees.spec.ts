import { describe, expect, it } from 'vitest'
import {
  CHECKPOINT_RESTORE_WARNING,
  EMPLOYEES_BASE,
  employeesListQuery,
  employeePath,
  memoryPath,
  threadMessagesPath,
  threadsPath,
  visibilityGrantsBatchPath,
  visibilityGrantsPath,
  visibilityPath,
  type MemoryClearBody,
  type ThreadBatchBody,
  type ThreadRestoreBody,
  type VisibilityGrantBody,
} from './employees'

describe('employees API paths', () => {
  it('列表 query 仅包含非空字段', () => {
    expect(employeesListQuery({})).toEqual({})
    expect(employeesListQuery({ q: '  alice  ', page: 2, page_size: 50 })).toEqual({
      q: 'alice',
      page: 2,
      page_size: 50,
    })
  })

  it('oa 路径编码', () => {
    expect(employeePath('zhang/san')).toBe(`${EMPLOYEES_BASE}/zhang%2Fsan`)
    expect(threadsPath('oa1', { status: 'deleted', page: 1, page_size: 20 })).toBe(
      `${EMPLOYEES_BASE}/oa1/threads?status=deleted&page=1&page_size=20`,
    )
    expect(threadMessagesPath('oa1', 'thr_x', { page: 2 })).toBe(
      `${EMPLOYEES_BASE}/oa1/threads/thr_x/messages?page=2`,
    )
    expect(memoryPath('oa1', { status: 'active', include_text: 1 })).toBe(
      `${EMPLOYEES_BASE}/oa1/memory?status=active&include_text=1`,
    )
    expect(visibilityPath('oa1')).toBe(`${EMPLOYEES_BASE}/oa1/visibility`)
    expect(visibilityGrantsPath('oa1')).toBe(`${EMPLOYEES_BASE}/oa1/visibility/grants`)
    expect(visibilityGrantsBatchPath('oa1')).toBe(`${EMPLOYEES_BASE}/oa1/visibility/grants/batch`)
  })

  it('恢复会话提示含 Checkpoint 不保证', () => {
    expect(CHECKPOINT_RESTORE_WARNING).toMatch(/Checkpoint/)
    expect(CHECKPOINT_RESTORE_WARNING).toMatch(/不保证/)
  })
})

describe('employees write body shapes', () => {
  it('restore / batch / grant / clear 字段', () => {
    const restore: ThreadRestoreBody = { reason: '误删恢复', status: 'active' }
    expect(restore).toEqual({ reason: '误删恢复', status: 'active' })

    const batch: ThreadBatchBody = { reason: '批量归档', action: 'archive', thread_ids: ['thr_a', 'thr_b'] }
    expect(batch.action).toBe('archive')
    expect(batch.thread_ids).toHaveLength(2)

    const grant: VisibilityGrantBody = { reason: '开放技能', skill_name: 'travel_query', effect: 'allow' }
    expect(grant.effect).toBe('allow')

    const clear: MemoryClearBody = { reason: '员工离职', confirm: true }
    expect(clear.confirm).toBe(true)
  })
})
