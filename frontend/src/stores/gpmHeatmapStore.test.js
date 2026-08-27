import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const apiMock = vi.hoisted(() => ({
  gpmHeatmapMeta: vi.fn(),
  gpmHeatmapFrame: vi.fn(),
  gpmHeatmapSceneTrends: vi.fn(),
  gpmHeatmapPoint: vi.fn(),
  gpmHeatmapTrends: vi.fn(),
}))

vi.mock('../api', () => ({
  api: apiMock,
  isRequestCancelled: (error) => error?.code === 'ABORTED',
}))

import { useGpmHeatmapStore } from './gpmHeatmapStore'

function deferred() {
  let resolve
  let reject
  const promise = new Promise((res, rej) => { resolve = res; reject = rej })
  return { promise, resolve, reject }
}

function frame(sceneId, pointId, batchId = sceneId) {
  return {
    batch: { batch_id: batchId },
    available_batches: [{ batch_id: batchId }],
    scene: { id: sceneId },
    heat_map: [{ key: 'Scene_DC', name: '场景 DC' }],
    trend: [{ key: 'Scene_DC', name: 'Scene_DC' }],
    points: [{ id: pointId, index: 1, heat_map_data: { Scene_DC: pointId } }],
  }
}

function meta(sceneId) {
  return {
    branch_tag: 'main',
    platforms: ['Android'],
    shading_qualities: [{ value: 5, label: '电影' }],
    scene_ids: [{
      value: sceneId,
      platforms: ['Android'],
      shading_qualities: [{ value: 5, label: '电影' }],
      platform_qualities: [{
        platform: 'Android', shading_qualities: [{ value: 5, label: '电影' }],
      }],
    }],
  }
}

beforeEach(() => {
  setActivePinia(createPinia())
  vi.clearAllMocks()
  apiMock.gpmHeatmapSceneTrends.mockResolvedValue({ available: true, points: [] })
})

