import { describe, expect, it } from 'vitest'

import { heatColor, linearHeatColor, metricRange, metricThresholds } from './colors'

describe('GPM heat colors', () => {
  it('优先使用配置阈值并保持四段纯色', () => {
    const thresholds = metricThresholds([], 'Scene_DC', [150, 300, 450])
    expect(thresholds).toEqual([150, 300, 450])
    expect([100, 200, 400, 500].map((value) => heatColor(value, thresholds))).toEqual([
      '#2f80ed', '#b7babd', '#f2b315', '#fa541c',
    ])
  })

  it('无配置时从当前点位分布生成阈值', () => {
    const points = [1, 2, 3, 4, 5].map((value) => ({ heat_map_data: { m: value } }))
    expect(metricThresholds(points, 'm')).toEqual([2, 3, 4])
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
})
