import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const apiMock = vi.hoisted(() => ({
  gpmProjectConfig: vi.fn(),
  importGpmProjectConfig: vi.fn(),
  uploadGpmProjectMapImage: vi.fn(),
}))

vi.mock('../api', () => ({ api: apiMock }))

import { useGpmProjectConfigStore } from './gpmProjectConfigStore'

const catalog = {
  latest_import: { id: 1, source_filename: 'DataForInstance.json' },
  maps: [{ map_name: 'Village_Dimension_Main' }],
  summary: { total: 1, configured: 0, missing: 1 },
}

function deferred() {
  let resolve
  const promise = new Promise((res) => { resolve = res })
  return { promise, resolve }
}

describe('gpmProjectConfigStore', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    apiMock.gpmProjectConfig.mockResolvedValue(catalog)
    apiMock.importGpmProjectConfig.mockResolvedValue(catalog)
    apiMock.uploadGpmProjectMapImage.mockResolvedValue({ revision: 1 })
  })

  it('加载并替换项目地图清单', async () => {
    const store = useGpmProjectConfigStore()
    await store.load()
    expect(store.catalog).toEqual(catalog)

    const file = new File(['{}'], 'DataForInstance.json')
    await store.importConfig(file)
    expect(apiMock.importGpmProjectConfig).toHaveBeenCalledWith(file)
    expect(store.importing).toBe(false)
  })

  it('上传地图图片后刷新目录状态', async () => {
    const store = useGpmProjectConfigStore()
    const file = new File(['map'], 'map.png')
    await store.uploadImage('Village_Dimension_Main', file)

    expect(apiMock.uploadGpmProjectMapImage).toHaveBeenCalledWith('Village_Dimension_Main', file)
    expect(apiMock.gpmProjectConfig).toHaveBeenCalledOnce()
    expect(store.uploadingMap).toBe('')
  })

  it('较旧的目录响应不能覆盖更新后的配置', async () => {
    const oldRequest = deferred()
    const newRequest = deferred()
    apiMock.gpmProjectConfig
      .mockReturnValueOnce(oldRequest.promise)
      .mockReturnValueOnce(newRequest.promise)
    const store = useGpmProjectConfigStore()
    const oldLoad = store.load()
    const newLoad = store.load()
    newRequest.resolve({ ...catalog, summary: { total: 2, configured: 1, missing: 1 } })
    await newLoad
    oldRequest.resolve(catalog)
    await oldLoad

    expect(store.catalog.summary.total).toBe(2)
  })
})
