import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

const { apiMock, routerMock, loggerMock } = vi.hoisted(() => ({
  apiMock: {
    meta: vi.fn(),
    settings: vi.fn(),
    batches: vi.fn(),
    sceneGrid: vi.fn(),
    comparisonLookup: vi.fn(),
    comparisonTask: vi.fn(),
    createComparison: vi.fn(),
  },
  routerMock: { push: vi.fn(), replace: vi.fn() },
  loggerMock: { info: vi.fn(), warn: vi.fn(), error: vi.fn() },
}))

vi.mock('./api', () => ({ api: apiMock }))
vi.mock('./router', () => ({ router: routerMock }))
vi.mock('./logger', () => ({ logger: loggerMock }))

import { p4Label, useStore, visibleQualityOptions } from './store'

beforeEach(() => {
  setActivePinia(createPinia())
  vi.resetAllMocks()
  const cacheState = globalThis.__PIXELCOMP_GRID_CACHE__
  cacheState.cache.clear()
  cacheState.inflight.clear()
  cacheState.epoch += 1
  apiMock.meta.mockResolvedValue({ scene_ids: [], platforms: [], baselines: [] })
  apiMock.settings.mockResolvedValue({
    default_shading_quality: 5,
    default_date_range_days: 30,
    filter_shading_qualities: [5, 4, 3, 2, 1, 0],
  })
  apiMock.batches.mockResolvedValue({ items: [], total: 0 })
  apiMock.sceneGrid.mockResolvedValue({ scene_id: '', batches: [], rows: [] })
})

afterEach(() => vi.useRealTimers())

function deferred() {
  let resolve
  let reject
  const promise = new Promise((res, rej) => {
    resolve = res
    reject = rej
  })
  return { promise, resolve, reject }
}

describe('display helpers', () => {
  it('按项目设置筛选画质并在空集合时回退全部档位', () => {
    expect(visibleQualityOptions({ filter_shading_qualities: [5, 3, 1] }).map((x) => x.value))
      .toEqual([5, 3, 1])
    expect(visibleQualityOptions({ filter_shading_qualities: [] })).toHaveLength(6)
  })

  it('统一格式化缺失和有效的 P4 版本', () => {
    expect(p4Label(null)).toBe('——')
    expect(p4Label('')).toBe('——')
    expect(p4Label(251200)).toBe('P4 251200')
  })
})

describe('batch initialization and request ordering', () => {
  it('深链初始化只使用项目设置下的最终场景筛选', async () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date(2026, 6, 13, 12, 0, 0))
    const store = useStore()
    apiMock.batches.mockResolvedValue({ items: [{ id: '10' }], total: 10 })
    apiMock.sceneGrid.mockResolvedValue({
      scene_id: 'Village_Dimension_Main',
      batches: [{ id: '10', scene_id: 'Village_Dimension_Main' }],
      rows: [],
    })

    await store.init('Village_Dimension_Main')

    expect(store.initialized).toBe(true)
    expect(store.batchView).toBe('grid')
    expect(store.filters.scene_id).toBe('Village_Dimension_Main')
    expect(store.batchTotal).toBe(10)
    expect(apiMock.batches).toHaveBeenCalledTimes(1)
    expect(apiMock.batches.mock.calls[0][0]).toMatchObject({
      scene_id: 'Village_Dimension_Main',
      shading_quality: 5,
      created_from: '2026-06-13',
      created_to: '2026-07-13',
      page: 1,
      page_size: 10,
    })
    expect(apiMock.sceneGrid).toHaveBeenCalledTimes(1)
    expect(apiMock.sceneGrid.mock.calls[0]).toEqual([
      'Village_Dimension_Main',
      expect.objectContaining({
        scene_id: 'Village_Dimension_Main',
        shading_quality: 5,
        created_from: '2026-06-13',
        created_to: '2026-07-13',
      }),
    ])
  })

  it('忽略晚到的旧筛选批次响应', async () => {
    const store = useStore()
    const oldRequest = deferred()
    const currentRequest = deferred()
    apiMock.batches
      .mockImplementationOnce(() => oldRequest.promise)
      .mockImplementationOnce(() => currentRequest.promise)

    store.filters.scene_id = ''
    const oldLoad = store.loadBatches()
    store.filters.scene_id = 'Village_Dimension_Main'
    const currentLoad = store.loadBatches()

    currentRequest.resolve({ items: [{ id: 'scene-10' }], total: 10 })
    await currentLoad
    oldRequest.resolve({ items: [{ id: 'global-120' }], total: 120 })
    await oldLoad

    expect(apiMock.batches.mock.calls[0][0].scene_id).toBe('')
    expect(apiMock.batches.mock.calls[1][0].scene_id).toBe('Village_Dimension_Main')
    expect(store.batches).toEqual([{ id: 'scene-10' }])
    expect(store.batchTotal).toBe(10)
  })

  it('动态页大小变化后只接受最新分页响应', async () => {
    const store = useStore()
    const page10 = deferred()
    const page8 = deferred()
    apiMock.batches
      .mockImplementationOnce(() => page10.promise)
      .mockImplementationOnce(() => page8.promise)

    store.batchPageSize = 10
    const oldLoad = store.loadBatches()
    store.batchPageSize = 8
    const currentLoad = store.loadBatches()
    page8.resolve({ items: [{ id: 'page-8' }], total: 10 })
    await currentLoad
    page10.resolve({ items: [{ id: 'page-10' }], total: 120 })
    await oldLoad

    expect(apiMock.batches.mock.calls.map(([params]) => params.page_size)).toEqual([10, 8])
    expect(store.batches).toEqual([{ id: 'page-8' }])
    expect(store.batchTotal).toBe(10)
  })

  it('空日期选择立即清空并使在途批次响应失效', async () => {
    const store = useStore()
    const oldRequest = deferred()
    apiMock.batches.mockImplementationOnce(() => oldRequest.promise)

    const oldLoad = store.loadBatches()
    store.filters.dateMode = 'days'
    store.filters.created_dates = []
    await store.loadBatches()
    oldRequest.resolve({ items: [{ id: 'stale' }], total: 120 })
    await oldLoad

    expect(store.batches).toEqual([])
    expect(store.batchTotal).toBe(0)
  })

  it('快速切换场景时忽略晚到的旧列表图响应', async () => {
    const store = useStore()
    const sceneA = deferred()
    const sceneB = deferred()
    apiMock.sceneGrid
      .mockImplementationOnce(() => sceneA.promise)
      .mockImplementationOnce(() => sceneB.promise)

    store.filters.scene_id = 'SceneA'
    const oldLoad = store.loadGrid()
    store.filters.scene_id = 'SceneB'
    const currentLoad = store.loadGrid()
    sceneB.resolve({ scene_id: 'SceneB', batches: [{ id: 'B' }], rows: [] })
    await currentLoad
    sceneA.resolve({ scene_id: 'SceneA', batches: [{ id: 'A' }], rows: [] })
    await oldLoad

    expect(store.grid.scene_id).toBe('SceneB')
    expect(store.grid.batches).toEqual([{ id: 'B' }])
  })

  it('刷新后旧列表图请求不会重新污染缓存', async () => {
    const store = useStore()
    const oldRequest = deferred()
    const freshRequest = deferred()
    apiMock.sceneGrid
      .mockImplementationOnce(() => oldRequest.promise)
      .mockImplementationOnce(() => freshRequest.promise)
    store.filters.scene_id = 'CacheScene'
    store.batchView = 'grid'

    const oldLoad = store.loadGrid()
    const refresh = store.refreshBatches()
    await vi.waitFor(() => expect(apiMock.sceneGrid).toHaveBeenCalledTimes(2))
    freshRequest.resolve({ scene_id: 'CacheScene', batches: [{ id: 'fresh' }], rows: [] })
    await refresh
    oldRequest.resolve({ scene_id: 'CacheScene', batches: [{ id: 'stale' }], rows: [] })
    await oldLoad
    await store.loadGrid()

    expect(apiMock.sceneGrid).toHaveBeenCalledTimes(2)
    expect(store.grid.batches).toEqual([{ id: 'fresh' }])
  })
})

