import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const apiMock = vi.hoisted(() => ({
  batch: vi.fn(),
  batches: vi.fn(),
  sceneGrid: vi.fn(),
  sceneAvailability: vi.fn(),
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
    column_id: `${id}:5`,
    branch_tag: 'main',
    scene_id: 'SceneA',
    platform: 'Windows',
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
  apiMock.sceneAvailability.mockResolvedValue({ scene_ids: [] })
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
      baselineQuality: '5',
      currentId: '20',
      currentQuality: '5',
      shadingQuality: '5',
      dateMode: 'range',
      rangeMode: 'fixed',
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
      branchTag: 'main', sceneId: 'SceneA', baselineId: '10', baselineQuality: 5,
      currentId: '20', currentQuality: 5,
      shadingQuality: 5,
      dateMode: 'range',
      rangeMode: 'fixed',
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

  it('旧版默认日期 URL 迁移为滚动范围并在刷新时推进到今天', async () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-08-29T12:00:00'))
    apiMock.sceneGrid.mockResolvedValue({ total: 0, batches: [], rows: [] })
    const store = useScreenshotComparisonStore()

    const normalized = await store.applyRoute({
      branchTag: 'main',
      sceneId: 'SceneA',
      dateMode: 'range',
      createdFrom: '2026-08-23',
      createdTo: '2026-08-29',
    })

    expect(normalized.rangeMode).toBe('rolling')
    vi.setSystemTime(new Date('2026-08-30T12:00:00'))
    const refreshed = await store.refresh()

    expect(refreshed).toMatchObject({
      rangeMode: 'rolling',
      createdFrom: '2026-08-24',
      createdTo: '2026-08-30',
    })
    expect(apiMock.sceneGrid).toHaveBeenLastCalledWith(
      'SceneA',
      expect.objectContaining({
        created_from: '2026-08-24',
        created_to: '2026-08-30',
      }),
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    )
  })

  it('刷新时保留用户明确选择的固定历史范围', async () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-08-29T12:00:00'))
    apiMock.sceneGrid.mockResolvedValue({ total: 0, batches: [], rows: [] })
    const store = useScreenshotComparisonStore()
    await store.applyRoute({
      branchTag: 'main',
      sceneId: 'SceneA',
      dateMode: 'range',
      rangeMode: 'fixed',
      createdFrom: '2026-08-01',
      createdTo: '2026-08-07',
    })

    vi.setSystemTime(new Date('2026-08-30T12:00:00'))
    await store.refresh()

    expect(store.filters).toMatchObject({
      rangeMode: 'fixed',
      created_from: '2026-08-01',
      created_to: '2026-08-07',
    })
  })
})

