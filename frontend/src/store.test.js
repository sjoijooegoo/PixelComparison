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
    comparisons: vi.fn(),
    scenes: vi.fn(),
    item: vi.fn(),
  },
  routerMock: { push: vi.fn(), replace: vi.fn() },
  loggerMock: { info: vi.fn(), warn: vi.fn(), error: vi.fn() },
}))

vi.mock('./api', () => ({
  api: apiMock,
  isRequestCancelled: (error) => error?.code === 'ABORTED' || error?.cancelled === true,
}))
vi.mock('./router', () => ({ router: routerMock }))
vi.mock('./logger', () => ({ logger: loggerMock }))

import {
  inclusiveDateRangeDays,
  isDateRangeAllowed,
  normalizeDateRangeDays,
  p4Label,
  useStore,
  visibleQualityOptions,
} from './store'

beforeEach(() => {
  setActivePinia(createPinia())
  vi.resetAllMocks()
  const cacheState = globalThis.__PIXELCOMP_GRID_CACHE__
  cacheState.cache.clear()
  cacheState.inflight.clear()
  cacheState.epoch += 1
  apiMock.meta.mockResolvedValue({ branch_tags: ['main'], scene_ids: [], platforms: [], baselines: [] })
  apiMock.settings.mockResolvedValue({
    default_shading_quality: 5,
    default_date_range_days: 30,
    filter_shading_qualities: [5, 4, 3, 2, 1, 0],
  })
  apiMock.batches.mockResolvedValue({ items: [], total: 0 })
  apiMock.sceneGrid.mockResolvedValue({ scene_id: '', batches: [], rows: [] })
  apiMock.comparisons.mockResolvedValue({ items: [], total: 0 })
  apiMock.scenes.mockResolvedValue({
    items: [], total: 0,
    counts: { all: 0, fail: 0, warn: 0, pass: 0, added: 0, missing: 0 },
  })
  apiMock.item.mockResolvedValue({ id: 1, name: 'Scene1' })
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

  it('连续日期范围最多允许14个首尾均计入的自然日', () => {
    expect(inclusiveDateRangeDays('2026-07-01', '2026-07-14')).toBe(14)
    expect(inclusiveDateRangeDays('2026-07-01', '2026-07-15')).toBe(15)
    expect(isDateRangeAllowed('2026-07-01', '2026-07-14')).toBe(true)
    expect(isDateRangeAllowed('2026-07-01', '2026-07-15')).toBe(false)
    expect(normalizeDateRangeDays(30)).toBe(14)
  })
})

