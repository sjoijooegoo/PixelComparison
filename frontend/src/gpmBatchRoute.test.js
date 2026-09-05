import { describe, expect, it } from 'vitest'
import {
  defaultGpmCapturedRange,
  gpmBatchLocation,
  gpmBatchRouteKey,
  parseGpmBatchRoute,
} from './gpmBatchRoute'

describe('GPM batch management route state', () => {
  it('默认最近 30 天、main 分支和第一页', () => {
    expect(defaultGpmCapturedRange(30, new Date(2026, 7, 28))).toEqual({
      capturedFrom: '2026-07-30', capturedTo: '2026-08-28',
    })
    const parsed = parseGpmBatchRoute({ query: {} })
    expect(parsed).toMatchObject({
      branchTag: 'main', page: 1, shadingQuality: '', rangeMode: 'rolling',
    })
  })

  it('序列化筛选、分页和返回地址', () => {
    const location = gpmBatchLocation({
      returnTo: '/gpm-heatmap/SceneA?batch=gpm-1',
      branchTag: 'engine-ue5', platform: 'Android', mapName: 'SceneA',
      shadingQuality: 5, rangeMode: 'fixed',
      capturedFrom: '2026-08-01', capturedTo: '2026-08-28', page: 2,
    })
    expect(location).toEqual({
      path: '/batch-management/gpm',
      query: {
        return_to: '/gpm-heatmap/SceneA?batch=gpm-1', branch_tag: 'engine-ue5',
        platform: 'Android', map_name: 'SceneA', quality: '5',
        range_mode: 'fixed', from: '2026-08-01', to: '2026-08-28', page: '2',
      },
    })
    expect(gpmBatchRouteKey(parseGpmBatchRoute({ query: location.query }))).toBe(
      gpmBatchRouteKey({
        returnTo: '/gpm-heatmap/SceneA?batch=gpm-1', branchTag: 'engine-ue5',
        platform: 'Android', mapName: 'SceneA', shadingQuality: 5,
        rangeMode: 'fixed', capturedFrom: '2026-08-01', capturedTo: '2026-08-28', page: 2,
      }),
    )
  })

  it('滚动范围 URL 不固化日期，避免后续刷新永远看不到新批次', () => {
    expect(gpmBatchLocation({ branchTag: 'main', rangeMode: 'rolling', page: 1 })).toEqual({
      path: '/batch-management/gpm',
      query: { branch_tag: 'main', range_mode: 'rolling' },
    })
  })

  it('定位批次进入 URL 和路由身份，普通翻页不携带定位', () => {
    const location = gpmBatchLocation({ focusBatchId: '67526', page: 3 })
    const parsed = parseGpmBatchRoute({ query: location.query })
    expect(parsed).toMatchObject({ focusBatchId: '67526', page: 3 })
    expect(gpmBatchRouteKey(parsed)).not.toBe(gpmBatchRouteKey({ ...parsed, focusBatchId: '' }))
    expect(gpmBatchLocation({ page: 4 }).query.focus_batch).toBeUndefined()
  })
})
