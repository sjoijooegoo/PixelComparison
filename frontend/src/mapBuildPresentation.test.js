import { describe, expect, it } from 'vitest'
import {
  MAP_BUILD_SERIES,
  atlasColor,
  bytesToMiB,
  compareMetricValues,
  formatBytes,
  formatExactBytes,
  formatMetricDelta,
  formatMiB,
  linePath,
  mapBuildDeltaColor,
  metricComparisonPercentRange,
  niceChartMaximum,
  rankMetricDetails,
  trendAxisLabel,
  trendDayKey,
} from './mapBuildPresentation'

describe('map build presentation helpers', () => {
  it('趋势提供全部静态指标且只默认开启主要五项', () => {
    expect(MAP_BUILD_SERIES.map((series) => series.key)).toEqual([
      'all_mips_bytes',
      'cook_estimate_bytes',
      'lightmap_all_mips_bytes',
      'shadowmap_all_mips_bytes',
      'hue_all_mips_bytes',
      'precomputed_light_volume_bytes',
      'precomputed_reflection_volume_bytes',
      'volumetric_lightmap_bytes',
      'reflection_capture_bytes',
      'mesh_map_build_data_bytes',
      'light_build_data_bytes',
      'precomputed_instanced_ilc_bytes',
      'precomputed_instanced_pr_bytes',
      'lightmap_resource_cluster_bytes',
    ])
    expect(MAP_BUILD_SERIES.filter((series) => series.defaultVisible).map((series) => series.key)).toEqual([
      'all_mips_bytes',
      'cook_estimate_bytes',
      'lightmap_all_mips_bytes',
      'shadowmap_all_mips_bytes',
      'hue_all_mips_bytes',
    ])
  })

  it('以二进制 MiB 展示 UE 字节指标', () => {
    expect(bytesToMiB(2 * 1024 * 1024)).toBe(2)
    expect(formatBytes(2 * 1024 * 1024)).toBe('2.00 MiB')
    expect(formatMiB(0)).toBe('0.00 MiB')
    expect(formatMiB(512)).toBe('<0.001 MiB')
    expect(formatMiB(8 * 1024)).toBe('0.008 MiB')
    expect(formatMiB(2 * 1024 * 1024)).toBe('2.00 MiB')
    expect(formatExactBytes(1234567)).toBe('1,234,567 B')
  })

  it('热力颜色随体积升高并对空集合提供稳定冷色', () => {
    expect(atlasColor(null, 0)).toBe('rgb(33, 72, 118)')
    expect(atlasColor(0, 100)).toBe('rgb(33, 72, 118)')
    expect(atlasColor(1, 100)).not.toBe(atlasColor(100, 100))
  })

  it('热力颜色按参考图的蓝色到橙色控制点线性过渡', () => {
    const reference = [
      { value: 0, rgb: [33, 72, 118] },
      { value: 20, rgb: [71, 93, 112] },
      { value: 34, rgb: [117, 105, 89] },
      { value: 65, rgb: [179, 121, 57] },
      { value: 100, rgb: [222, 132, 35] },
    ]

    for (const sample of reference) {
      const actual = atlasColor(sample.value, 100).match(/\d+/g).map(Number)
      expect(actual, `${sample.value} MiB => ${actual.join(', ')}`).toEqual(sample.rgb)
    }
  })

  it('折线遇到缺失批次时断开而不是连线或补零', () => {
    const path = linePath([1, null, 3], (index) => index * 10, (value) => 100 - value)
    expect(path).toBe('M 0.00 99.00M 20.00 97.00')
  })

  it('Y 轴最大值向上取易读刻度且不会小于数据', () => {
    expect(niceChartMaximum([0, 2.34, 1.2])).toBeGreaterThanOrEqual(2.34)
    expect(niceChartMaximum([])).toBe(1)
  })

  it('占用明细只展示资源规模并按数值降序排列', () => {
    const rows = rankMetricDetails({
      total_bytes: 300,
      all_mips_bytes: 500,
      cook_estimate_bytes: 400,
      lightmap_all_mips_bytes: 100,
      shadowmap_all_mips_bytes: 200,
      hue_all_mips_bytes: 50,
      precomputed_light_volume_bytes: 700,
      precomputed_reflection_volume_bytes: 600,
      volumetric_lightmap_bytes: 40,
      reflection_capture_bytes: 30,
      mesh_map_build_data_bytes: 20,
      light_build_data_bytes: 10,
      precomputed_instanced_ilc_bytes: 9,
      precomputed_instanced_pr_bytes: 8,
      lightmap_resource_cluster_bytes: 7,
      texture_count: 999,
    }, { precomputed_light_volume_bytes: 350 })
    expect(rows).toHaveLength(12)
    expect(rows[0].key).toBe('precomputed_light_volume_bytes')
    expect(rows.map((row) => row.key)).toContain('lightmap_all_mips_bytes')
    expect(rows.map((row) => row.key)).not.toContain('lightmap_bytes')
    expect(rows.map((row) => row.key)).not.toContain('total_bytes')
    expect(rows.map((row) => row.key)).not.toContain('texture_count')
    expect(rows[0].previousValue).toBe(350)
    expect(rows[1].previousValue).toBeNull()
  })

  it('历史对比覆盖上升、下降、稳定、新增和无基准边界', () => {
    expect(formatMetricDelta(compareMetricValues(120, 100))).toBe('↑20.0%')
    expect(formatMetricDelta(compareMetricValues(75, 100))).toBe('↓25.0%')
    expect(formatMetricDelta(compareMetricValues(100.04, 100))).toBe('0.0%')
    expect(formatMetricDelta(compareMetricValues(1, 0))).toBe('新增')
    expect(formatMetricDelta(compareMetricValues(0, 0))).toBe('0.0%')
    expect(formatMetricDelta(compareMetricValues(1, null))).toBe('新增')
    expect(formatMetricDelta(compareMetricValues(1, 1, false))).toBe('—')
  })

  it('从当前页面的可比较指标动态计算变化率范围', () => {
    expect(metricComparisonPercentRange([
      {
        current: {
          all_mips_bytes: 80,
          cook_estimate_bytes: 130,
          texture_count: 5,
          total_bytes: 1000,
        },
        previous: {
          all_mips_bytes: 100,
          cook_estimate_bytes: 100,
          texture_count: null,
          total_bytes: 1,
        },
      },
      {
        current: { lightmap_all_mips_bytes: 20 },
        previous: { lightmap_all_mips_bytes: 20 },
      },
    ])).toEqual([-20, 30])
    expect(metricComparisonPercentRange([])).toEqual([0, 0])
  })

  it('允许不同展示区域只用自己的指标计算动态范围', () => {
    const pairs = [{
      current: { all_mips_bytes: 110, cook_estimate_bytes: 400 },
      previous: { all_mips_bytes: 100, cook_estimate_bytes: 100 },
    }]

    expect(metricComparisonPercentRange(pairs, ['all_mips_bytes'])).toEqual([0, 10])
    expect(metricComparisonPercentRange(pairs, ['cook_estimate_bytes'])).toEqual([0, 300])
  })

  it('样本充足时用正负 P90 隔离极端变化率', () => {
    const regularPairs = Array.from({ length: 10 }, (_, index) => {
      const percent = index + 1
      return {
        current: {
          all_mips_bytes: 100 + percent,
          cook_estimate_bytes: 100 - percent,
        },
        previous: {
          all_mips_bytes: 100,
          cook_estimate_bytes: 100,
        },
      }
    })
    const outlier = {
      current: { all_mips_bytes: 1100, cook_estimate_bytes: 1 },
      previous: { all_mips_bytes: 100, cook_estimate_bytes: 100 },
    }

    expect(metricComparisonPercentRange([...regularPairs, outlier])).toEqual([-10, 10])
  })

  it('变化率按下降绿、中性灰紫、上升粉红连续插值', () => {
    const range = [-20, 30]
    expect(mapBuildDeltaColor({ kind: 'decrease', percent: -20 }, range)).toBe('#52e817')
    expect(mapBuildDeltaColor({ kind: 'decrease', percent: -10 }, range)).toBe('#84ca65')
    expect(mapBuildDeltaColor({ kind: 'increase', percent: 3 }, range)).toBe('#c1a2ae')
    expect(mapBuildDeltaColor({ kind: 'increase', percent: 15 }, range)).toBe('#eb7d9c')
    expect(mapBuildDeltaColor({ kind: 'increase', percent: 30 }, range)).toBe('#ff1111')
    expect(mapBuildDeltaColor({ kind: 'steady', percent: 0 }, range)).toBeUndefined()
  })

  it('同一天多个批次在横轴补充时刻以便区分', () => {
    const point = { batch: { created_at: '2026-08-01T17:30', id: '803' } }
    expect(trendDayKey(point)).toBe('2026-08-01')
    expect(trendAxisLabel(point)).toBe('08-01')
    expect(trendAxisLabel(point, true)).toBe('08-01 17:30')
  })
})