describe('screenshot scene availability', () => {
  it('只发送分支、画质和日期，不让当前场景缩窄下拉菜单', async () => {
    const store = useScreenshotComparisonStore()
    store.filters = {
      branch_tag: 'main',
      scene_id: 'SceneA',
      shading_quality: 5,
      dateMode: 'days',
      created_from: '2026-08-01',
      created_to: '2026-08-07',
      created_dates: ['2026-08-01', '2026-08-03'],
    }
    apiMock.sceneAvailability.mockResolvedValue({ scene_ids: ['SceneB'] })

    await store.loadSceneAvailability()

    expect(store.availableSceneIds).toEqual(['SceneB'])
    expect(apiMock.sceneAvailability).toHaveBeenCalledWith({
      capability: 'screenshots',
      branch_tag: 'main',
      shading_quality: 5,
      created_dates: ['2026-08-01', '2026-08-03'],
    }, { signal: expect.any(AbortSignal) })
  })

  it('快速切换画质时取消旧请求且只接受最新响应', async () => {
    const first = deferred()
    const second = deferred()
    apiMock.sceneAvailability
      .mockReturnValueOnce(first.promise)
      .mockReturnValueOnce(second.promise)
    const store = useScreenshotComparisonStore()

    store.filters.shading_quality = 5
    const oldLoad = store.loadSceneAvailability()
    store.filters.shading_quality = 3
    const newLoad = store.loadSceneAvailability()
    second.resolve({ scene_ids: ['PrettyScene'] })
    await newLoad
    first.resolve({ scene_ids: ['MovieScene'] })
    await oldLoad

    expect(store.availableSceneIds).toEqual(['PrettyScene'])
    expect(apiMock.sceneAvailability.mock.calls[0][1].signal.aborted).toBe(true)
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

  it('离开页面会使尚未完成的角色网格恢复失效', async () => {
    const gridRequest = deferred()
    apiMock.sceneGrid.mockReturnValue(gridRequest.promise)
    const store = useScreenshotComparisonStore()

    const applying = store.applyRoute({
      branchTag: 'main', sceneId: 'SceneB', baselineId: '10',
      dateMode: 'days', createdDates: ['2026-07-31'],
    })
    await Promise.resolve()
    await Promise.resolve()
    const signal = apiMock.sceneGrid.mock.calls[0][2].signal

    store.deactivate()
    gridRequest.resolve({ total: 1, batches: [batch('10')], rows: [] })

    await expect(applying).resolves.toBeNull()
    expect(signal.aborted).toBe(true)
    expect(store.baselineBatch).toBeNull()
  })

  it('多画质角色用列身份恢复，旧链接在有歧义时不猜测画质', async () => {
    const movie = batch('10')
    const high = batch('10', { column_id: '10:3', shading_quality: 3 })
    const current = batch('20')
    apiMock.sceneGrid.mockResolvedValue({ total: 3, batches: [movie, high, current], rows: [] })
    const store = useScreenshotComparisonStore()

    let normalized = await store.applyRoute({
      branchTag: 'main', sceneId: 'SceneA', baselineId: '10', currentId: '20',
      currentQuality: '5',
      dateMode: 'days', createdDates: ['2026-07-30'], shadingQuality: 'all',
    })
    expect(store.baselineBatch).toBeNull()
    expect(normalized.baselineId).toBe('')

    normalized = await store.applyRoute({
      branchTag: 'main', sceneId: 'SceneA', baselineId: '10', baselineQuality: '5',
      currentId: '20', currentQuality: '5',
      dateMode: 'days', createdDates: ['2026-07-30'], shadingQuality: 'all',
    })
    expect(store.baselineBatch.column_id).toBe('10:5')
    expect(normalized.baselineQuality).toBe(5)
  })

  it('禁止跨画质角色对比并把画质传给 lookup 和创建接口', async () => {
    const baseline = batch('10')
    const otherQuality = batch('20', { column_id: '20:3', shading_quality: 3 })
    const current = batch('30')
    const store = useScreenshotComparisonStore()
    store.grid = { total: 3, batches: [baseline, otherQuality, current], rows: [] }
    store.setRole(baseline, 'baseline')
    store.setRole(otherQuality, 'current')
    expect(store.currentBatch).toBeNull()
    expect(store.canCompare).toBe(false)

    store.setRole(current, 'current')
    await store.loadGridHeatmaps()
    expect(apiMock.comparisonLookup).toHaveBeenLastCalledWith(
      '30', '10', 5, expect.objectContaining({ signal: expect.any(AbortSignal) }),
    )
    apiMock.createComparison.mockResolvedValue({ status: 'done' })
    await store.runComparison()
    expect(apiMock.createComparison).toHaveBeenCalledWith(
      expect.objectContaining({ batch_id: '30', ref_batch_id: '10', shading_quality: 5 }),
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    )
  })

  it('禁止选择跨平台对比列', () => {
    const baseline = batch('10', { platform: 'Windows' })
    const android = batch('20', { platform: 'Android' })
    const store = useScreenshotComparisonStore()
    store.grid = { total: 2, batches: [baseline, android], rows: [] }

    store.setRole(baseline, 'baseline')
    store.setRole(android, 'current')

    expect(store.currentBatch).toBeNull()
    expect(store.canCompare).toBe(false)
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
