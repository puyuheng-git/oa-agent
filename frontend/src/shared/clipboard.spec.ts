import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import { copyText } from './clipboard'

describe('copyText', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
  })
  afterEach(() => {
    document.body.innerHTML = ''
  })

  it('优先使用 clipboard API', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined)
    Object.defineProperty(navigator, 'clipboard', {
      configurable: true,
      value: { writeText },
    })
    await expect(copyText(' thr_abc ')).resolves.toBe(true)
    expect(writeText).toHaveBeenCalledWith('thr_abc')
  })

  it('clipboard 失败时回退 execCommand', async () => {
    Object.defineProperty(navigator, 'clipboard', {
      configurable: true,
      value: { writeText: vi.fn().mockRejectedValue(new Error('denied')) },
    })
    const exec = vi.fn().mockReturnValue(true)
    Object.defineProperty(document, 'execCommand', { configurable: true, value: exec })
    await expect(copyText('thr_xyz')).resolves.toBe(true)
    expect(exec).toHaveBeenCalledWith('copy')
  })
})
