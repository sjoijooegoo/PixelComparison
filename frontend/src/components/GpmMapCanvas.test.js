// @vitest-environment happy-dom

import { mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import GpmMapCanvas from './GpmMapCanvas.vue'

const frame = {
  map: { show_direction: false },
  map_config: {
    image_url: '/map.png',
    x_min: 0,
    x_max: 100,
    y_min: 0,
    y_max: 100,
  },
  heat_map: [{
    key: 'Scene_DC',
    name: '场景DC',
    scale: {
      mode: 'configured',
      segments: [
        { color: '#00ff00', expression: '<365' },
        { color: '#ffff00', expression: '>=365 & <390' },
        { color: '#ff0000', expression: '>=390' },
      ],
    },
  }],
  points: [
    {
      id: 1,
      position: [20, 20],
      heat_map_data: { Scene_DC: 320 },
      metric_change_percent: { Scene_DC: 28 },
    },
    { id: 2, position: [40, 40], heat_map_data: { Scene_DC: 380 } },
  ],
}

describe('GpmMapCanvas legend interactions', () => {
  beforeEach(() => {
    globalThis.ResizeObserver = class {
      observe() {}
      unobserve() {}
      disconnect() {}
    }
    HTMLCanvasElement.prototype.getContext = vi.fn(() => ({
      setTransform: vi.fn(),
      clearRect: vi.fn(),
    }))
  })

  it('悬停强调颜色段，点击切换该段的显示状态', async () => {
    const wrapper = mount(GpmMapCanvas, { props: { frame, metricKey: 'Scene_DC' } })
    const bands = wrapper.findAll('.band-legend')

    expect(bands.map((band) => band.text())).toEqual(['[0,365)', '[365,390)', '[390,+∞)'])
    await bands[1].trigger('mouseenter')
    expect(bands[1].classes()).toContain('is-hovered')

    await bands[1].trigger('click')
    expect(bands[1].classes()).toContain('is-hidden')
    expect(bands[1].attributes('aria-pressed')).toBe('false')

    await bands[1].trigger('click')
    expect(bands[1].classes()).not.toContain('is-hidden')
    expect(bands[1].attributes('aria-pressed')).toBe('true')
  })

  it('点位面板在指标值后显示相对上一批次的升降百分比', async () => {
    const wrapper = mount(GpmMapCanvas, {
      props: {
        frame: { ...frame, previous_batch: { batch_id: 'previous' } },
        metricKey: 'Scene_DC',
      },
    })

    wrapper.vm.hoveredPointId = 1
    wrapper.vm.tooltipAnchor = { x: 20, y: 20, side: 'right' }
    await wrapper.vm.$nextTick()

    expect(wrapper.get('.tooltip-metric strong').text()).toBe('320')
    expect(wrapper.get('.metric-change').text()).toBe('↑ 28%')
    expect(wrapper.get('.metric-change').classes()).toContain('is-up')
  })
})