describe('GPMHeatmap store request ordering', () => {
  it('场景快速切换时旧 frame 响应不能覆盖新场景', async () => {
    const oldRequest = deferred()
    const newRequest = deferred()
    apiMock.gpmHeatmapFrame
      .mockReturnValueOnce(oldRequest.promise)
      .mockReturnValueOnce(newRequest.promise)
    const store = useGpmHeatmapStore()
    store.filters.platform = 'Android'
    store.filters.shadingQuality = 5

    store.filters.sceneId = 'OldScene'
    const oldLoad = store.loadFrame()
    store.filters.sceneId = 'NewScene'
    const newLoad = store.loadFrame()
    newRequest.resolve(frame('NewScene', 22))
    await newLoad
    oldRequest.resolve(frame('OldScene', 11))
    await oldLoad

    expect(store.frame.scene.id).toBe('NewScene')
    expect(store.selectedPointId).toBe(22)
  })

  it('同参数并发读取会复用同一个 inflight 请求', async () => {
    const pending = deferred()
    apiMock.gpmHeatmapFrame.mockReturnValue(pending.promise)
    const store = useGpmHeatmapStore()
    Object.assign(store.filters, {
      sceneId: 'Village_Dimension_Main', platform: 'Android', shadingQuality: 5,
    })

    const first = store.loadFrame()
    const second = store.loadFrame()
    pending.resolve(frame('Village_Dimension_Main', 1, 'gpm-1'))
    await Promise.all([first, second])

    expect(apiMock.gpmHeatmapFrame).toHaveBeenCalledTimes(1)
    expect(store.filters.batchId).toBe('gpm-1')
  })

  it('点位切换并行加载详情和趋势', async () => {
    apiMock.gpmHeatmapPoint.mockResolvedValue({ id: 8, detail_data: [] })
    apiMock.gpmHeatmapTrends.mockResolvedValue({ available: false, points: [] })
    const store = useGpmHeatmapStore()
    store.trendMode = 'point'

    await store.selectPoint(8)

    expect(apiMock.gpmHeatmapPoint).toHaveBeenCalledWith(8, expect.any(Object))
    expect(apiMock.gpmHeatmapTrends).toHaveBeenCalledWith(8, { days: 14 }, expect.any(Object))
    expect(store.pointDetail.id).toBe(8)
  })

  it('单点模式切换点位时保留旧详情和趋势直到新响应完成', async () => {
    const detailRequest = deferred()
    const trendRequest = deferred()
    apiMock.gpmHeatmapPoint.mockReturnValue(detailRequest.promise)
    apiMock.gpmHeatmapTrends.mockReturnValue(trendRequest.promise)
    const store = useGpmHeatmapStore()
    store.trendMode = 'point'
    store.selectedPointId = 8
    store.pointDetail = { id: 8, detail_data: [{ name: 'old-detail' }] }
    store.trends = { available: true, points: [{ batch_id: 'old-trend' }] }

    const selecting = store.selectPoint(9)

    expect(store.selectedPointId).toBe(9)
    expect(store.pointDetail.id).toBe(8)
    expect(store.trends.points[0].batch_id).toBe('old-trend')
    expect(store.loading.detail).toBe(true)
    expect(store.loading.trends).toBe(true)

    detailRequest.resolve({ id: 9, detail_data: [{ name: 'new-detail' }] })
    trendRequest.resolve({ available: true, points: [{ batch_id: 'new-trend' }] })
    await selecting

    expect(store.pointDetail.id).toBe(9)
    expect(store.trends.points[0].batch_id).toBe('new-trend')
  })

  it('整体平均按场景筛选加载，切换点位不重复请求整体趋势', async () => {
    apiMock.gpmHeatmapSceneTrends.mockResolvedValue({ available: true, points: [] })
    apiMock.gpmHeatmapPoint.mockResolvedValue({ id: 8, detail_data: [] })
    const store = useGpmHeatmapStore()
    Object.assign(store.filters, {
      branchTag: 'main', sceneId: 'Village_Dimension_Main',
      platform: 'Android', shadingQuality: 5,
    })

    await store.changeTrendMode('average')
    await store.selectPoint(8)

    expect(apiMock.gpmHeatmapSceneTrends).toHaveBeenCalledTimes(1)
    expect(apiMock.gpmHeatmapSceneTrends).toHaveBeenCalledWith(
      'Village_Dimension_Main',
      {
        branch_tag: 'main', platform: 'Android', shading_quality: 5, days: 14,
      },
      expect.any(Object),
    )
    expect(apiMock.gpmHeatmapTrends).not.toHaveBeenCalled()
    expect(apiMock.gpmHeatmapPoint).toHaveBeenCalledTimes(1)
  })

  it('切换趋势统计方式时保留旧曲线直到新响应完成', async () => {
    const pending = deferred()
    apiMock.gpmHeatmapTrends.mockReturnValue(pending.promise)
    const store = useGpmHeatmapStore()
    store.trendMode = 'average'
    store.selectedPointId = 8
    store.trends = { available: true, points: [{ batch_id: 'old' }] }

    const switching = store.changeTrendMode('point')

    expect(store.trendMode).toBe('point')
    expect(store.trends.points[0].batch_id).toBe('old')
    expect(store.loading.trends).toBe(true)

    pending.resolve({ available: true, points: [{ batch_id: 'new' }] })
    await switching

    expect(store.trends.points[0].batch_id).toBe('new')
    expect(store.loading.trends).toBe(false)
  })

  it('路由仅接受 7、14、30 天并默认 14 天', async () => {
    apiMock.gpmHeatmapMeta.mockResolvedValue(meta('Village_Dimension_Main'))
    apiMock.gpmHeatmapFrame.mockResolvedValue(frame('Village_Dimension_Main', 8, 'gpm-1'))
    apiMock.gpmHeatmapPoint.mockResolvedValue({ id: 8, detail_data: [] })
    apiMock.gpmHeatmapTrends.mockResolvedValue({ available: true, points: [] })
    const store = useGpmHeatmapStore()

    await store.applyRoute({ sceneId: 'Village_Dimension_Main', days: 60 })

    expect(store.days).toBe(14)
    expect(store.routeState().trendMode).toBe('average')
  })

  it('重叠路由中已取消的 meta 响应不能再改筛选或发起旧 frame 请求', async () => {
    const oldMeta = deferred()
    const newMeta = deferred()
    apiMock.gpmHeatmapMeta
      .mockReturnValueOnce(oldMeta.promise)
      .mockReturnValueOnce(newMeta.promise)
    apiMock.gpmHeatmapFrame.mockResolvedValue(frame('NewScene', 22, 'new-batch'))
    apiMock.gpmHeatmapPoint.mockResolvedValue({ id: 22, detail_data: [] })
    apiMock.gpmHeatmapTrends.mockResolvedValue({ available: false, points: [] })
    const store = useGpmHeatmapStore()

    const oldRoute = store.applyRoute({ sceneId: 'OldScene', platform: 'Android', shadingQuality: 5 })
    const newRoute = store.applyRoute({ sceneId: 'NewScene', platform: 'Android', shadingQuality: 5 })
    newMeta.resolve(meta('NewScene'))
    await newRoute
    oldMeta.resolve(meta('OldScene'))
    await oldRoute

    expect(store.filters.sceneId).toBe('NewScene')
    expect(store.frame.scene.id).toBe('NewScene')
    expect(store.initialized).toBe(true)
    expect(apiMock.gpmHeatmapFrame).toHaveBeenCalledTimes(1)
    expect(apiMock.gpmHeatmapFrame.mock.calls[0][0]).toBe('NewScene')
  })

  it('页面离开后使进行中的路由初始化失效且不再发后续请求', async () => {
    const pendingMeta = deferred()
    apiMock.gpmHeatmapMeta.mockReturnValue(pendingMeta.promise)
    const store = useGpmHeatmapStore()

    const applying = store.applyRoute({
      sceneId: 'Village_Dimension_Main', platform: 'Android', shadingQuality: 5,
    })
    store.dispose()
    pendingMeta.resolve(meta('Village_Dimension_Main'))
    await applying

    expect(apiMock.gpmHeatmapFrame).not.toHaveBeenCalled()
    expect(store.initialized).toBe(false)
  })
})
