import { describe, expect, it, vi } from 'vitest'

import { isOverflowing, syncOverflowTitle, vOverflowTitle } from './overflowTitle'

function elementWithSize({ clientWidth = 100, scrollWidth = 100 } = {}) {
  const attributes = new Map()
  return {
    clientHeight: 20,
    clientWidth,
    scrollHeight: 20,
    scrollWidth,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    removeAttribute: vi.fn((name) => attributes.delete(name)),
    setAttribute: vi.fn((name, value) => attributes.set(name, value)),
    title: () => attributes.get('title'),
  }
}

describe('overflowTitle', () => {
  it('只给实际溢出的内容添加原生提示', () => {
    const fitting = elementWithSize()
    const clipped = elementWithSize({ scrollWidth: 180 })

    syncOverflowTitle(fitting, '完整内容')
    syncOverflowTitle(clipped, '被截断的完整内容')

    expect(isOverflowing(fitting)).toBe(false)
    expect(fitting.title()).toBeUndefined()
    expect(clipped.title()).toBe('被截断的完整内容')
  })

  it('内容或尺寸变化后刷新并在卸载时清理监听', () => {
    const element = elementWithSize({ scrollWidth: 180 })
    vOverflowTitle.mounted(element, { value: '旧内容' })
    expect(element.title()).toBe('旧内容')

    element.scrollWidth = 80
    vOverflowTitle.updated(element, { value: '新内容' })
    expect(element.title()).toBeUndefined()

    const refresh = element.addEventListener.mock.calls[0][1]
    vOverflowTitle.beforeUnmount(element)
    expect(element.removeEventListener).toHaveBeenCalledWith('mouseenter', refresh)
  })
})