describe('batch initialization and request ordering', () => {
  it('从路由恢复分支，并把分支带入首屏批次与列表图请求', async () => {
    const store = useStore()
    apiMock.meta.mockResolvedValue({
      branch_tags: ['main', 'engine-ue5'],
      scene_ids: ['BranchScene'],
      platforms: [],
      baselines: [],
    })

    await store.init('BranchScene', 'engine-ue5')

    expect(store.filters.branch_tag).toBe('engine-ue5')
    expect(apiMock.batches).toHaveBeenCalledWith(expect.objectContaining({
      branch_tag: 'engine-ue5',
      scene_id: 'BranchScene',
    }))
    expect(apiMock.sceneGrid).toHaveBeenCalledWith(
      'BranchScene',
      expect.objectContaining({ branch_tag: 'engine-ue5' }),
    )
  })

  it('切换分支保留场景、清空角色和分页，并重新加载当前视图', async () => {
    const store = useStore()
    store.meta.branch_tags = ['main', 'engine-ue5']
    store.filters.scene_id = 'BranchScene'
    store.batchView = 'grid'
    store.batchPage = 3
    store.currentBatch = { id: '10', scene_id: 'BranchScene', branch_tag: 'main' }
    store.baselineBatch = { id: '9', scene_id: 'BranchScene', branch_tag: 'main' }

    await store.changeBranch('engine-ue5')

    expect(store.filters.scene_id).toBe('BranchScene')
    expect(store.filters.branch_tag).toBe('engine-ue5')
    expect(store.batchPage).toBe(1)
    expect(store.currentBatch).toBeNull()
    expect(store.baselineBatch).toBeNull()
    expect(apiMock.batches).toHaveBeenCalledWith(expect.objectContaining({ branch_tag: 'engine-ue5' }))
    expect(apiMock.sceneGrid).toHaveBeenCalledWith(
      'BranchScene',
      expect.objectContaining({ branch_tag: 'engine-ue5' }),
    )
  })

  it('不存在的分支深链回退 main，避免下拉框进入无选项状态', async () => {
    const store = useStore()
    apiMock.meta.mockResolvedValue({
      branch_tags: ['main', 'engine-ue5'], scene_ids: [], platforms: [], baselines: [],
    })

    await store.init('', 'missing-branch')
    await store.changeBranch('still-missing')

    expect(store.filters.branch_tag).toBe('main')
    expect(apiMock.batches).toHaveBeenLastCalledWith(expect.objectContaining({ branch_tag: 'main' }))
  })

  it('深链初始化只使用项目设置下的最终场景筛选', async () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date(2026, 6, 13, 12, 0, 0))
    const store = useStore()
    apiMock.meta.mockResolvedValue({
      scene_ids: ['Village_Dimension_Main'],
      unlisted_scene_ids: [],
      platforms: [],
      baselines: [],
    })
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
      created_from: '2026-06-30',
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
        created_from: '2026-06-30',
        created_to: '2026-07-13',
      }),
    ])
  })

  it('并发初始化复用同一轮请求，失败后可以重试', async () => {
    const store = useStore()
    const meta = deferred()
    apiMock.meta.mockReturnValueOnce(meta.promise)

    const first = store.init('Village_Dimension_Main')
    const duplicate = store.init('Village_Dimension_Main')
    expect(store.initializing).toBe(true)
    expect(apiMock.meta).toHaveBeenCalledTimes(1)
    expect(apiMock.settings).toHaveBeenCalledTimes(1)

    meta.reject(new Error('网络不可用'))
    await expect(first).rejects.toThrow('网络不可用')
    await expect(duplicate).rejects.toThrow('网络不可用')
    expect(store.initializing).toBe(false)
    expect(store.initialized).toBe(false)
    expect(store.initError).toContain('网络不可用')

    apiMock.meta.mockResolvedValue({ scene_ids: [], platforms: [], baselines: [] })
    await store.init('')

    expect(apiMock.meta).toHaveBeenCalledTimes(2)
    expect(store.initialized).toBe(true)
    expect(store.initError).toBe('')
  })

  it('深链场景不在权威目录时回退到未选择场景的列表', async () => {
    const store = useStore()
    apiMock.meta.mockResolvedValue({
      scene_ids: ['VisibleScene'],
      unlisted_scene_ids: ['HiddenScene'],
      scene_catalog_configured: true,
      platforms: [],
      baselines: [],
    })

    await store.init('HiddenScene')

    expect(store.initialized).toBe(true)
    expect(store.batchView).toBe('list')
    expect(store.filters.scene_id).toBe('')
    expect(apiMock.batches).toHaveBeenCalledTimes(1)
    expect(apiMock.batches.mock.calls[0][0].scene_id).toBe('')
    expect(apiMock.sceneGrid).not.toHaveBeenCalled()
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

  it('批次或列表图加载失败时保存错误，重试成功后清除', async () => {
    const store = useStore()
    const timeout = Object.assign(new Error('请求超时（30 秒），请重试'), {
      code: 'TIMEOUT', retryable: true,
    })

    apiMock.batches.mockRejectedValueOnce(timeout)
    await expect(store.loadBatches()).rejects.toThrow('请求超时')
    expect(store.batchLoading).toBe(false)
    expect(store.batchError).toContain('请求超时')

    apiMock.batches.mockResolvedValueOnce({ items: [{ id: 'ok' }], total: 1 })
    await store.loadBatches()
    expect(store.batchError).toBe('')
    expect(store.batches).toEqual([{ id: 'ok' }])

    store.filters.scene_id = 'SceneA'
    apiMock.sceneGrid.mockRejectedValueOnce(timeout)
    await expect(store.loadGrid()).rejects.toThrow('请求超时')
    expect(store.gridLoading).toBe(false)
    expect(store.gridError).toContain('请求超时')

    apiMock.sceneGrid.mockResolvedValueOnce({ scene_id: 'SceneA', batches: [], rows: [] })
    await store.loadGrid()
    expect(store.gridError).toBe('')
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
    apiMock.meta.mockResolvedValue({
      scene_ids: ['CacheScene'],
      unlisted_scene_ids: [],
      platforms: [],
      baselines: [],
    })

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

  it('目录刷新隐藏当前场景时清空筛选并返回被隐藏的场景ID', async () => {
    const store = useStore()
    store.filters.scene_id = 'HiddenScene'
    store.batchView = 'grid'
    store.grid = { scene_id: 'HiddenScene', batches: [{ id: 'old' }], rows: [] }
    apiMock.meta.mockResolvedValue({
      scene_ids: ['VisibleScene'],
      unlisted_scene_ids: ['HiddenScene'],
      scene_catalog_configured: true,
      platforms: [],
      baselines: [],
    })

    const hiddenSceneId = await store.refreshBatches()

    expect(hiddenSceneId).toBe('HiddenScene')
    expect(store.filters.scene_id).toBe('')
    expect(store.batchView).toBe('list')
    expect(store.grid.batches).toEqual([])
    expect(apiMock.batches.mock.calls[0][0].scene_id).toBe('')
    expect(apiMock.sceneGrid).not.toHaveBeenCalled()
  })
})

describe('comparison orientation', () => {
  it('切换对比分支只加载该分支并清空旧选择', async () => {
    const store = useStore()
    store.meta.branch_tags = ['main', 'engine-ue5']
    store.selectedComparison = { id: 1, branch_tag: 'main' }
    apiMock.comparisons.mockResolvedValue({ items: [], total: 0 })

    await store.changeComparisonBranch('engine-ue5')

    expect(store.filters.branch_tag).toBe('engine-ue5')
    expect(store.selectedComparison).toBeNull()
    expect(apiMock.comparisons).toHaveBeenCalledWith(
      { branch_tag: 'engine-ue5' },
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    )
  })

  it('快速切换对比分支时取消旧请求且过期响应不能覆盖当前分支', async () => {
    const store = useStore()
    const mainRequest = deferred()
    const engineRequest = deferred()
    apiMock.comparisons
      .mockImplementationOnce(() => mainRequest.promise)
      .mockImplementationOnce(() => engineRequest.promise)

    store.filters.branch_tag = 'main'
    const oldLoad = store.loadComparisons()
    const oldSignal = apiMock.comparisons.mock.calls[0][1].signal
    store.filters.branch_tag = 'engine-ue5'
    const currentLoad = store.loadComparisons()

    expect(oldSignal.aborted).toBe(true)
    engineRequest.resolve({ items: [{ id: 2, branch_tag: 'engine-ue5' }] })
    await currentLoad
    mainRequest.resolve({ items: [{ id: 1, branch_tag: 'main' }] })
    await oldLoad

    expect(store.comparisons).toEqual([{ id: 2, branch_tag: 'engine-ue5' }])
  })

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
    expect(store.rolesByScene['main\u0000SceneA']).toEqual({ baseline: null, current: batch })
  })

  it('无截图批次不能成为对比角色，跨分支选择也不能发起对比', () => {
    const store = useStore()
    const buildOnly = {
      id: 'build', scene_id: 'SceneA', branch_tag: 'engine-ue5', has_screenshots: false,
    }
    store.setRole(buildOnly, 'current')
    expect(store.currentBatch).toBeNull()

    store.currentBatch = {
      id: '2', scene_id: 'SceneA', branch_tag: 'engine-ue5', has_screenshots: true,
    }
    store.baselineBatch = {
      id: '1', scene_id: 'SceneA', branch_tag: 'main', has_screenshots: true,
    }
    expect(store.canCompare).toBe(false)
  })
})

