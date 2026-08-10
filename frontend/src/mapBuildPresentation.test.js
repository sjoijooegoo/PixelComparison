import { describe, expect, it } from 'vitest'
import {
  MAP_BUILD_SERIES,
  atlasColor,
  bytesToMiB,
  formatBytes,
  formatExactBytes,
  formatMiB,
  linePath,
  niceChartMaximum,
  rankMetricDetails,
  trendAxisLabel,
  trendDayKey,
} from './mapBuildPresentation'

describe('map build presentation helpers', () => {
  it('趋势只展示资源规模口径', () => {
    expect(MAP_BUILD_SERIES.map((series) => series.key)).toEqual([
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
    })
    expect(rows).toHaveLength(12)
    expect(rows[0].key).toBe('precomputed_light_volume_bytes')
    expect(rows.map((row) => row.key)).toContain('lightmap_all_mips_bytes')
    expect(rows.map((row) => row.key)).not.toContain('lightmap_bytes')
    expect(rows.map((row) => row.key)).not.toContain('total_bytes')
    expect(rows.map((row) => row.key)).not.toContain('texture_count')
  })

  it('同一天多个批次在横轴补充时刻以便区分', () => {
    const point = { batch: { created_at: '2026-08-01T17:30', id: '803' } }
    expect(trendDayKey(point)).toBe('2026-08-01')
    expect(trendAxisLabel(point)).toBe('08-01')
    expect(trendAxisLabel(point, true)).toBe('08-01 17:30')
  })
})
