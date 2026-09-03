import { describe, expect, it, vi } from 'vitest'

import { clearNativeTitle, vNoNativeTitle } from './noNativeTitle'

function fakeElement() {
  const attributes = new Map([['title', '当前选中值']])
  return {
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    removeAttribute: vi.fn((name) => attributes.delete(name)),
    matches: vi.fn((selector) => selector === '.arco-select-view[title]' && attributes.has('title')),
    querySelectorAll: vi.fn(() => []),
    setAttribute: (name, value) => attributes.set(name, value),
    title: () => attributes.get('title'),
  }
}

describe('noNativeTitle', () => {
  it('清除控件生成的原生 title，并在再次进入时继续清理', () => {
    const element = fakeElement()
    clearNativeTitle(element)
    expect(element.title()).toBeUndefined()

    element.setAttribute('title', '更新后的选中值')
    vNoNativeTitle.mounted(element)
    expect(element.title()).toBeUndefined()

    const enter = element.addEventListener.mock.calls.find(([event]) => event === 'mouseenter')[1]
    element.setAttribute('title', '组件重新生成的值')
    enter()
    expect(element.title()).toBeUndefined()

    vNoNativeTitle.beforeUnmount(element)
    expect(element.removeEventListener).toHaveBeenCalledWith('mouseenter', enter)
  })

  it('可以在筛选模块容器内统一清理下拉控件', () => {
    const select = fakeElement()
    const container = fakeElement()
    container.removeAttribute('title')
    container.matches.mockReturnValue(false)
    container.querySelectorAll.mockReturnValue([select])

    clearNativeTitle(container)

    expect(select.title()).toBeUndefined()
  })
})
