// @vitest-environment happy-dom

import { mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

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

describe('GpmMapCanvas interactions', () => {
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

  afterEach(() => vi.useRealTimers())

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

    wrapper.vm.tooltipPointId = 1
    wrapper.vm.tooltipAnchor = { x: 20, y: 20, side: 'right' }
    await wrapper.vm.$nextTick()

    expect(wrapper.get('.tooltip-metric strong').text()).toBe('320')
    expect(wrapper.get('.metric-change').text()).toBe('↑ 28%')
    expect(wrapper.get('.metric-change').classes()).toContain('is-up')
  })

  it('小于 0.1% 的非零变化显示为近似零并使用零变化颜色', async () => {
    const point = frame.points[0]
    const frameWithChange = (change) => ({
      ...frame,
      previous_batch: { batch_id: 'previous' },
      points: [{
        ...point,
        metric_change_percent: { Scene_DC: change },
      }],
    })
    const wrapper = mount(GpmMapCanvas, {
      props: { frame: frameWithChange(0.04), metricKey: 'Scene_DC' },
    })
    wrapper.vm.tooltipPointId = 1
    wrapper.vm.tooltipAnchor = { x: 20, y: 20, side: 'right' }
    await wrapper.vm.$nextTick()

    const change = () => wrapper.get('.metric-change')
    expect(change().text()).toBe('≈0.0%')
    expect(change().classes()).toContain('is-flat')
    expect(change().classes()).not.toContain('is-up')

    await wrapper.setProps({ frame: frameWithChange(-0.04) })
    wrapper.vm.tooltipPointId = 1
    wrapper.vm.tooltipAnchor = { x: 20, y: 20, side: 'right' }
    await wrapper.vm.$nextTick()
    expect(change().text()).toBe('≈0.0%')
    expect(change().classes()).toContain('is-flat')
    expect(change().classes()).not.toContain('is-down')

    await wrapper.setProps({ frame: frameWithChange(0) })
    wrapper.vm.tooltipPointId = 1
    wrapper.vm.tooltipAnchor = { x: 20, y: 20, side: 'right' }
    await wrapper.vm.$nextTick()
    expect(change().text()).toBe('0%')
    expect(change().classes()).toContain('is-flat')
  })

  it('只在指针稳定停留后切换面板，离开点位后立即开始关闭', async () => {
    vi.useFakeTimers()
    const wrapper = mount(GpmMapCanvas, {
      props: {
        frame: { ...frame, map: { show_direction: true } },
        metricKey: 'Scene_DC',
      },
    })

    wrapper.vm.requestTooltip(1, { x: 20, y: 20, side: 'right' })
    await vi.advanceTimersByTimeAsync(60)
    wrapper.vm.requestTooltip(2, { x: 40, y: 40, side: 'right' })
    await vi.advanceTimersByTimeAsync(129)
    expect(wrapper.vm.tooltipPointId).toBeNull()

    await vi.advanceTimersByTimeAsync(1)
    expect(wrapper.vm.tooltipPointId).toBe(2)
    expect(wrapper.vm.tooltipArrowProgressById.get('2')).toBe(0)
    await vi.advanceTimersByTimeAsync(180)
    expect(wrapper.vm.tooltipArrowProgressById.get('2')).toBe(1)

    wrapper.vm.requestTooltip(1, { x: 20, y: 20, side: 'right' })
    await vi.advanceTimersByTimeAsync(129)
    expect(wrapper.vm.tooltipPointId).toBe(2)
    await vi.advanceTimersByTimeAsync(1)
    expect(wrapper.vm.tooltipPointId).toBe(1)
    await vi.advanceTimersByTimeAsync(180)
    expect(wrapper.vm.tooltipArrowProgressById.get('1')).toBe(1)
    expect(wrapper.vm.tooltipArrowProgressById.has('2')).toBe(false)

    wrapper.vm.requestTooltip(null, null)
    await vi.advanceTimersByTimeAsync(0)
    expect(wrapper.vm.tooltipPointId).toBeNull()
    await vi.advanceTimersByTimeAsync(180)
    expect(wrapper.vm.tooltipArrowProgressById.size).toBe(0)
  })

  it('Hover 方块在 130ms 内平滑放大，切换点位时同步过渡', async () => {
    vi.useFakeTimers()
    const wrapper = mount(GpmMapCanvas, { props: { frame, metricKey: 'Scene_DC' } })

    wrapper.vm.hoveredPointId = 1
    expect(wrapper.vm.hoveredSquareProgressById.get('1')).toBe(0)
    await vi.advanceTimersByTimeAsync(80)
    expect(wrapper.vm.hoveredSquareProgressById.get('1')).toBeGreaterThan(0)
    expect(wrapper.vm.hoveredSquareProgressById.get('1')).toBeLessThan(1)
    await vi.advanceTimersByTimeAsync(100)
    expect(wrapper.vm.hoveredSquareProgressById.get('1')).toBe(1)

    wrapper.vm.hoveredPointId = 2
    expect(wrapper.vm.hoveredSquareProgressById.get('2')).toBe(0)
    await vi.advanceTimersByTimeAsync(80)
    expect(wrapper.vm.hoveredSquareProgressById.get('1')).toBeLessThan(1)
    expect(wrapper.vm.hoveredSquareProgressById.get('2')).toBeGreaterThan(0)
    await vi.advanceTimersByTimeAsync(100)
    expect(wrapper.vm.hoveredSquareProgressById.has('1')).toBe(false)
    expect(wrapper.vm.hoveredSquareProgressById.get('2')).toBe(1)

    wrapper.vm.hoveredPointId = null
    await vi.advanceTimersByTimeAsync(180)
    expect(wrapper.vm.hoveredSquareProgressById.size).toBe(0)
  })
})
