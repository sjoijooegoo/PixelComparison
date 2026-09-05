import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const apiMock = vi.hoisted(() => ({
  gpmHeatmapCatalog: vi.fn(),
  gpmHeatmapUploads: vi.fn(),
  deleteGpmHeatmapUpload: vi.fn(),
}))

vi.mock('../api', () => ({ api: apiMock }))

import { useGpmBatchStore } from './gpmBatchStore'

const heatmapMeta = {
  branch_tags: ['engine-ue5', 'main'],
  platforms: ['Android'],
  maps: [
    { id: 0, value: 'Configured_Without_Data' },
    { id: 1, value: 'Village_Dimension_Main' },
  ],
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
  apiMock.gpmHeatmapCatalog.mockResolvedValue(heatmapMeta)
  apiMock.gpmHeatmapUploads.mockResolvedValue({ items: [{ id: 1 }], total: 1 })
  apiMock.deleteGpmHeatmapUpload.mockResolvedValue({ deleted: true })
})

describe('GPM batch catalog store', () => {
  it('接受服务器定位页码，窗口改变每页数量后继续定位，手动翻页解除定位', async () => {
    const store = useGpmBatchStore()
    apiMock.gpmHeatmapUploads.mockResolvedValue({
      items: [{ batch_id: 'source' }], total: 40, page: 3, located_batch_id: 'source',
    })
    const state = await store.applyRoute({ branchTag: 'main', focusBatchId: 'source', page: 1 })
    expect(apiMock.gpmHeatmapUploads).toHaveBeenCalledWith(expect.objectContaining({ locate_batch_id: 'source' }))
    expect(state).toMatchObject({ page: 3, focusBatchId: 'source' })
    store.batchPageSize = 5
    apiMock.gpmHeatmapUploads.mockResolvedValue({ items: [{ batch_id: 'source' }], total: 40, page: 6, located_batch_id: 'source' })
    await store.loadBatches()
    expect(store.batchPage).toBe(6)
    expect(apiMock.gpmHeatmapUploads).toHaveBeenLastCalledWith(expect.objectContaining({ page_size: 5, locate_batch_id: 'source' }))
    apiMock.gpmHeatmapUploads.mockResolvedValue({ items: [], total: 40, page: 7 })
    await store.applyRoute({ branchTag: 'main', page: 7 })
    expect(store.focusBatchId).toBe('')
    expect(apiMock.gpmHeatmapUploads.mock.lastCall[0]).not.toHaveProperty('locate_batch_id')
    expect(store.batchPage).toBe(7)
  })

  it('来源消失时清除定位并提示，仍保留正常批次列表', async () => {
    const store = useGpmBatchStore()
    apiMock.gpmHeatmapUploads.mockResolvedValue({ items: [{ batch_id: 'other' }], total: 1, page: 1, located_batch_id: null })
    const state = await store.applyRoute({ branchTag: 'main', focusBatchId: 'deleted' })
    expect(state.focusBatchId).toBe('')
    expect(store.locationMessage).toContain('来源批次 deleted')
    expect(store.batches).toEqual([{ batch_id: 'other' }])
    expect(store.error).toBe('')
  })

  it('新路由等待元数据期间，旧定位请求不得覆盖当前状态', async () => {
    const store = useGpmBatchStore()
    const oldPage = deferred()
    apiMock.gpmHeatmapUploads.mockReturnValueOnce(oldPage.promise)
    store.focusBatchId = 'old'
    const oldLoad = store.loadBatches()
    const meta = deferred()
    apiMock.gpmHeatmapCatalog.mockReturnValueOnce(meta.promise)
    const newRoute = store.applyRoute({ branchTag: 'main', focusBatchId: 'new' })
    oldPage.resolve({ items: [], page: 9, located_batch_id: null })
    await oldLoad
    expect(store.locationMessage).toBe('')
    expect(store.batchPage).toBe(1)
    apiMock.gpmHeatmapUploads.mockResolvedValue({ items: [{ batch_id: 'new' }], page: 2, located_batch_id: 'new' })
    meta.resolve(heatmapMeta)
    await newRoute
    expect(store.focusBatchId).toBe('new')
    expect(store.batchPage).toBe(2)
  })
  it('按路由规范化筛选并读取独立批次目录', async () => {
    const store = useGpmBatchStore()
    const state = await store.applyRoute({
      returnTo: '/gpm-heatmap/Village_Dimension_Main',
      branchTag: 'engine-ue5', platform: 'Android', mapName: 'Village_Dimension_Main',
      shadingQuality: 5, capturedFrom: '2026-08-01', capturedTo: '2026-08-28', page: 2,
    })

    expect(apiMock.gpmHeatmapUploads).toHaveBeenCalledWith({
      branch_tag: 'engine-ue5', platform: 'Android', map_name: 'Village_Dimension_Main',
      shading_quality: 5, captured_from: '2026-08-01', captured_to: '2026-08-28',
      page: 2, page_size: 10,
    })
    expect(state).toMatchObject({
      returnTo: '/gpm-heatmap/Village_Dimension_Main', branchTag: 'engine-ue5', page: 2,
    })
  })

  it('与热力图工作区共享地图、平台和规范画质选项', async () => {
    const store = useGpmBatchStore()

    await store.applyRoute({ branchTag: 'main' })

    expect(store.meta).toEqual({
      branch_tags: ['engine-ue5', 'main'],
      platforms: ['IOS', 'Android', 'Windows'],
      maps: ['Configured_Without_Data', 'Village_Dimension_Main'],
      shading_qualities: [
        { value: 5, label: '电影' },
        { value: 4, label: '极致' },
        { value: 3, label: '精美' },
        { value: 2, label: '均衡' },
        { value: 1, label: '流畅' },
        { value: 0, label: '节能' },
      ],
    })
    expect(apiMock.gpmHeatmapCatalog).toHaveBeenCalledWith({ branch_tag: 'main' })
  })

  it('保留规范平台和画质，但不允许未知场景污染目录请求', async () => {
    const store = useGpmBatchStore()
    await store.applyRoute({
      branchTag: 'main', platform: 'Windows', mapName: 'Missing', shadingQuality: 2,
      capturedFrom: '2026-08-01', capturedTo: '2026-08-28', page: 1,
    })

    expect(store.filters).toMatchObject({
      branchTag: 'main', platform: 'Windows', mapName: '', shadingQuality: 2,
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
    apiMock.gpmHeatmapCatalog
      .mockReturnValueOnce(oldMeta.promise)
      .mockReturnValueOnce(newMeta.promise)
    const store = useGpmBatchStore()

    const oldRoute = store.applyRoute({ branchTag: 'main', mapName: 'OldScene' })
    const newRoute = store.applyRoute({ branchTag: 'main', mapName: 'Village_Dimension_Main' })
    newMeta.resolve(heatmapMeta)
    await newRoute
    oldMeta.resolve(heatmapMeta)
    await oldRoute

    expect(store.filters.mapName).toBe('Village_Dimension_Main')
    expect(apiMock.gpmHeatmapUploads).toHaveBeenCalledTimes(1)
  })
})
