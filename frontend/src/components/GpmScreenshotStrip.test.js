// @vitest-environment happy-dom

import { mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import GpmScreenshotStrip from './GpmScreenshotStrip.vue'

const points = [
  { id: 11, index: 1, thumbnail_url: '/thumb/1.jpg', image_url: '/image/1.jpg' },
  { id: 12, index: 2, thumbnail_url: '/thumb/2.jpg', image_url: '/image/2.jpg' },
]

function mountStrip() {
  return mount(GpmScreenshotStrip, {
    props: { points, selectedPointId: 11 },
    global: {
      stubs: {
        'a-image-preview-group': {
          props: ['srcList', 'visible', 'current', 'infinite'],
          emits: ['update:visible', 'update:current'],
          template: '<div v-if="visible" class="image-preview" :data-src="srcList[current]" :data-count="srcList.length" :data-current="current" />',
        },
      },
    },
  })
}

describe('GpmScreenshotStrip', () => {
  beforeEach(() => {
    Element.prototype.scrollIntoView = vi.fn()
    HTMLElement.prototype.scrollTo = vi.fn()
  })

  it('初始选中项不自动纠正截图条或外层页面的滚动位置', async () => {
    const wrapper = mountStrip()
    await wrapper.vm.$nextTick()

    expect(HTMLElement.prototype.scrollTo).not.toHaveBeenCalled()
    expect(Element.prototype.scrollIntoView).not.toHaveBeenCalled()
  })

  it('地图等外部来源切换点位时将对应截图直接移入可视区域', async () => {
    const wrapper = mountStrip()
    const strip = wrapper.find('.shot-strip').element
    const second = wrapper.findAll('.shot')[1].element
    Object.defineProperty(strip, 'clientWidth', { configurable: true, value: 300 })
    Object.defineProperty(second, 'offsetLeft', { configurable: true, value: 600 })
    Object.defineProperty(second, 'offsetWidth', { configurable: true, value: 280 })

    await wrapper.setProps({ selectedPointId: 12 })
    await wrapper.vm.$nextTick()

    expect(strip.scrollLeft).toBe(590)
    expect(Element.prototype.scrollIntoView).not.toHaveBeenCalled()
  })

  it('外部重复点击已选点位时仍可主动重新定位', () => {
    const wrapper = mountStrip()
    const strip = wrapper.find('.shot-strip').element
    const first = wrapper.findAll('.shot')[0].element
    Object.defineProperty(strip, 'clientWidth', { configurable: true, value: 300 })
    Object.defineProperty(first, 'offsetLeft', { configurable: true, value: 600 })
    Object.defineProperty(first, 'offsetWidth', { configurable: true, value: 280 })
    strip.scrollLeft = 0

    wrapper.vm.revealPoint(11)

    expect(strip.scrollLeft).toBe(590)
  })

  it('截图条内部点击切换点位时不自动回正滚动位置', async () => {
    const wrapper = mountStrip()
    await wrapper.findAll('.shot')[1].trigger('click')
    await wrapper.setProps({ selectedPointId: 12 })

    expect(HTMLElement.prototype.scrollTo).not.toHaveBeenCalled()
  })

  it('单击选择点位，双击后使用原图打开预览', async () => {
    const wrapper = mountStrip()
    const second = wrapper.findAll('.shot')[1]

    await second.trigger('click')
    await second.trigger('click')
    expect(wrapper.emitted('select')).toEqual([[12]])

    await second.trigger('dblclick')
    const preview = wrapper.find('.image-preview')
    expect(preview.attributes('data-src')).toBe('/image/2.jpg')
    expect(preview.attributes('data-count')).toBe('2')
    expect(preview.attributes('data-current')).toBe('1')
  })

  it('支持按住横向拖动滚动，并吞掉拖动后的点击', async () => {
    const wrapper = mountStrip()
    const strip = wrapper.find('.shot-strip')
    strip.element.scrollLeft = 300

    await strip.trigger('mousedown', { button: 0, clientX: 200, clientY: 30 })
    window.dispatchEvent(new MouseEvent('mousemove', { clientX: 120, clientY: 32 }))
    await wrapper.vm.$nextTick()
    expect(strip.element.scrollLeft).toBe(380)
    expect(strip.classes()).toContain('dragging')

    window.dispatchEvent(new MouseEvent('mouseup', { clientX: 120, clientY: 32 }))
    await wrapper.vm.$nextTick()
    await wrapper.find('.shot').trigger('click')
    expect(wrapper.emitted('select')).toBeUndefined()
    expect(strip.classes()).not.toContain('dragging')
  })

  it('纵向移动不劫持页面滚动', async () => {
    const wrapper = mountStrip()
    const strip = wrapper.find('.shot-strip')
    strip.element.scrollLeft = 100

    await strip.trigger('mousedown', { button: 0, clientX: 100, clientY: 20 })
    window.dispatchEvent(new MouseEvent('mousemove', { clientX: 103, clientY: 60 }))
    await wrapper.vm.$nextTick()
    expect(strip.element.scrollLeft).toBe(100)
    expect(strip.classes()).not.toContain('dragging')
    window.dispatchEvent(new MouseEvent('mouseup'))
  })
})
