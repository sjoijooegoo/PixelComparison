import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

const { apiMock, routerMock, loggerMock } = vi.hoisted(() => ({
  apiMock: {
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
  vi.clearAllMocks()
})

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
