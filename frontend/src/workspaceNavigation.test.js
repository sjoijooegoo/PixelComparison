import { describe, expect, it, vi } from 'vitest'
import {
  batchManagementLocation,
  gpmSettingsLocation,
  safeReturnTo,
  screenshotSettingsLocation,
  workspaceContext,
} from './workspaceNavigation'

describe('workspace navigation context', () => {
  it('批次切换尚未同步 URL 时，用实际帧和点位生成返回地址', () => {
    const location = batchManagementLocation({
      path: '/gpm-heatmap/OldMap',
      fullPath: '/gpm-heatmap/OldMap?batch=old&platform=IOS&quality=4&point=1&metric=OldMetric#chart',
    }, {
      map: { map_name: 'New Map' },
      batch: { batch_id: 'shown', branch_tag: 'main', platform: 'Android', shading_quality: 0 },
    }, { point: 13, metric: 'Scene_Tris', trendMode: 'point', days: 30 })
    const target = new URL(location.query.return_to, 'http://localhost')
    expect(target.pathname).toBe('/gpm-heatmap/New%20Map')
    expect(Object.fromEntries(target.searchParams)).toEqual({
      batch: 'shown', branch_tag: 'main', platform: 'Android', quality: '0',
      point: '13', metric: 'Scene_Tris', trend_mode: 'point', days: '30',
    })
    expect(target.hash).toBe('#chart')
    expect(location.query.focus_batch).toBe('shown')
  })

  it('来源批次超出默认日期时扩展范围，确保仍能定位', () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date(2026, 8, 5, 12))
    try {
      const location = batchManagementLocation({ path: '/gpm-heatmap/Forest', fullPath: '/gpm-heatmap/Forest' }, {
        map: { map_name: 'Forest' },
        batch: { batch_id: 'older', branch_tag: 'main', platform: 'Android', shading_quality: 0, captured_at: '2026-08-01T12:00:00+08:00' },
      })
      expect(location.query).toMatchObject({
        focus_batch: 'older', range_mode: 'fixed', from: '2026-08-01', to: '2026-09-05', quality: '0',
      })
    } finally { vi.useRealTimers() }
  })
  it('按当前工作区选择独立批次域并携带完整来源', () => {
    const gpmRoute = {
      path: '/gpm-heatmap/SceneA',
      fullPath: '/gpm-heatmap/SceneA?branch_tag=main&quality=5',
      query: {},
    }
    expect(batchManagementLocation(gpmRoute)).toEqual({
      path: '/batch-management/gpm',
      query: { return_to: gpmRoute.fullPath },
    })

    const buildRoute = {
      path: '/map-build/SceneA', fullPath: '/map-build/SceneA?branch_tag=main', query: {},
    }
    expect(batchManagementLocation(buildRoute).path).toBe('/batch-management/capture')
    expect(workspaceContext({
      path: '/batch-management/capture', query: { return_to: buildRoute.fullPath },
    }).workspace).toBe('mapBuild')
  })

  it('截图设置固定属于截图工作区并保留来源', () => {
    const route = { path: '/screenshot/SceneA', fullPath: '/screenshot/SceneA?q=1' }
    expect(screenshotSettingsLocation(route)).toEqual({
      path: '/settings/screenshot-comparison', query: { return_to: route.fullPath },
    })
    expect(workspaceContext({
      path: '/settings/screenshot-comparison', query: { return_to: '/map-build/SceneA' },
    }).workspace).toBe('screenshot')
  })

  it('热力图设置固定属于热力图工作区并保留来源', () => {
    const route = { path: '/gpm-heatmap/SceneA', fullPath: '/gpm-heatmap/SceneA?batch=123' }
    expect(gpmSettingsLocation(route)).toEqual({
      path: '/settings/gpm-heatmap', query: { return_to: route.fullPath },
    })
    expect(workspaceContext({
      path: '/settings/gpm-heatmap', query: { return_to: route.fullPath },
    })).toMatchObject({ workspace: 'gpm', isSettings: true, returnTo: route.fullPath })
  })

  it('返回地址仅接受三个工作区内的本地地址', () => {
    expect(safeReturnTo('/screenshot/SceneA?quality=5')).toBe('/screenshot/SceneA?quality=5')
    expect(safeReturnTo('//example.com')).toBe('/screenshot')
    expect(safeReturnTo('/batch-management/gpm', '/gpm-heatmap')).toBe('/gpm-heatmap')
  })

  it('没有来源参数时返回当前管理域对应的工作区', () => {
    expect(workspaceContext({ path: '/batch-management/gpm', query: {} }).returnTo)
      .toBe('/gpm-heatmap')
    expect(workspaceContext({ path: '/batch-management/capture', query: {} }).returnTo)
      .toBe('/screenshot')
  })
})
