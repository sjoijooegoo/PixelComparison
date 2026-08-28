import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const apiMock = vi.hoisted(() => ({
  gpmScaleCatalog: vi.fn(),
  createGpmMetricScale: vi.fn(),
  updateGpmMetricScale: vi.fn(),
  deleteGpmMetricScale: vi.fn(),
  createGpmMetricScaleSet: vi.fn(),
  updateGpmMetricScaleSet: vi.fn(),
  deleteGpmMetricScaleSet: vi.fn(),
  updateGpmMapScaleBindings: vi.fn(),
}))

vi.mock('../api', () => ({ api: apiMock }))

import { useGpmScaleConfigStore } from './gpmScaleConfigStore'

const catalog = {
  palette: { colors: ['green', 'lime', 'amber', 'orange', 'red'], labels: [] },
  platforms: ['Android'], shading_qualities: [{ value: 5, label: '电影' }],
  metric_scales: [], scale_sets: [], maps: [],
}

function deferred() {
  let resolve
  const promise = new Promise((res) => { resolve = res })
  return { promise, resolve }
}

describe('gpmScaleConfigStore', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    apiMock.gpmScaleCatalog.mockResolvedValue(catalog)
    apiMock.createGpmMetricScale.mockResolvedValue({ id: 1 })
    apiMock.createGpmMetricScaleSet.mockResolvedValue({ id: 2 })
    apiMock.updateGpmMapScaleBindings.mockResolvedValue({ map_name: 'Village_Dimension_Main' })
  })

  it('加载完整标尺配置目录', async () => {
    const store = useGpmScaleConfigStore()
    await store.load()
    expect(store.catalog).toEqual(catalog)
    expect(store.loading).toBe(false)
  })

  it('保存最小标尺或地图应用后刷新共享目录', async () => {
    const store = useGpmScaleConfigStore()
    const body = {
      name: '场景DC标尺', metric_key: 'Scene_DC', thresholds: [100, 200, 300, 400],
    }
    await store.saveMetricScale(null, body)
    expect(apiMock.createGpmMetricScale).toHaveBeenCalledWith(body)
    expect(apiMock.gpmScaleCatalog).toHaveBeenCalledOnce()

    const setBody = {
      name: '用户定义标尺集',
      items: [{ metric_key: 'GPU Time/ms', scale_id: 1 }],
    }
    await store.saveScaleSet(null, setBody)
    expect(apiMock.createGpmMetricScaleSet).toHaveBeenCalledWith(setBody)
    expect(apiMock.gpmScaleCatalog).toHaveBeenCalledTimes(2)

    await store.saveMapBindings('Village_Dimension_Main', { bindings: [] })
    expect(apiMock.updateGpmMapScaleBindings).toHaveBeenCalledWith(
      'Village_Dimension_Main', { bindings: [] },
    )
    expect(apiMock.gpmScaleCatalog).toHaveBeenCalledTimes(3)
    expect(store.saving).toBe(false)
  })

  it('较旧的标尺目录响应不能覆盖最新目录', async () => {
    const oldRequest = deferred()
    const newRequest = deferred()
    apiMock.gpmScaleCatalog
      .mockReturnValueOnce(oldRequest.promise)
      .mockReturnValueOnce(newRequest.promise)
    const store = useGpmScaleConfigStore()
    const oldLoad = store.load()
    const newLoad = store.load()
    newRequest.resolve({ ...catalog, metric_scales: [{ id: 2, name: 'new' }] })
    await newLoad
    oldRequest.resolve({ ...catalog, metric_scales: [{ id: 1, name: 'old' }] })
    await oldLoad

    expect(store.catalog.metric_scales[0].name).toBe('new')
  })
})
