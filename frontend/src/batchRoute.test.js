import { describe, expect, it } from 'vitest'

import {
  batchLocation,
  batchRouteKey,
  batchStateFromFilters,
  parseBatchRoute,
} from './batchRoute'

describe('batch catalog route state', () => {
  it('序列化场景、指定日期和分页', () => {
    expect(batchLocation({
      branchTag: 'engine-ue5',
      sceneId: 'Scene A',
      dateMode: 'days',
      createdDates: ['2026-08-01', '2026-08-03'],
      page: 2,
    })).toEqual({
      path: '/batches',
      query: {
        branch_tag: 'engine-ue5',
        scene_id: 'Scene A',
        date_mode: 'days',
        dates: '2026-08-01,2026-08-03',
        page: '2',
      },
    })
  })

  it('解析重复形式的指定日期并忽略历史画质参数', () => {
    const parsed = parseBatchRoute({
      query: {
        branch_tag: 'main',
        scene_id: 'SceneA',
        quality: '3',
        dates: ['2026-08-01,2026-08-03', '2026-08-05'],
        page: '3',
      },
    })

    expect(parsed).toMatchObject({
      branchTag: 'main',
      sceneId: 'SceneA',
      createdDates: ['2026-08-01', '2026-08-03', '2026-08-05'],
      page: '3',
    })
    expect(parsed).not.toHaveProperty('shadingQuality')
    expect(batchLocation(parsed).query).not.toHaveProperty('quality')
  })

  it('从筛选状态生成第一页路由', () => {
    const state = batchStateFromFilters({
      branch_tag: 'main',
      scene_id: '',
      dateMode: 'range',
      created_from: '2026-08-14',
      created_to: '2026-08-20',
      created_dates: [],
    })

    expect(batchLocation(state)).toEqual({
      path: '/batches',
      query: {
        branch_tag: 'main',
        date_mode: 'range',
        from: '2026-08-14',
        to: '2026-08-20',
      },
    })
  })

  it('路由对比键将分页字符串和内部数字视为同一状态', () => {
    const routeState = {
      branchTag: 'main',
      sceneId: 'SceneA',
      dateMode: 'range',
      createdFrom: '2026-08-14',
      createdTo: '2026-08-20',
      createdDates: [],
      page: '2',
    }

    expect(batchRouteKey(routeState)).toBe(batchRouteKey({
      ...routeState,
      page: 2,
    }))
  })
})
