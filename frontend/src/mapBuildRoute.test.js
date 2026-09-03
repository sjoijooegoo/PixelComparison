import { describe, expect, it } from 'vitest'
import { mapBuildBatchWindow, mapBuildComparison, mapBuildRoute } from './mapBuildRoute'

const now = new Date(2026, 7, 30, 12, 0, 0)

describe('mapBuildBatchWindow', () => {
  it('接受包含首尾日期的 60 天并拒绝 61 天', () => {
    expect(mapBuildBatchWindow.days(['2026-07-02', '2026-08-30'])).toBe(60)
    expect(mapBuildBatchWindow.fromPicker(['2026-07-02', '2026-08-30'], now)).toEqual({
      valid: true,
      mode: 'fixed',
      range: ['2026-07-02', '2026-08-30'],
    })
    expect(mapBuildBatchWindow.fromPicker(['2026-07-01', '2026-08-30'], now)).toEqual({
      valid: false,
      message: '创建时间范围最多选择 60 天',
    })
  })

  it('清空范围恢复滚动 30 天，超长深链也规范化为滚动窗口', () => {
    expect(mapBuildBatchWindow.fromPicker([], now)).toEqual({
      valid: true,
      mode: 'rolling',
      range: ['2026-08-01', '2026-08-30'],
    })
    expect(mapBuildBatchWindow.fromRoute(
      ['2026-07-01', '2026-08-30'],
      'fixed',
      now,
    )).toEqual({
      mode: 'rolling',
      range: ['2026-08-01', '2026-08-30'],
    })
  })
})

describe('mapBuildRoute', () => {
  it('集中解析固定日期、节点和显式对比批次', () => {
    const state = mapBuildRoute.parse({
      params: { sceneId: 'Forest_WP' },
      query: {
        range_mode: 'fixed', from: '2026-07-02', to: '2026-08-30',
        batch: '20', compare: 'batch', compare_batch: '19', scope: 'subtree',
        block: '2', sub: '3',
      },
    }, { routeReady: true, now })

    expect(state).toEqual({
      batchId: '20',
      comparisonSelection: 'batch:19',
      batchDateRange: ['2026-07-02', '2026-08-30'],
      batchDateRangeMode: 'fixed',
      metricScope: 'subtree',
      blockIndex: 2,
      subBlockIndex: 3,
      registryPath: null,
    })
  })

  it('生成稳定地址并忽略空查询参数', () => {
    const location = mapBuildRoute.location({
      sceneId: 'Forest_WP',
      branchTag: 'main',
      rangeMode: 'fixed',
      batchDateRange: ['2026-07-02', '2026-08-30'],
      hasOverview: true,
      batchId: '20',
      comparisonSelection: mapBuildComparison.batchValue('19'),
      metricScope: 'self',
      selection: { blockIndex: 2, subBlockIndex: null, registryPath: null },
    })
    expect(location).toEqual({
      path: '/map-build/Forest_WP',
      query: {
        branch_tag: 'main', range_mode: 'fixed',
        from: '2026-07-02', to: '2026-08-30',
        batch: '20', compare: 'batch', compare_batch: '19', scope: 'self', block: '2',
      },
    })
    expect(mapBuildRoute.matches({
      path: location.path,
      query: { ...location.query, unused: '' },
    }, location)).toBe(true)
  })
})
