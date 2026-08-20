import { describe, expect, it } from 'vitest'

import {
  batchLocation,
  batchRouteKey,
  batchStateFromFilters,
  parseBatchRoute,
} from './batchRoute'

describe('batch catalog route state', () => {
  it('序列化场景、全部画质、指定日期和分页', () => {
    expect(batchLocation({
      branchTag: 'engine-ue5',
      sceneId: 'Scene A',
      shadingQuality: '',
      dateMode: 'days',
      createdDates: ['2026-08-01', '2026-08-03'],
      page: 2,
    })).toEqual({
      path: '/batches',
      query: {
        branch_tag: 'engine-ue5',
        scene_id: 'Scene A',
        quality: 'all',
        date_mode: 'days',
        dates: '2026-08-01,2026-08-03',
        page: '2',
      },
    })
  })

  it('解析重复形式的指定日期并保留缺省筛选', () => {
    const parsed = parseBatchRoute({
      query: {
        branch_tag: 'main',
        scene_id: 'SceneA',
        dates: ['2026-08-01,2026-08-03', '2026-08-05'],
        page: '3',
      },
    })

    expect(parsed).toMatchObject({
      branchTag: 'main',
      sceneId: 'SceneA',
      shadingQuality: undefined,
      createdDates: ['2026-08-01', '2026-08-03', '2026-08-05'],
      page: '3',
    })
    expect(batchRouteKey(parsed)).not.toBe(batchRouteKey({
      ...parsed,
      shadingQuality: '',
    }))
  })

  it('从筛选状态生成显式的全部画质和第一页', () => {
    const state = batchStateFromFilters({
      branch_tag: 'main',
      scene_id: '',
      shading_quality: undefined,
      dateMode: 'range',
      created_from: '2026-08-14',
      created_to: '2026-08-20',
      created_dates: [],
    })

    expect(batchLocation(state)).toEqual({
      path: '/batches',
      query: {
        branch_tag: 'main',
        quality: 'all',
        date_mode: 'range',
        from: '2026-08-14',
        to: '2026-08-20',
      },
    })
  })

  it('路由对比键将 URL 字符串和内部数字视为同一状态', () => {
    const routeState = {
      branchTag: 'main',
      sceneId: 'SceneA',
      shadingQuality: '4',
      dateMode: 'range',
      createdFrom: '2026-08-14',
      createdTo: '2026-08-20',
      createdDates: [],
      page: '2',
    }

    expect(batchRouteKey(routeState)).toBe(batchRouteKey({
      ...routeState,
      shadingQuality: 4,
      page: 2,
    }))
  })
})
