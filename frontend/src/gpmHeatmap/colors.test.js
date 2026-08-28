import { describe, expect, it } from 'vitest'

import {
  configuredBands,
  heatColor,
  linearHeatColor,
  metricRange,
  resolvedHeatColor,
} from './colors'

describe('GPM heat colors', () => {
  it('使用配置阈值并保持五段纯色', () => {
    const thresholds = [150, 250, 350, 450]
    expect([100, 200, 300, 400, 500].map((value) => heatColor(value, thresholds))).toEqual([
      '#52e817', '#b7f400', '#ffb20a', '#ff4a0a', '#ff1111',
    ])
  })

  it('严格按表达式保留共享边界的归属', () => {
    expect(heatColor(100, [100], 'lower_is_better', ['#lower', '#upper'], ['lower']))
      .toBe('#lower')
    expect(heatColor(100, [100], 'lower_is_better', ['#lower', '#upper'], ['upper']))
      .toBe('#upper')

    const bands = configuredBands({
      mode: 'configured', thresholds: [100], boundary_owners: ['lower'],
      palette: { colors: ['#lower', '#upper'] },
    })
    expect(bands).toMatchObject([
      { maximum: 100, maximumInclusive: true },
      { minimum: 100, minimumInclusive: false },
    ])
  })

  it('按当前指标最小值到最大值线性映射绿色到红色', () => {
    const points = [0, 50, 100].map((value) => ({ heat_map_data: { m: value } }))
    const range = metricRange(points, 'm')

    expect(range).toEqual([0, 100])
    expect(linearHeatColor(0, range)).toBe('hsl(120 78% 48%)')
    expect(linearHeatColor(50, range)).toBe('hsl(60 78% 48%)')
    expect(linearHeatColor(100, range)).toBe('hsl(0 78% 48%)')
    expect(linearHeatColor(200, range)).toBe('hsl(0 78% 48%)')
  })

  it('按解析结果在固定五色标尺和动态范围之间切换', () => {
    const configured = {
      mode: 'configured', thresholds: [10, 20, 30, 40], direction: 'lower_is_better',
      palette: { colors: ['#1', '#2', '#3', '#4', '#5'], labels: ['a', 'b', 'c', 'd', 'e'] },
    }
    expect(resolvedHeatColor(35, configured)).toBe('#4')
    expect(configuredBands(configured)).toHaveLength(5)
    expect(resolvedHeatColor(50, { mode: 'dynamic', range: [0, 100] }))
      .toBe('hsl(60 78% 48%)')
  })

  it('支持自定义颜色段数量并按判定方向反转映射', () => {
    const scale = {
      mode: 'configured', thresholds: [100, 300], direction: 'higher_is_better',
      palette: { colors: ['#00ff00', '#ffaa00', '#ff0000'], labels: ['好', '中', '差'] },
    }
    expect(resolvedHeatColor(50, scale)).toBe('#ff0000')
    expect(resolvedHeatColor(200, scale)).toBe('#ffaa00')
    expect(resolvedHeatColor(500, scale)).toBe('#00ff00')
    expect(configuredBands(scale).map((item) => item.color))
      .toEqual(['#ff0000', '#ffaa00', '#00ff00'])
  })
})
