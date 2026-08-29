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
  saveGpmMapConfiguration: vi.fn(),
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
    apiMock.updateGpmMetricScale.mockResolvedValue({ id: 0 })
    apiMock.createGpmMetricScaleSet.mockResolvedValue({ id: 2 })
    apiMock.updateGpmMetricScaleSet.mockResolvedValue({ id: 0 })
    apiMock.saveGpmMapConfiguration.mockResolvedValue({ map_name: 'Village_Dimension_Main' })
  })

  it('用一个原子请求保存地图定义、标尺绑定和图片', async () => {
    const store = useGpmScaleConfigStore()
    const configuration = {
      map_name: 'Village_Dimension_Main', origin: [0, 0], range: [100, 100], bindings: [],
    }
    const image = new File(['map'], 'map.png', { type: 'image/png' })

    await store.saveMapConfiguration({
      mapName: configuration.map_name, configuration, image,
    })

    expect(apiMock.saveGpmMapConfiguration)
      .toHaveBeenCalledWith(configuration.map_name, configuration, image)
    expect(apiMock.gpmScaleCatalog).toHaveBeenCalledOnce()
    expect(store.saving).toBe(false)
  })

  it('加载完整标尺配置目录', async () => {
    const store = useGpmScaleConfigStore()
    await store.load()
    expect(store.catalog).toEqual(catalog)
    expect(store.loading).toBe(false)
  })

  it('保存最终契约标尺或标尺集后刷新共享目录', async () => {
    const store = useGpmScaleConfigStore()
    const body = {
      name: '场景DC标尺',
      segments: [
        { color: '#00ff00', expression: '<100' },
        { color: '#ff0000', expression: '>=100' },
      ],
    }
    await store.saveMetricScale(null, body)
    expect(apiMock.createGpmMetricScale).toHaveBeenCalledWith(body)

    const setBody = {
      name: '用户定义标尺集',
      items: [{ metric_key: 'GPU Time/ms', scale_id: 1 }],
    }
    await store.saveScaleSet(null, setBody)
    expect(apiMock.createGpmMetricScaleSet).toHaveBeenCalledWith(setBody)
    expect(apiMock.gpmScaleCatalog).toHaveBeenCalledTimes(2)
    expect(store.saving).toBe(false)
  })

  it('ID 为 0 的标尺和标尺集仍走更新接口', async () => {
    const store = useGpmScaleConfigStore()
    const scaleBody = { name: '零号标尺', segments: [] }
    const setBody = { name: '零号标尺集', items: [] }

    await store.saveMetricScale(0, scaleBody)
    await store.saveScaleSet(0, setBody)

    expect(apiMock.updateGpmMetricScale).toHaveBeenCalledWith(0, scaleBody)
    expect(apiMock.updateGpmMetricScaleSet).toHaveBeenCalledWith(0, setBody)
    expect(apiMock.createGpmMetricScale).not.toHaveBeenCalled()
    expect(apiMock.createGpmMetricScaleSet).not.toHaveBeenCalled()
  })

  it('原子地图保存失败时不制造部分保存状态', async () => {
    apiMock.saveGpmMapConfiguration.mockRejectedValue(new Error('地图保存失败'))
    const store = useGpmScaleConfigStore()

    await expect(store.saveMapConfiguration({
      mapName: 'Manual_Map',
      configuration: { map_name: 'Manual_Map', bindings: [] },
      image: null,
    })).rejects.toThrow('地图保存失败')
    expect(apiMock.gpmScaleCatalog).not.toHaveBeenCalled()
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

  it('命令已成功时，后续目录刷新失败不得误报为保存失败', async () => {
    apiMock.createGpmMetricScale.mockResolvedValue({ id: 0, name: '新标尺' })
    apiMock.gpmScaleCatalog.mockRejectedValue(new Error('网络中断'))
    const store = useGpmScaleConfigStore()

    await expect(store.saveMetricScale(null, { name: '新标尺', segments: [] }))
      .resolves.toMatchObject({ id: 0 })
    expect(store.catalog.metric_scales).toEqual([{ id: 0, name: '新标尺' }])
    expect(store.error).toContain('配置已保存，但列表刷新失败')
  })
})
