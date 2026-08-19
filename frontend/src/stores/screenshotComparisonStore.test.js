import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const apiMock = vi.hoisted(() => ({
  batch: vi.fn(),
  batches: vi.fn(),
  sceneGrid: vi.fn(),
  comparisonLookup: vi.fn(),
  comparisonTask: vi.fn(),
  createComparison: vi.fn(),
  deleteBatch: vi.fn(),
  meta: vi.fn(),
  settings: vi.fn(),
  saveSettings: vi.fn(),
}))

vi.mock('../api', () => ({
  api: apiMock,
  isRequestCancelled: (error) => error?.code === 'ABORTED' || error?.cancelled === true,
}))

import { useBatchCatalogStore } from './batchCatalogStore'
import { useProjectStore } from './projectStore'
import { useScreenshotComparisonStore } from './screenshotComparisonStore'

function deferred() {
  let resolve
  let reject
  const promise = new Promise((res, rej) => {
    resolve = res
    reject = rej
  })
  return { promise, resolve, reject }
}

function batch(id, overrides = {}) {
  return {
    id,
    branch_tag: 'main',
    scene_id: 'SceneA',
    shading_quality: 5,
    created_at: '2026-08-01 10:00',
    has_screenshots: true,
    ...overrides,
  }
}

function prepareProject() {
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
  project.initialized = true
  return project
}

beforeEach(() => {
  setActivePinia(createPinia())
  vi.clearAllMocks()
  apiMock.comparisonLookup.mockResolvedValue({
    exists: false,
    status: 'missing',
    ready: false,
    task_id: null,
    done: 0,
    total: 0,
  })
  prepareProject()
})

afterEach(() => {
  vi.useRealTimers()
})

describe('screenshot comparison route hydration', () => {
  it('未选择场景时保留空工作区且不请求网格', async () => {
    const store = useScreenshotComparisonStore()

    const normalized = await store.applyRoute({ branchTag: 'engine-ue5', sceneId: '' })

    expect(normalized).toMatchObject({
      branchTag: 'engine-ue5', sceneId: '', baselineId: '', currentId: '',
    })
    expect(apiMock.sceneGrid).not.toHaveBeenCalled()
    expect(apiMock.batch).not.toHaveBeenCalled()
  })

  it('刷新带角色的路由时保留 URL 日期和画质筛选', async () => {
    const baseline = batch('10', { created_at: '2026-08-01 09:00' })
    const current = batch('20', { created_at: '2026-08-02 10:00' })
    apiMock.batch.mockImplementation(async (id) => ({ 10: baseline, 20: current })[id])
    apiMock.sceneGrid.mockResolvedValue({
      total: 2,
      batches: [baseline, current],
      rows: [],
    })
    const store = useScreenshotComparisonStore()

    const normalized = await store.applyRoute({
      branchTag: 'main',
      sceneId: 'SceneA',
      baselineId: '10',
      currentId: '20',
      shadingQuality: '5',
      dateMode: 'range',
      createdFrom: '2026-08-01',
      createdTo: '2026-08-07',
    })

    expect(apiMock.sceneGrid).toHaveBeenCalledTimes(1)
    expect(apiMock.sceneGrid).toHaveBeenCalledWith(
      'SceneA',
      {
        branch_tag: 'main',
        scene_id: 'SceneA',
        shading_quality: 5,
        created_from: '2026-08-01',
        created_to: '2026-08-07',
      },
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    )
    expect(apiMock.batches).not.toHaveBeenCalled()
    expect(store.baselineBatch.id).toBe('10')
    expect(store.currentBatch.id).toBe('20')
    expect(normalized).toMatchObject({
      branchTag: 'main', sceneId: 'SceneA', baselineId: '10', currentId: '20',
      shadingQuality: 5,
      dateMode: 'range',
      createdFrom: '2026-08-01',
      createdTo: '2026-08-07',
    })
  })

  it('清理无截图、跨分支和重复的角色参数', async () => {
    apiMock.batch.mockImplementation(async (id) => batch(id, {
      branch_tag: id === 'cross' ? 'engine-ue5' : 'main',
      has_screenshots: id !== 'empty',
    }))
    apiMock.sceneGrid.mockResolvedValue({ total: 0, batches: [], rows: [] })
    const store = useScreenshotComparisonStore()

    const normalized = await store.applyRoute({
      branchTag: 'main', sceneId: 'SceneA', baselineId: 'cross', currentId: 'empty',
    })

    expect(normalized.baselineId).toBe('')
    expect(normalized.currentId).toBe('')
    expect(store.baselineBatch).toBeNull()
    expect(store.currentBatch).toBeNull()
  })

  it('用户修改画质后切换场景时保留当前画质', async () => {
    apiMock.sceneGrid.mockResolvedValue({ total: 0, batches: [], rows: [] })
    const store = useScreenshotComparisonStore()
    await store.applyRoute({ branchTag: 'main', sceneId: 'SceneA' })

    store.filters.shading_quality = 4
    // Arco Select 的 v-model 会先写入新场景，再触发路由切换。
    store.filters.scene_id = 'SceneB'
    await store.applyRoute({
      branchTag: 'main',
      sceneId: 'SceneB',
      shadingQuality: '4',
      dateMode: 'range',
      createdFrom: store.filters.created_from,
      createdTo: store.filters.created_to,
    })

    expect(store.filters.shading_quality).toBe(4)
    expect(apiMock.sceneGrid).toHaveBeenLastCalledWith(
      'SceneB',
      expect.objectContaining({ shading_quality: 4 }),
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    )
  })

  it('规范化指定日期和非法筛选参数', async () => {
    apiMock.sceneGrid.mockResolvedValue({ total: 0, batches: [], rows: [] })
    const store = useScreenshotComparisonStore()

    const normalized = await store.applyRoute({
      branchTag: 'main',
      sceneId: 'SceneA',
      shadingQuality: 'invalid',
      dateMode: 'days',
      createdDates: ['2026-08-03', 'bad-date', '2026-08-01', '2026-08-03'],
    })

    expect(store.filters.shading_quality).toBe(5)
    expect(store.filters.dateMode).toBe('days')
    expect(store.filters.created_dates).toEqual(['2026-08-01', '2026-08-03'])
    expect(normalized).toMatchObject({
      shadingQuality: 5,
      dateMode: 'days',
      createdDates: ['2026-08-01', '2026-08-03'],
    })
  })

  it('显式全部画质生效，非法连续范围回退项目默认日期', async () => {
    apiMock.sceneGrid.mockResolvedValue({ total: 0, batches: [], rows: [] })
    const store = useScreenshotComparisonStore()
    const expectedRange = store.defaultFilters('main', 'SceneA')

    const normalized = await store.applyRoute({
      branchTag: 'main',
      sceneId: 'SceneA',
      shadingQuality: 'all',
      dateMode: 'range',
      createdFrom: '2026-01-01',
      createdTo: '2026-08-01',
    })

    expect(store.filters.shading_quality).toBe('')
    expect(store.filters.created_from).toBe(expectedRange.created_from)
    expect(store.filters.created_to).toBe(expectedRange.created_to)
    expect(normalized.shadingQuality).toBe('')
  })

  it('指定日期全部非法时回退项目默认范围', async () => {
    apiMock.sceneGrid.mockResolvedValue({ total: 0, batches: [], rows: [] })
    const store = useScreenshotComparisonStore()

    const normalized = await store.applyRoute({
      branchTag: 'main',
      sceneId: 'SceneA',
      dateMode: 'days',
      createdDates: ['not-a-date'],
    })

    expect(normalized.dateMode).toBe('range')
    expect(store.filters.created_dates).toEqual([])
  })
})

