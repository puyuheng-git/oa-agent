import { describe, expect, it } from 'vitest'
import { conversationLink } from './files'

describe('conversationLink', () => {
  it('有 thread_id 时跳转到对话记录', () => {
    expect(conversationLink('thr_1')).toEqual({ path: '/conversations', query: { thread: 'thr_1' } })
  })

  it('无 thread_id 时不可跳转', () => {
    expect(conversationLink(null)).toBeNull()
  })
})
