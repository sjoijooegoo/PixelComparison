import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const apiMock = vi.hoisted(() => ({
  batches: vi.fn(),
  sceneAvailability: vi.fn(),
  deleteBatch: vi.fn(),
  meta: vi.fn(),
  settings: vi.fn(),
  saveSettings: vi.fn(),
}))

vi.mock('../api', () => ({ api: apiMock }))

import { useBatchCatalogStore } from './batchCatalogStore'
import { useProjectStore } from './projectStore'

function deferred() {
  let resolve
  const promise = new Promise((res) => { resolve = res })
  return { promise, resolve }
}

beforeEach(() => {
  setActivePinia(createPinia())
  vi.clearAllMocks()
  apiMock.sceneAvailability.mockResolvedValue({ scene_ids: [] })
  const project = useProjectStore()
  project.meta = {
    ...project.meta,
    branch_tags: ['main', 'engine-ue5'],
    scene_ids: ['SceneA', 'SceneB'],
  }
  project.settings = {
    ...project.settings,
    default_shading_quality: 5,
    default_date_range_days: 7,
  }
})

describe('batch catalog requests', () => {
  it('无查询参数时默认 main、全部场景和全部画质', async () => {
    apiMock.batches.mockResolvedValue({ items: [], total: 0 })
    const store = useBatchCatalogStore()

    const normalized = await store.applyRoute({})

    expect(store.filters).toMatchObject({
      branch_tag: 'main',
      scene_id: '',
      shading_quality: '',
      dateMode: 'range',
    })
    expect(store.batchPage).toBe(1)
    expect(apiMock.batches).toHaveBeenCalledWith(expect.objectContaining({
      branch_tag: 'main',
      scene_id: '',
      shading_quality: '',
      page: 1,
    }))
    expect(normalized).toMatchObject({
      branchTag: 'main', sceneId: '', shadingQuality: '', page: 1,
    })
  })

  it('从路由恢复分支、场景、画质、指定日期和页码', async () => {
    apiMock.batches.mockResolvedValue({ items: [], total: 0 })
    const store = useBatchCatalogStore()

    const normalized = await store.applyRoute({
      branchTag: 'engine-ue5',
      sceneId: 'SceneB',
      shadingQuality: '3',
      dateMode: 'days',
      createdDates: ['2026-08-03', 'bad-date', '2026-08-01', '2026-08-03'],
      page: '2',
    })

    expect(store.filters).toMatchObject({
      branch_tag: 'engine-ue5',
      scene_id: 'SceneB',
      shading_quality: 3,
      dateMode: 'days',
      created_dates: ['2026-08-01', '2026-08-03'],
    })
    expect(store.batchPage).toBe(2)
    expect(apiMock.batches).toHaveBeenCalledWith(expect.objectContaining({
      branch_tag: 'engine-ue5',
      scene_id: 'SceneB',
      shading_quality: 3,
      created_dates: ['2026-08-01', '2026-08-03'],
      page: 2,
    }))
    expect(normalized.page).toBe(2)
  })

  it('快速切换路由时旧响应不能覆盖最新筛选', async () => {
    const oldRequest = deferred()
    const newRequest = deferred()
    apiMock.batches
      .mockReturnValueOnce(oldRequest.promise)
      .mockReturnValueOnce(newRequest.promise)
    const store = useBatchCatalogStore()

    const oldApply = store.applyRoute({ sceneId: 'SceneA' })
    const newApply = store.applyRoute({ sceneId: 'SceneB' })
    newRequest.resolve({ items: [{ id: 'new' }], total: 1 })
    await newApply
    oldRequest.resolve({ items: [{ id: 'old' }], total: 1 })

    await expect(oldApply).resolves.toBeNull()
    expect(store.filters.scene_id).toBe('SceneB')
    expect(store.batches).toEqual([{ id: 'new' }])
  })

  it('动态页大小变化后只接受最新分页响应', async () => {
    const oldRequest = deferred()
    const newRequest = deferred()
    apiMock.batches
      .mockReturnValueOnce(oldRequest.promise)
      .mockReturnValueOnce(newRequest.promise)
    const store = useBatchCatalogStore()

    store.batchPageSize = 10
    const oldLoad = store.loadBatches()
    store.batchPageSize = 20
    const newLoad = store.loadBatches()
    newRequest.resolve({ items: [{ id: 'new' }], total: 1 })
    await newLoad
    oldRequest.resolve({ items: [{ id: 'old' }], total: 1 })
    await oldLoad

    expect(store.batches).toEqual([{ id: 'new' }])
    expect(apiMock.batches.mock.calls[1][0].page_size).toBe(20)
  })

  it('空的指定日期立即清空目录且不请求全部历史', async () => {
    const store = useBatchCatalogStore()
    store.batches = [{ id: 'existing' }]
    store.batchTotal = 1
    store.filters.dateMode = 'days'
    store.filters.created_dates = []

    await store.loadBatches()

    expect(store.batches).toEqual([])
    expect(store.batchTotal).toBe(0)
    expect(apiMock.batches).not.toHaveBeenCalled()
  })

  it('场景可用性应用除场景自身外的画质和日期筛选', async () => {
    const store = useBatchCatalogStore()
    store.filters = {
      branch_tag: 'engine-ue5',
      scene_id: 'SceneA',
      shading_quality: 3,
      dateMode: 'range',
      created_from: '2026-08-01',
      created_to: '2026-08-07',
      created_dates: [],
    }
    apiMock.sceneAvailability.mockResolvedValue({ scene_ids: ['SceneB'] })

    await store.loadSceneAvailability()

    expect(store.availableSceneIds).toEqual(['SceneB'])
    expect(apiMock.sceneAvailability).toHaveBeenCalledWith({
      capability: 'batches',
      branch_tag: 'engine-ue5',
      shading_quality: 3,
      created_from: '2026-08-01',
      created_to: '2026-08-07',
    }, { signal: expect.any(AbortSignal) })
  })

  it('快速切换筛选时旧场景可用性响应不能覆盖新状态', async () => {
    const oldRequest = deferred()
    const newRequest = deferred()
    apiMock.sceneAvailability
      .mockReturnValueOnce(oldRequest.promise)
      .mockReturnValueOnce(newRequest.promise)
    const store = useBatchCatalogStore()

    store.filters.shading_quality = 5
    const oldLoad = store.loadSceneAvailability()
    store.filters.shading_quality = 3
    const newLoad = store.loadSceneAvailability()
    newRequest.resolve({ scene_ids: ['NewScene'] })
    await newLoad
    oldRequest.resolve({ scene_ids: ['OldScene'] })
    await oldLoad

    expect(store.availableSceneIds).toEqual(['NewScene'])
    expect(apiMock.sceneAvailability.mock.calls[0][1].signal.aborted).toBe(true)
  })
})