describe('screenshot comparison request coordination', () => {
  it('相同筛选的并发网格请求复用同一个 inflight 请求', async () => {
    const request = deferred()
    apiMock.sceneGrid.mockReturnValue(request.promise)
    const store = useScreenshotComparisonStore()
    store.filters = store.defaultFilters('main', 'DedupScene')

    const first = store.loadGrid({ force: true })
    const duplicate = store.loadGrid()

    expect(apiMock.sceneGrid).toHaveBeenCalledTimes(1)
    request.resolve({ total: 0, batches: [], rows: [] })
    await Promise.all([first, duplicate])
  })

  it('快速切换场景时旧网格响应不能覆盖最新场景', async () => {
    const oldRequest = deferred()
    const newRequest = deferred()
    apiMock.sceneGrid
      .mockReturnValueOnce(oldRequest.promise)
      .mockReturnValueOnce(newRequest.promise)
    const store = useScreenshotComparisonStore()
    store.filters = store.defaultFilters('main', 'SceneA')
    const oldLoad = store.loadGrid({ force: true })

    store.filters.scene_id = 'SceneB'
    const newLoad = store.loadGrid({ force: true })
    newRequest.resolve({ total: 1, batches: [batch('new', { scene_id: 'SceneB' })], rows: [] })
    await newLoad
    oldRequest.resolve({ total: 1, batches: [batch('old')], rows: [] })
    await oldLoad

    expect(store.grid.batches.map((item) => item.id)).toEqual(['new'])
  })

  it('批次目录和截图对比持有互相独立的筛选状态', () => {
    const catalog = useBatchCatalogStore()
    const screenshot = useScreenshotComparisonStore()

    catalog.filters.branch_tag = 'engine-ue5'
    catalog.filters.scene_id = 'SceneB'

    expect(screenshot.filters.branch_tag).toBe('main')
    expect(screenshot.filters.scene_id).toBe('')
  })

  it('lookup 发现运行任务后恢复轮询并只在完成后展示热力图', async () => {
    vi.useFakeTimers()
    const baseline = batch('10')
    const current = batch('20')
    apiMock.comparisonLookup
      .mockResolvedValueOnce({
        exists: true,
        status: 'running',
        ready: false,
        task_id: 'task-1',
        done: 0,
        total: 1,
        heatmaps: {},
      })
      .mockResolvedValueOnce({
        exists: true,
        status: 'done',
        ready: true,
        task_id: null,
        done: 1,
        total: 1,
        heatmaps: { shot_01: '/images/heatmaps/1/shot_01.png?v=2' },
      })
    apiMock.comparisonTask.mockResolvedValue({ status: 'done', done: 1, total: 1 })
    const store = useScreenshotComparisonStore()
    store.grid = { total: 2, batches: [baseline, current], rows: [] }
    store.baselineBatch = baseline
    store.currentBatch = current

    await store.loadGridHeatmaps()
    expect(store.gridHeatmaps.status).toBe('running')
    expect(store.gridHeatmaps.ready).toBe(false)

    await vi.advanceTimersByTimeAsync(400)
    await Promise.resolve()

    expect(apiMock.comparisonTask).toHaveBeenCalledWith(
      'task-1', expect.objectContaining({ signal: expect.any(AbortSignal) }),
    )
    expect(store.gridHeatmaps.status).toBe('done')
    expect(store.gridHeatmaps.ready).toBe(true)
    expect(store.gridHeatmaps.map.shot_01).toContain('/images/heatmaps/1/shot_01.png')
  })

  it('恢复的轮询任务失败时收敛为页面错误态', async () => {
    vi.useFakeTimers()
    const baseline = batch('10')
    const current = batch('20')
    apiMock.comparisonLookup.mockResolvedValue({
      exists: true,
      status: 'running',
      ready: false,
      task_id: 'task-error',
      done: 0,
      total: 1,
      heatmaps: {},
    })
    apiMock.comparisonTask.mockResolvedValue({
      status: 'error', done: 0, total: 1, error: '后台计算失败',
    })
    const store = useScreenshotComparisonStore()
    store.grid = { total: 2, batches: [baseline, current], rows: [] }
    store.baselineBatch = baseline
    store.currentBatch = current

    await store.loadGridHeatmaps()
    await vi.advanceTimersByTimeAsync(400)
    await Promise.resolve()

    expect(store.running).toBe(false)
    expect(store.gridHeatmapError).toBe('后台计算失败')
  })

  it('快速替换角色时旧 lookup 响应不能覆盖当前批次对', async () => {
    const oldRequest = deferred()
    const newRequest = deferred()
    apiMock.comparisonLookup
      .mockReturnValueOnce(oldRequest.promise)
      .mockReturnValueOnce(newRequest.promise)
    const baseline = batch('10')
    const oldCurrent = batch('20')
    const newCurrent = batch('30')
    const store = useScreenshotComparisonStore()
    store.grid = { total: 3, batches: [baseline, oldCurrent, newCurrent], rows: [] }
    store.baselineBatch = baseline
    store.currentBatch = oldCurrent
    const oldLoad = store.loadGridHeatmaps()

    store.currentBatch = newCurrent
    const newLoad = store.loadGridHeatmaps()
    newRequest.resolve({
      exists: true,
      status: 'done',
      ready: true,
      done: 1,
      total: 1,
      heatmaps: { shot_01: '/images/new.png' },
    })
    await newLoad
    oldRequest.resolve({
      exists: true,
      status: 'done',
      ready: true,
      done: 1,
      total: 1,
      heatmaps: { shot_01: '/images/old.png' },
    })
    await oldLoad

    expect(store.gridHeatmaps.current_id).toBe('30')
    expect(store.gridHeatmaps.map.shot_01).toBe('/images/new.png')
  })

  it('离开页面会使尚未完成的角色元数据恢复失效', async () => {
    const roleRequest = deferred()
    apiMock.batch.mockReturnValue(roleRequest.promise)
    const store = useScreenshotComparisonStore()

    const applying = store.applyRoute({
      branchTag: 'main', sceneId: 'SceneA', baselineId: '10',
    })
    await Promise.resolve()
    const signal = apiMock.batch.mock.calls[0][1].signal

    store.deactivate()
    roleRequest.resolve(batch('10'))

    await expect(applying).resolves.toBeNull()
    expect(signal.aborted).toBe(true)
    expect(apiMock.sceneGrid).not.toHaveBeenCalled()
  })

  it('离开页面后创建任务的迟到响应不会重启轮询', async () => {
    const createRequest = deferred()
    apiMock.createComparison.mockReturnValue(createRequest.promise)
    const baseline = batch('10')
    const current = batch('20')
    const store = useScreenshotComparisonStore()
    store.grid = { total: 2, batches: [baseline, current], rows: [] }
    store.baselineBatch = baseline
    store.currentBatch = current

    const running = store.runComparison()
    await Promise.resolve()
    const signal = apiMock.createComparison.mock.calls[0][1].signal

    store.deactivate()
    createRequest.resolve({ status: 'running', task_id: 'task-late' })

    await expect(running).resolves.toBeNull()
    expect(signal.aborted).toBe(true)
    expect(apiMock.comparisonTask).not.toHaveBeenCalled()
    expect(store.running).toBe(false)
  })
})
