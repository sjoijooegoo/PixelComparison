import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const apiMock = vi.hoisted(() => ({
  gpmHeatmapUploadMeta: vi.fn(),
  gpmHeatmapUploads: vi.fn(),
  deleteGpmHeatmapUpload: vi.fn(),
}))

vi.mock('../api', () => ({ api: apiMock }))

import { useGpmBatchStore } from './gpmBatchStore'

const meta = {
  branch_tags: ['engine-ue5', 'main'],
  platforms: ['Android'],
  scene_ids: ['Village_Dimension_Main'],
  shading_qualities: [{ value: 5, label: '电影' }],
}

function deferred() {
  let resolve
  const promise = new Promise((res) => { resolve = res })
  return { promise, resolve }
}

beforeEach(() => {
  setActivePinia(createPinia())
  vi.clearAllMocks()
  apiMock.gpmHeatmapUploadMeta.mockResolvedValue(meta)
  apiMock.gpmHeatmapUploads.mockResolvedValue({ items: [{ id: 1 }], total: 1 })
  apiMock.deleteGpmHeatmapUpload.mockResolvedValue({ deleted: true })
})

describe('GPM batch catalog store', () => {
  it('按路由规范化筛选并读取独立批次目录', async () => {
    const store = useGpmBatchStore()
    const state = await store.applyRoute({
      returnTo: '/gpm-heatmap/Village_Dimension_Main',
      branchTag: 'engine-ue5', platform: 'Android', sceneId: 'Village_Dimension_Main',
      shadingQuality: 5, capturedFrom: '2026-08-01', capturedTo: '2026-08-28', page: 2,
    })

    expect(apiMock.gpmHeatmapUploads).toHaveBeenCalledWith({
      branch_tag: 'engine-ue5', platform: 'Android', scene_id: 'Village_Dimension_Main',
      shading_quality: 5, captured_from: '2026-08-01', captured_to: '2026-08-28',
      page: 2, page_size: 10,
    })
    expect(state).toMatchObject({
      returnTo: '/gpm-heatmap/Village_Dimension_Main', branchTag: 'engine-ue5', page: 2,
    })
  })

  it('不允许未知筛选值污染目录请求', async () => {
    const store = useGpmBatchStore()
    await store.applyRoute({
      branchTag: 'main', platform: 'Windows', sceneId: 'Missing', shadingQuality: 2,
      capturedFrom: '2026-08-01', capturedTo: '2026-08-28', page: 1,
    })

    expect(store.filters).toMatchObject({
      branchTag: 'main', platform: '', sceneId: '', shadingQuality: '',
    })
  })

  it('删除调用 GPM 专属接口并刷新目录', async () => {
    const store = useGpmBatchStore()
    Object.assign(store.filters, {
      branchTag: 'main', capturedFrom: '2026-08-01', capturedTo: '2026-08-28',
    })
    store.batches = [{ id: 1 }]
    store.batchPage = 2

    await store.deleteBatch('gpm-1', 'main')

    expect(apiMock.deleteGpmHeatmapUpload).toHaveBeenCalledWith('gpm-1', 'main')
    expect(store.batchPage).toBe(1)
    expect(apiMock.gpmHeatmapUploads).toHaveBeenCalled()
  })

  it('快速切换路由时旧元数据不能覆盖最新筛选或发起旧目录请求', async () => {
    const oldMeta = deferred()
    const newMeta = deferred()
    apiMock.gpmHeatmapUploadMeta
      .mockReturnValueOnce(oldMeta.promise)
      .mockReturnValueOnce(newMeta.promise)
    const store = useGpmBatchStore()

    const oldRoute = store.applyRoute({ branchTag: 'main', sceneId: 'OldScene' })
    const newRoute = store.applyRoute({ branchTag: 'main', sceneId: 'Village_Dimension_Main' })
    newMeta.resolve(meta)
    await newRoute
    oldMeta.resolve({ ...meta, scene_ids: ['OldScene'] })
    await oldRoute

    expect(store.filters.sceneId).toBe('Village_Dimension_Main')
    expect(apiMock.gpmHeatmapUploads).toHaveBeenCalledTimes(1)
  })
})