describe('comparison orientation', () => {
  it('换向时交换图片、直方图和新增/缺失状态', () => {
    const store = useStore()
    store.detail = {
      id: 7,
      status: 'added',
      current_url: '/images/current.png',
      baseline_url: '/images/baseline.png',
      metrics: { hist_current: [1], hist_baseline: [2], ssim: 0.9 },
    }
    store.flip = true

    expect(store.orientedDetail).toMatchObject({
      id: 7,
      status: 'missing',
      current_url: '/images/baseline.png',
      baseline_url: '/images/current.png',
      metrics: { hist_current: [2], hist_baseline: [1], ssim: 0.9 },
    })
  })

  it('同一批次切换角色时清除另一侧并保存场景记忆', () => {
    const store = useStore()
    const batch = { id: '10', scene_id: 'SceneA' }

    store.setRole(batch, 'baseline')
    store.setRole(batch, 'current')

    expect(store.baselineBatch).toBeNull()
    expect(store.currentBatch).toEqual(batch)
    expect(store.rolesByScene.SceneA).toEqual({ baseline: null, current: batch })
  })
})

describe('comparison polling', () => {
  it('轮询后台任务并返回完成结果', async () => {
    vi.useFakeTimers()
    const store = useStore()
    apiMock.createComparison.mockResolvedValue({ task_id: 'task-1', status: 'running', flip: true })
    apiMock.comparisonTask.mockResolvedValue({
      status: 'done',
      done: 3,
      total: 3,
      comparison: { id: 42 },
    })

    const resultPromise = store._awaitComparison({ batch_id: '2', ref_batch_id: '1' })
    await vi.advanceTimersByTimeAsync(400)

    await expect(resultPromise).resolves.toEqual({ comparison: { id: 42 }, flip: true })
    expect(store.progress).toEqual({ done: 3, total: 3 })
    vi.useRealTimers()
  })

  it('忽略已经过期的热力图 lookup 响应', async () => {
    const store = useStore()
    const current = { id: '2', scene_id: 'SceneA' }
    const baseline = { id: '1', scene_id: 'SceneA' }
    store.grid = { batches: [current, baseline], rows: [] }
    store.currentBatch = current
    store.baselineBatch = baseline

    let finishLookup
    apiMock.comparisonLookup.mockReturnValue(new Promise((resolve) => { finishLookup = resolve }))
    const pending = store.loadGridHeatmaps()
    store.currentBatch = { id: '3', scene_id: 'SceneA' }
    finishLookup({ exists: true, heatmaps: { shot: '/images/heat.webp' } })
    await pending

    expect(store.gridHeatmaps).toBeNull()
  })
})
