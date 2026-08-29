import { describe, expect, it } from 'vitest'

import {
  configuredBandIndex,
  configuredBands,
  formatCoordinateValue,
  formatConfiguredBandRange,
  linearHeatColor,
  metricRange,
  resolvedHeatColor,
} from './colors'

const configured = (segments) => ({ mode: 'configured', segments })

describe('GPM heat colors', () => {
  it('坐标保留最多两位小数且不插入千分位逗号', () => {
    expect(formatCoordinateValue(-192711)).toBe('-192711')
    expect(formatCoordinateValue(1234.567)).toBe('1234.57')
  })

  it('严格按最终表达式标尺保留共享边界归属', () => {
    const lowerOwnsBoundary = configured([
      { color: '#111111', expression: '<=100' },
      { color: '#222222', expression: '>100' },
    ])
    const upperOwnsBoundary = configured([
      { color: '#111111', expression: '<100' },
      { color: '#222222', expression: '>=100' },
    ])

    expect(resolvedHeatColor(100, lowerOwnsBoundary)).toBe('#111111')
    expect(resolvedHeatColor(100, upperOwnsBoundary)).toBe('#222222')
    expect(configuredBands(lowerOwnsBoundary).map(formatConfiguredBandRange))
      .toEqual(['[0,100]', '(100,+∞)'])
  })

  it('用数学区间紧凑显示常规半开标尺', () => {
    const scale = configured([
      { color: '#111111', expression: '<365' },
      { color: '#222222', expression: '>=365 & <390' },
      { color: '#333333', expression: '>=390' },
    ])
    expect(configuredBands(scale).map(formatConfiguredBandRange))
      .toEqual(['[0,365)', '[365,390)', '[390,+∞)'])
    expect([364, 365, 389, 390].map((value) => configuredBandIndex(value, scale)))
      .toEqual([0, 1, 1, 2])
  })

  it('按当前指标最小值到最大值线性映射绿色到红色', () => {
    const points = [0, 50, 100].map((value) => ({ heat_map_data: { m: value } }))
    const range = metricRange(points, 'm')

    expect(range).toEqual([0, 100])
    expect(linearHeatColor(0, range)).toBe('hsl(120 78% 48%)')
    expect(linearHeatColor(50, range)).toBe('hsl(60 78% 48%)')
    expect(linearHeatColor(100, range)).toBe('hsl(0 78% 48%)')
  })

  it('缺失值和布尔值不会被误判为数值 0', () => {
    const scale = configured([
      { color: '#111111', expression: '<10' },
      { color: '#222222', expression: '>=10' },
    ])
    const points = [null, false, ' ', 12].map((value) => ({ heat_map_data: { m: value } }))

    expect(metricRange(points, 'm')).toEqual([12, 12])
    expect(resolvedHeatColor(null, scale)).toBe('#6b7280')
    expect(resolvedHeatColor(false, { mode: 'dynamic', range: [0, 100] }))
      .toBe('#6b7280')
  })

  it('按解析结果在配置标尺和动态范围之间切换', () => {
    const scale = configured([
      { color: '#111111', expression: '<10' },
      { color: '#222222', expression: '>=10 & <20' },
      { color: '#333333', expression: '>=20' },
    ])
    expect(resolvedHeatColor(15, scale)).toBe('#222222')
    expect(configuredBands(scale)).toHaveLength(3)
    expect(resolvedHeatColor(50, { mode: 'dynamic', range: [0, 100] }))
      .toBe('hsl(60 78% 48%)')
  })

  it('标尺数组被不可变替换后重新编译颜色段', () => {
    const scale = configured([
      { color: '#111111', expression: '<10' },
      { color: '#222222', expression: '>=10' },
    ])
    expect(resolvedHeatColor(20, scale)).toBe('#222222')

    scale.segments = [
      { color: '#333333', expression: '<10' },
      { color: '#444444', expression: '>=10' },
    ]
    expect(resolvedHeatColor(20, scale)).toBe('#444444')
  })

})