describe('comparison data request coordination', () => {
  it('场景列表相同参数复用请求，参数变化时取消旧请求且只写入最新结果', async () => {
    const store = useStore()
    const oldRequest = deferred()
    const currentRequest = deferred()
    apiMock.scenes
      .mockImplementationOnce(() => oldRequest.promise)
      .mockImplementationOnce(() => currentRequest.promise)
    store.selectedComparison = { id: 42 }

    const oldLoad = store.loadScenes()
    const duplicate = store.loadScenes()
    expect(apiMock.scenes).toHaveBeenCalledTimes(1)
    const oldSignal = apiMock.scenes.mock.calls[0][2].signal

    store.sceneSearch = 'latest'
    const currentLoad = store.loadScenes()
    expect(apiMock.scenes).toHaveBeenCalledTimes(2)
    expect(oldSignal.aborted).toBe(true)

    currentRequest.resolve({
      items: [{ id: 2, name: 'latest' }], total: 1,
      counts: { all: 1, fail: 0, warn: 0, pass: 1, added: 0, missing: 0 },
    })
    await currentLoad
    oldRequest.resolve({
      items: [{ id: 1, name: 'stale' }], total: 99,
      counts: { all: 99, fail: 99, warn: 0, pass: 0, added: 0, missing: 0 },
    })
    await Promise.all([oldLoad, duplicate])

    expect(store.scenes).toEqual([{ id: 2, name: 'latest' }])
    expect(store.sceneTotal).toBe(1)
    expect(store.loading).toBe(false)
  })

  it('详情相同检查点复用请求，快速切换时取消旧请求并阻止旧详情回写', async () => {
    const store = useStore()
    const oldRequest = deferred()
    const currentRequest = deferred()
    apiMock.item
      .mockImplementationOnce(() => oldRequest.promise)
      .mockImplementationOnce(() => currentRequest.promise)

    const oldLoad = store.selectScene(1)
    const duplicate = store.selectScene(1)
    expect(apiMock.item).toHaveBeenCalledTimes(1)
    const oldSignal = apiMock.item.mock.calls[0][1].signal

    const currentLoad = store.selectScene(2)
    expect(apiMock.item).toHaveBeenCalledTimes(2)
    expect(oldSignal.aborted).toBe(true)

    currentRequest.resolve({ id: 2, name: 'latest' })
    await currentLoad
    oldRequest.resolve({ id: 1, name: 'stale' })
    await Promise.all([oldLoad, duplicate])

    expect(store.selectedSceneItemId).toBe(2)
    expect(store.detail).toEqual({ id: 2, name: 'latest' })
    expect(store.detailLoading).toBe(false)
  })

  it('热力图相同批次对复用查询，换批次后取消旧查询并只保留最新映射', async () => {
    const store = useStore()
    const oldRequest = deferred()
    const currentRequest = deferred()
    apiMock.comparisonLookup
      .mockImplementationOnce(() => oldRequest.promise)
      .mockImplementationOnce(() => currentRequest.promise)
    const baseline = { id: '1', scene_id: 'SceneA' }
    const oldCurrent = { id: '2', scene_id: 'SceneA' }
    const current = { id: '3', scene_id: 'SceneA' }
    store.grid = { batches: [baseline, oldCurrent, current], rows: [] }
    store.baselineBatch = baseline
    store.currentBatch = oldCurrent

    const oldLoad = store.loadGridHeatmaps()
    const duplicate = store.loadGridHeatmaps()
    expect(apiMock.comparisonLookup).toHaveBeenCalledTimes(1)
    const oldSignal = apiMock.comparisonLookup.mock.calls[0][2].signal

    store.currentBatch = current
    const currentLoad = store.loadGridHeatmaps()
    expect(apiMock.comparisonLookup).toHaveBeenCalledTimes(2)
    expect(oldSignal.aborted).toBe(true)

    currentRequest.resolve({ exists: true, heatmaps: { shot: '/images/latest.webp' } })
    await currentLoad
    oldRequest.resolve({ exists: true, heatmaps: { shot: '/images/stale.webp' } })
    await Promise.all([oldLoad, duplicate])

    expect(store.gridHeatmaps).toMatchObject({
      current_id: '3', baseline_id: '1',
      map: { shot: '/images/latest.webp' },
    })
    expect(store.gridHeatmapLoading).toBe(false)
  })

  it('快速切换对比记录时只为最新场景加载详情', async () => {
    const store = useStore()
    const oldScenes = deferred()
    const currentScenes = deferred()
    apiMock.scenes
      .mockImplementationOnce(() => oldScenes.promise)
      .mockImplementationOnce(() => currentScenes.promise)
    apiMock.item.mockResolvedValue({ id: 20, name: 'latest-detail' })

    const oldOpen = store.openComparison({ id: 1 })
    const oldSignal = apiMock.scenes.mock.calls[0][2].signal
    const currentOpen = store.openComparison({ id: 2 })
    expect(oldSignal.aborted).toBe(true)

    currentScenes.resolve({
      items: [{ id: 20, name: 'latest-scene' }], total: 1,
      counts: { all: 1, fail: 0, warn: 0, pass: 1, added: 0, missing: 0 },
    })
    await currentOpen
    oldScenes.resolve({
      items: [{ id: 10, name: 'stale-scene' }], total: 1,
      counts: { all: 1, fail: 1, warn: 0, pass: 0, added: 0, missing: 0 },
    })
    await oldOpen

    expect(apiMock.item).toHaveBeenCalledTimes(1)
    expect(apiMock.item).toHaveBeenCalledWith(20, expect.objectContaining({
      signal: expect.any(AbortSignal),
    }))
    expect(store.selectedComparison.id).toBe(2)
    expect(store.detail).toEqual({ id: 20, name: 'latest-detail' })
  })

  it('离开页面会取消场景、详情和热力图请求并停止加载状态', async () => {
    const store = useStore()
    const sceneRequest = deferred()
    const detailRequest = deferred()
    const heatmapRequest = deferred()
    apiMock.scenes.mockReturnValue(sceneRequest.promise)
    apiMock.item.mockReturnValue(detailRequest.promise)
    apiMock.comparisonLookup.mockReturnValue(heatmapRequest.promise)
    const baseline = { id: '1' }
    const current = { id: '2' }
    store.selectedComparison = { id: 42 }
    store.grid = { batches: [baseline, current], rows: [] }
    store.baselineBatch = baseline
    store.currentBatch = current

    const scenes = store.loadScenes()
    const detail = store.selectScene(7)
    const heatmaps = store.loadGridHeatmaps()
    const sceneSignal = apiMock.scenes.mock.calls[0][2].signal
    const detailSignal = apiMock.item.mock.calls[0][1].signal
    const heatmapSignal = apiMock.comparisonLookup.mock.calls[0][2].signal

    store.cancelComparisonDataRequests()
    store.cancelGridHeatmapRequest()

    expect(sceneSignal.aborted).toBe(true)
    expect(detailSignal.aborted).toBe(true)
    expect(heatmapSignal.aborted).toBe(true)
    expect(store.loading).toBe(false)
    expect(store.detailLoading).toBe(false)
    expect(store.gridHeatmapLoading).toBe(false)
    expect(store.comparisonDataStale).toBe(true)

    sceneRequest.resolve({ items: [{ id: 99 }], total: 1, counts: {} })
    detailRequest.resolve({ id: 99 })
    heatmapRequest.resolve({ exists: true, heatmaps: { stale: '/images/stale.webp' } })
    await Promise.all([scenes, detail, heatmaps])

    expect(store.scenes).toEqual([])
    expect(store.detail).toBeNull()
    expect(store.gridHeatmaps).toBeNull()
  })

  it('请求中离开结果页后重新进入会恢复当前对比的列表和详情', async () => {
    const store = useStore()
    store.selectedComparison = { id: 42 }
    store.flip = true
    store.comparisonDataStale = true
    apiMock.scenes.mockResolvedValue({
      items: [{ id: 7, name: 'restored-scene' }], total: 1,
      counts: { all: 1, fail: 0, warn: 0, pass: 1, added: 0, missing: 0 },
    })
    apiMock.item.mockResolvedValue({ id: 7, name: 'restored-detail' })

    await store.resumeComparisonData()

    expect(apiMock.scenes).toHaveBeenCalledWith(42, expect.any(Object), expect.objectContaining({
      signal: expect.any(AbortSignal),
    }))
    expect(apiMock.item).toHaveBeenCalledWith(7, expect.objectContaining({
      signal: expect.any(AbortSignal),
    }))
    expect(store.comparisonDataStale).toBe(false)
    expect(store.flip).toBe(true)
    expect(store.detail).toEqual({ id: 7, name: 'restored-detail' })
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
