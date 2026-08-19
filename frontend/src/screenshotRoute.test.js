import { describe, expect, it } from 'vitest'

import {
  parseScreenshotRoute,
  screenshotLocation,
  screenshotRouteKey,
  screenshotStateFromFilters,
} from './screenshotRoute'

describe('screenshot route state', () => {
  it('序列化全部画质和指定日期', () => {
    expect(screenshotLocation({
      branchTag: 'main',
      sceneId: 'Scene A',
      baselineId: '',
      currentId: '',
      shadingQuality: '',
      dateMode: 'days',
      createdDates: ['2026-08-01', '2026-08-03'],
    })).toEqual({
      path: '/screenshot/Scene%20A',
      query: {
        branch_tag: 'main',
        quality: 'all',
        date_mode: 'days',
        dates: '2026-08-01,2026-08-03',
      },
    })
  })

  it('解析逗号和重复查询形式的指定日期', () => {
    expect(parseScreenshotRoute({
      params: { sceneId: 'SceneA' },
      query: {
        branch_tag: 'engine-ue5',
        quality: '3',
        date_mode: 'days',
        dates: ['2026-08-01,2026-08-03', '2026-08-05'],
      },
    })).toMatchObject({
      branchTag: 'engine-ue5',
      sceneId: 'SceneA',
      shadingQuality: '3',
      dateMode: 'days',
      createdDates: ['2026-08-01', '2026-08-03', '2026-08-05'],
    })
  })

  it('区分旧链接缺省筛选与显式全部画质', () => {
    const oldLink = parseScreenshotRoute({ params: {}, query: {} })
    expect(screenshotRouteKey(oldLink)).not.toBe(screenshotRouteKey({
      ...oldLink,
      shadingQuality: '',
    }))
  })

  it('把下拉框清空产生的 undefined 序列化为全部画质', () => {
    const state = screenshotStateFromFilters({
      branch_tag: 'main',
      scene_id: 'SceneA',
      shading_quality: undefined,
      dateMode: 'range',
      created_from: '2026-08-01',
      created_to: '2026-08-07',
      created_dates: [],
    })
    expect(screenshotLocation(state).query.quality).toBe('all')
  })
})
