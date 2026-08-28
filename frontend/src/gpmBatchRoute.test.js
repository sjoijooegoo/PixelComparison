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
    expect(parsed).toMatchObject({ branchTag: 'main', page: 1, shadingQuality: '' })
  })

  it('序列化筛选、分页和返回地址', () => {
    const location = gpmBatchLocation({
      returnTo: '/gpm-heatmap/SceneA?batch=gpm-1',
      branchTag: 'engine-ue5', platform: 'Android', sceneId: 'SceneA',
      shadingQuality: 5, capturedFrom: '2026-08-01', capturedTo: '2026-08-28', page: 2,
    })
    expect(location).toEqual({
      path: '/batch-management/gpm',
      query: {
        return_to: '/gpm-heatmap/SceneA?batch=gpm-1', branch_tag: 'engine-ue5',
        platform: 'Android', scene_id: 'SceneA', quality: '5',
        from: '2026-08-01', to: '2026-08-28', page: '2',
      },
    })
    expect(gpmBatchRouteKey(parseGpmBatchRoute({ query: location.query }))).toBe(
      gpmBatchRouteKey({
        returnTo: '/gpm-heatmap/SceneA?batch=gpm-1', branchTag: 'engine-ue5',
        platform: 'Android', sceneId: 'SceneA', shadingQuality: 5,
        capturedFrom: '2026-08-01', capturedTo: '2026-08-28', page: 2,
      }),
    )
  })
})
