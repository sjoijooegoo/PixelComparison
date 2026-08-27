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
        'a-image-preview': {
          props: ['src', 'visible'],
          template: '<div class="image-preview" :data-src="src" />',
        },
      },
    },
  })
}

describe('GpmScreenshotStrip', () => {
  beforeEach(() => {
    Element.prototype.scrollIntoView = vi.fn()
  })

  it('单击选择点位，双击后使用原图打开预览', async () => {
    const wrapper = mountStrip()
    const second = wrapper.findAll('.shot')[1]

    await second.trigger('click')
    await second.trigger('click')
    expect(wrapper.emitted('select')).toEqual([[12]])

    await second.trigger('dblclick')
    expect(wrapper.find('.image-preview').attributes('data-src')).toBe('/image/2.jpg')
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
