import { describe, expect, it } from 'vitest'

import { heatColor, metricThresholds } from './colors'

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
})
