import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const apiMock = vi.hoisted(() => ({
  gpmHeatmapMeta: vi.fn(),
  gpmHeatmapFrame: vi.fn(),
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

    await store.selectPoint(8)

    expect(apiMock.gpmHeatmapPoint).toHaveBeenCalledWith(8, expect.any(Object))
    expect(apiMock.gpmHeatmapTrends).toHaveBeenCalledWith(8, { days: 30 }, expect.any(Object))
    expect(store.pointDetail.id).toBe(8)
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
})
