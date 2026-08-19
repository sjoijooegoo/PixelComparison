import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const apiMock = vi.hoisted(() => ({
  batches: vi.fn(),
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
  const project = useProjectStore()
  project.meta = { ...project.meta, branch_tags: ['main', 'engine-ue5'] }
  project.settings = {
    ...project.settings,
    default_shading_quality: 5,
    default_date_range_days: 7,
  }
})

describe('batch catalog requests', () => {
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
})
