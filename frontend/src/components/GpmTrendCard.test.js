// @vitest-environment happy-dom

import { mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it } from 'vitest'

import GpmTrendCard from './GpmTrendCard.vue'

const points = [
  {
    batch_id: 'gpm-1', captured_at: '2026-08-20T09:00:00+08:00', p4_version: 2960782,
    metrics: { Scene_DC: 234.5, Drawcall: 300 },
  },
  {
    batch_id: 'gpm-2', captured_at: '2026-08-20T15:00:00+08:00', p4_version: 2960783,
    metrics: { Scene_DC: 258, Drawcall: 321 },
  },
]
const series = [
  { key: 'Scene_DC', label: '场景 DC', color: '#3491fa' },
  { key: 'Drawcall', label: 'DrawCall', color: '#4cd6b0' },
]

function mountCard(extraProps = {}) {
  return mount(GpmTrendCard, {
    props: {
      title: 'DC 趋势', series, points,
      storageKey: 'test.gpmTrend.visibleSeries', ...extraProps,
    },
  })
}

describe('GpmTrendCard', () => {
  beforeEach(() => window.localStorage.clear())

  it('绘制数值轴、日期轴并区分同日批次', () => {
    const wrapper = mountCard()

    expect(wrapper.findAll('.axis-label')).toHaveLength(5)
    expect(wrapper.get('.axis-line').attributes('x1')).toBe('52')
    expect(wrapper.get('.axis-line').attributes('x2')).toBe('1148')
    expect(Number(wrapper.find('.axis-label').attributes('x'))).toBeLessThan(52)
    expect(wrapper.findAll('.x-label').map((item) => item.text())).toEqual([
      '08-20 09:00', '08-20 15:00',
    ])
    expect(wrapper.findAll('.series-dot')).toHaveLength(4)
    expect(wrapper.get('header .series-selector').exists()).toBe(true)
  })

  it('鼠标经过点位时显示日期、P4、批次和所有可见指标', async () => {
    const wrapper = mountCard()

    await wrapper.findAll('.point-hit-area')[1].trigger('mouseenter')

    const tooltip = wrapper.get('.chart-tooltip')
    expect(tooltip.text()).toContain('2026-08-20 15:00')
    expect(tooltip.text()).toContain('P4 2960783')
    expect(tooltip.text()).toContain('批次 gpm-2')
    expect(tooltip.text()).toContain('258')
    expect(tooltip.text()).toContain('321')
    expect(wrapper.findAll('.series-dot').every((dot) => !dot.classes().includes('hovered'))).toBe(true)
  })

  it('图例按钮控制曲线显示并至少保留一项', async () => {
    const wrapper = mountCard()
    const buttons = wrapper.findAll('.series-selector button')

    await buttons[0].trigger('click')
    expect(wrapper.findAll('.series-dot')).toHaveLength(2)
    expect(buttons[0].attributes('aria-pressed')).toBe('false')

    await buttons[1].trigger('click')
    expect(wrapper.findAll('.series-dot')).toHaveLength(2)
    expect(wrapper.text()).toContain('至少保留一项')
  })

  it('缺失指标不会被错误绘制成 0', () => {
    const wrapper = mountCard({
      series: [series[0]],
      points: [{ batch_id: 'missing', captured_at: '2026-08-20T09:00:00', metrics: {} }],
    })

    expect(wrapper.find('.series-dot').exists()).toBe(false)
    expect(wrapper.text()).toContain('当前范围没有可显示的指标')
  })

  it('数值轴始终显示完整数字而不是万单位', () => {
    const wrapper = mountCard({
      series: [series[0]],
      points: [{
        batch_id: 'large', captured_at: '2026-08-20T09:00:00',
        metrics: { Scene_DC: 600000 },
      }],
    })

    const labels = wrapper.findAll('.axis-label').map((item) => item.text())
    expect(labels).toContain('1,000,000')
    expect(labels.every((label) => !label.includes('万'))).toBe(true)
  })
})
