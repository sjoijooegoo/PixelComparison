import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const apiMock = vi.hoisted(() => ({
  gpmHeatmapCatalog: vi.fn(),
  gpmHeatmapFrame: vi.fn(),
  gpmHeatmapMapTrends: vi.fn(),
  gpmHeatmapPoint: vi.fn(),
  gpmHeatmapTrends: vi.fn(),
}))

vi.mock('../api', () => ({
  api: apiMock,
  isRequestCancelled: (error) => error?.code === 'ABORTED',
}))

import { useGpmHeatmapStore } from './gpmHeatmapStore'

function deferred() {
  let resolve
  let reject
  const promise = new Promise((res, rej) => { resolve = res; reject = rej })
  return { promise, resolve, reject }
}

function frame(mapName, pointId, batchId = mapName, p4Version = 2960783, points = null) {
  return {
    batch: { batch_id: batchId, p4_version: p4Version },
    available_batches: [{ batch_id: batchId }],
    map: { map_name: mapName },
    heat_map: [{ key: 'Scene_DC', name: '场景 DC' }],
    trend: [{ key: 'Scene_DC', name: 'Scene_DC' }],
    points: points || [{ id: pointId, index: 1, heat_map_data: { Scene_DC: pointId } }],
  }
}

function meta(mapName) {
  return {
    branch_tag: 'main',
    platforms: ['Android'],
    shading_qualities: [{ value: 5, label: '电影' }],
    maps: [{
      value: mapName,
      platforms: ['Android'],
      shading_qualities: [{ value: 5, label: '电影' }],
      platform_qualities: [{
        platform: 'Android', shading_qualities: [{ value: 5, label: '电影' }],
      }],
    }],
  }
}

beforeEach(() => {
  setActivePinia(createPinia())
  vi.clearAllMocks()
  apiMock.gpmHeatmapMapTrends.mockResolvedValue({ available: true, points: [] })
})

describe('GPMHeatmap store request ordering', () => {
  it('场景快速切换时旧 frame 响应不能覆盖新场景', async () => {
    const oldRequest = deferred()
    const newRequest = deferred()
    apiMock.gpmHeatmapFrame
      .mockReturnValueOnce(oldRequest.promise)
      .mockReturnValueOnce(newRequest.promise)
    const store = useGpmHeatmapStore()
    store.filters.platform = 'Android'
    store.filters.shadingQuality = 5

    store.filters.mapName = 'OldScene'
    const oldLoad = store.loadFrame()
    store.filters.mapName = 'NewScene'
    const newLoad = store.loadFrame()
    newRequest.resolve(frame('NewScene', 22))
    await newLoad
    oldRequest.resolve(frame('OldScene', 11))
    await oldLoad

    expect(store.frame.map.map_name).toBe('NewScene')
    expect(store.selectedPointId).toBe(22)
  })

  it('同参数并发读取会复用同一个 inflight 请求', async () => {
    const pending = deferred()
    apiMock.gpmHeatmapFrame.mockReturnValue(pending.promise)
    const store = useGpmHeatmapStore()
    Object.assign(store.filters, {
      mapName: 'Village_Dimension_Main', platform: 'Android', shadingQuality: 5,
    })

    const first = store.loadFrame()
    const second = store.loadFrame()
    pending.resolve(frame('Village_Dimension_Main', 1, 'gpm-1'))
    await Promise.all([first, second])

    expect(apiMock.gpmHeatmapFrame).toHaveBeenCalledTimes(1)
    expect(store.filters.batchId).toBe('gpm-1')
  })

  it('点位切换并行加载详情和趋势', async () => {
    apiMock.gpmHeatmapPoint.mockResolvedValue({ id: 8, detail_data: [] })
    apiMock.gpmHeatmapTrends.mockResolvedValue({ available: false, points: [] })
    const store = useGpmHeatmapStore()
    store.trendMode = 'point'

    await store.selectPoint(8)

    expect(apiMock.gpmHeatmapPoint).toHaveBeenCalledWith(8, expect.any(Object))
    expect(apiMock.gpmHeatmapTrends).toHaveBeenCalledWith(8, { days: 14 }, expect.any(Object))
    expect(store.pointDetail.id).toBe(8)
  })

  it('单点模式切换点位时保留旧详情和趋势直到新响应完成', async () => {
    const detailRequest = deferred()
    const trendRequest = deferred()
    apiMock.gpmHeatmapPoint.mockReturnValue(detailRequest.promise)
    apiMock.gpmHeatmapTrends.mockReturnValue(trendRequest.promise)
    const store = useGpmHeatmapStore()
    store.trendMode = 'point'
    store.selectedPointId = 8
    store.pointDetail = { id: 8, detail_data: [{ name: 'old-detail' }] }
    store.trends = { available: true, points: [{ batch_id: 'old-trend' }] }

    const selecting = store.selectPoint(9)

    expect(store.selectedPointId).toBe(9)
    expect(store.pointDetail.id).toBe(8)
    expect(store.trends.points[0].batch_id).toBe('old-trend')
    expect(store.loading.detail).toBe(true)
    expect(store.loading.trends).toBe(true)

    detailRequest.resolve({ id: 9, detail_data: [{ name: 'new-detail' }] })
    trendRequest.resolve({ available: true, points: [{ batch_id: 'new-trend' }] })
    await selecting

    expect(store.pointDetail.id).toBe(9)
    expect(store.trends.points[0].batch_id).toBe('new-trend')
  })

  it('整体平均按场景筛选加载，切换点位不重复请求整体趋势', async () => {
    apiMock.gpmHeatmapMapTrends.mockResolvedValue({ available: true, points: [] })
    apiMock.gpmHeatmapPoint.mockResolvedValue({ id: 8, detail_data: [] })
    const store = useGpmHeatmapStore()
    Object.assign(store.filters, {
      branchTag: 'main', mapName: 'Village_Dimension_Main',
      platform: 'Android', shadingQuality: 5,
    })

    await store.changeTrendMode('average')
    await store.selectPoint(8)

    expect(apiMock.gpmHeatmapMapTrends).toHaveBeenCalledTimes(1)
    expect(apiMock.gpmHeatmapMapTrends).toHaveBeenCalledWith(
      'Village_Dimension_Main',
      {
        branch_tag: 'main', platform: 'Android', shading_quality: 5, days: 14,
      },
      expect.any(Object),
    )
    expect(apiMock.gpmHeatmapTrends).not.toHaveBeenCalled()
    expect(apiMock.gpmHeatmapPoint).toHaveBeenCalledTimes(1)
  })

  it('切换趋势统计方式时保留旧曲线直到新响应完成', async () => {
    const pending = deferred()
    apiMock.gpmHeatmapTrends.mockReturnValue(pending.promise)
    const store = useGpmHeatmapStore()
    store.trendMode = 'average'
    store.selectedPointId = 8
    store.trends = { available: true, points: [{ batch_id: 'old' }] }

    const switching = store.changeTrendMode('point')

    expect(store.trendMode).toBe('point')
    expect(store.trends.points[0].batch_id).toBe('old')
    expect(store.loading.trends).toBe(true)

    pending.resolve({ available: true, points: [{ batch_id: 'new' }] })
    await switching

    expect(store.trends.points[0].batch_id).toBe('new')
    expect(store.loading.trends).toBe(false)
  })

  it('路由仅接受 7、14、30 天并默认 14 天', async () => {
    apiMock.gpmHeatmapCatalog.mockResolvedValue(meta('Village_Dimension_Main'))
    apiMock.gpmHeatmapFrame.mockResolvedValue(frame('Village_Dimension_Main', 8, 'gpm-1'))
    apiMock.gpmHeatmapPoint.mockResolvedValue({ id: 8, detail_data: [] })
    apiMock.gpmHeatmapTrends.mockResolvedValue({ available: true, points: [] })
    const store = useGpmHeatmapStore()

    await store.applyRoute({ mapName: 'Village_Dimension_Main', days: 60 })

    expect(store.days).toBe(14)
    expect(store.routeState().trendMode).toBe('average')
  })

  it('无显式场景路由时跳过无数据地图并选择首个有数据地图', async () => {
    const response = meta('DataMap')
    response.maps.unshift({
      id: 1,
      value: 'EmptyMap',
      has_data: false,
      platforms: [],
      shading_qualities: [],
      platform_qualities: [],
    })
    response.maps[1].id = 2
    response.maps[1].has_data = true
    apiMock.gpmHeatmapCatalog.mockResolvedValue(response)
    apiMock.gpmHeatmapFrame.mockResolvedValue(frame('DataMap', 8, 'gpm-1'))
    apiMock.gpmHeatmapPoint.mockResolvedValue({ id: 8, detail_data: [] })
    const store = useGpmHeatmapStore()

    await store.applyRoute({})

    expect(store.filters.mapName).toBe('DataMap')
    expect(apiMock.gpmHeatmapFrame).toHaveBeenCalledWith(
      'DataMap', expect.any(Object), expect.any(Object),
    )
  })

  it('从其他页面进入时默认选择 IOS 下首个有数据场景、首个有数据画质和最新批次', async () => {
    const response = {
      branch_tag: 'main',
      platforms: ['IOS', 'Android', 'Windows'],
      shading_qualities: [
        { value: 5, label: '电影' },
        { value: 3, label: '高' },
        { value: 1, label: '低' },
      ],
      maps: [
        {
          id: 0, value: 'AndroidOnly', has_data: true,
          platforms: ['Android'],
          platform_qualities: [{
            platform: 'Android', shading_qualities: [{ value: 5, label: '电影' }],
          }],
        },
        {
          id: 1, value: 'FirstIOSMap', has_data: true,
          platforms: ['IOS'],
          platform_qualities: [{
            platform: 'IOS',
            shading_qualities: [{ value: 3, label: '高' }, { value: 1, label: '低' }],
          }],
        },
        {
          id: 2, value: 'SecondIOSMap', has_data: true,
          platforms: ['IOS'],
          platform_qualities: [{
            platform: 'IOS', shading_qualities: [{ value: 5, label: '电影' }],
          }],
        },
      ],
    }
    apiMock.gpmHeatmapCatalog.mockResolvedValue(response)
    apiMock.gpmHeatmapFrame.mockResolvedValue(frame('FirstIOSMap', 8, 'ios-latest'))
    apiMock.gpmHeatmapPoint.mockResolvedValue({ id: 8, detail_data: [] })
    const store = useGpmHeatmapStore()

    await store.applyRoute({})

    expect(store.filters).toMatchObject({
      platform: 'IOS', mapName: 'FirstIOSMap', shadingQuality: 3, batchId: 'ios-latest',
    })
    expect(apiMock.gpmHeatmapFrame).toHaveBeenCalledWith(
      'FirstIOSMap',
      expect.objectContaining({
        platform: 'IOS', shading_quality: 3, batch_id: '', nearest_p4_version: null,
      }),
      expect.any(Object),
    )
  })

  it('空数据组合保留平台画质筛选并进入正常空状态', async () => {
    const response = meta('EmptyMap')
    response.platforms = []
    response.shading_qualities = []
    response.maps[0] = {
      id: 0,
      value: 'EmptyMap',
      has_data: false,
      platforms: [],
      shading_qualities: [],
      platform_qualities: [],
    }
    apiMock.gpmHeatmapCatalog.mockResolvedValue(response)
    const store = useGpmHeatmapStore()

    await store.applyRoute({ mapName: 'EmptyMap', platform: 'IOS', shadingQuality: 4 })

    expect(store.filters).toMatchObject({
      mapName: 'EmptyMap', platform: 'IOS', shadingQuality: 4, batchId: '',
    })
    expect(store.platformOptions).toEqual(['IOS', 'Android', 'Windows'])
    expect(store.qualityOptions.map((item) => item.value)).toEqual([5, 4, 3, 2, 1, 0])
    expect(store.mapHasBatches('EmptyMap')).toBe(false)
    expect(store.qualityHasBatches(4)).toBe(false)
    expect(store.scopeEmpty).toBe(true)
    expect(store.errors.frame).toBe('')
    expect(apiMock.gpmHeatmapFrame).not.toHaveBeenCalled()
    expect(apiMock.gpmHeatmapPoint).not.toHaveBeenCalled()
    expect(apiMock.gpmHeatmapMapTrends).not.toHaveBeenCalled()
  })

  it('按当前平台和关联筛选判断场景、画质是否存在采集批次', () => {
    const store = useGpmHeatmapStore()
    store.meta = meta('DataMap')
    Object.assign(store.filters, {
      mapName: 'DataMap', platform: 'Android', shadingQuality: 5,
    })

    expect(store.mapHasBatches('DataMap')).toBe(true)
    expect(store.qualityHasBatches(5)).toBe(true)
    expect(store.qualityHasBatches(4)).toBe(false)

    store.filters.platform = 'IOS'
    expect(store.mapHasBatches('DataMap')).toBe(false)
    expect(store.qualityHasBatches(5)).toBe(false)
  })

  it('切换筛选范围时清除旧批次并按当前 P4 请求最近批次', async () => {
    const pending = deferred()
    apiMock.gpmHeatmapFrame.mockReturnValue(pending.promise)
    apiMock.gpmHeatmapPoint.mockResolvedValue({ id: 9, detail_data: [] })
    const store = useGpmHeatmapStore()
    Object.assign(store.filters, {
      mapName: 'Village_Dimension_Main', platform: 'Android',
      shadingQuality: 5, batchId: 'gpm-demo-20260826',
    })
    store.frame = frame(
      'Village_Dimension_Main', 8, 'gpm-demo-20260826', 2960783,
    )

    const changing = store.changeScope({ platform: 'IOS' })

    expect(store.filters.batchId).toBe('')
    expect(store.batchOptions).toEqual([])
    expect(apiMock.gpmHeatmapFrame).toHaveBeenCalledWith(
      'Village_Dimension_Main',
      expect.objectContaining({
        platform: 'IOS', batch_id: '', nearest_p4_version: 2960783,
      }),
      expect.any(Object),
    )

    pending.resolve(frame('Village_Dimension_Main', 9, 'ios-nearest', 2960785))
    await changing
    expect(store.filters.batchId).toBe('ios-nearest')
  })

  it('同一场景切换画质或批次时按稳定身份保留当前点位', async () => {
    const oldPoints = [
      { id: 11, index: 1, screenshot_id: '01', point_key: 'route-1' },
      { id: 12, index: 2, screenshot_id: '02', point_key: 'route-2' },
    ]
    const newPoints = [
      { id: 21, index: 1, screenshot_id: '01', point_key: 'route-1' },
      { id: 22, index: 2, screenshot_id: '02', point_key: 'route-2' },
    ]
    apiMock.gpmHeatmapFrame.mockResolvedValue(
      frame('Village_Dimension_Main', 21, 'quality-3', 2960800, newPoints),
    )
    apiMock.gpmHeatmapPoint.mockResolvedValue({ id: 22, detail_data: [] })
    const store = useGpmHeatmapStore()
    Object.assign(store.filters, {
      mapName: 'Village_Dimension_Main', platform: 'Android',
      shadingQuality: 5, batchId: 'quality-5',
    })
    store.frame = frame(
      'Village_Dimension_Main', 11, 'quality-5', 2960783, oldPoints,
    )
    store.selectedPointId = 12
    store.pointDetail = { id: 12, detail_data: [{ name: 'old' }] }

    await store.changeScope({ shadingQuality: 3 })

    expect(store.selectedPointId).toBe(22)
    expect(store.pointDetail.id).toBe(22)
    expect(apiMock.gpmHeatmapPoint).toHaveBeenCalledWith(22, expect.any(Object))
  })

  it('点位没有稳定 point_key 时不按截图 ID 或序号误配', async () => {
    const store = useGpmHeatmapStore()
    Object.assign(store.filters, {
      mapName: 'Village_Dimension_Main', platform: 'Android',
      shadingQuality: 5, batchId: 'old',
    })
    store.frame = frame('Village_Dimension_Main', 31, 'old', 2960783, [
      { id: 31, index: 1, screenshot_id: '01' },
      { id: 32, index: 2, screenshot_id: '02' },
    ])
    store.selectedPointId = 32
    apiMock.gpmHeatmapFrame.mockResolvedValue(
      frame('Village_Dimension_Main', 41, 'new', 2960784, [
        { id: 41, index: 1, screenshot_id: '01' },
        { id: 42, index: 2, screenshot_id: '02' },
      ]),
    )
    apiMock.gpmHeatmapPoint.mockResolvedValue({ id: 41, detail_data: [] })

    await store.changeScope({ batchId: 'new' })

    expect(store.selectedPointId).toBe(41)
    expect(store.pointDetail.id).toBe(41)
  })

  it('切换平台时不把其他平台的同名 point_key 当成当前点位', async () => {
    const store = useGpmHeatmapStore()
    Object.assign(store.filters, {
      mapName: 'Village_Dimension_Main', platform: 'Android',
      shadingQuality: 5, batchId: 'android',
    })
    store.frame = frame('Village_Dimension_Main', 31, 'android', 2960783, [
      { id: 31, index: 1, point_key: 'route-1' },
      { id: 32, index: 2, point_key: 'route-2' },
    ])
    store.selectedPointId = 32
    apiMock.gpmHeatmapFrame.mockResolvedValue(
      frame('Village_Dimension_Main', 41, 'ios', 2960784, [
        { id: 41, index: 1, point_key: 'route-1' },
        { id: 42, index: 2, point_key: 'route-2' },
      ]),
    )
    apiMock.gpmHeatmapPoint.mockResolvedValue({ id: 41, detail_data: [] })

    await store.changeScope({ platform: 'IOS' })

    expect(store.selectedPointId).toBe(41)
  })

  it('刷新时忽略当前批次并切换到筛选范围内最新批次', async () => {
    apiMock.gpmHeatmapCatalog.mockResolvedValue(meta('Village_Dimension_Main'))
    apiMock.gpmHeatmapFrame.mockResolvedValue(
      frame('Village_Dimension_Main', 9, 'gpm-latest', 2960900),
    )
    apiMock.gpmHeatmapPoint.mockResolvedValue({ id: 9, detail_data: [] })
    const store = useGpmHeatmapStore()
    Object.assign(store.filters, {
      branchTag: 'main', mapName: 'Village_Dimension_Main', platform: 'Android',
      shadingQuality: 5, batchId: 'gpm-demo-20260826',
    })

    await store.refresh()

    expect(apiMock.gpmHeatmapFrame).toHaveBeenCalledWith(
      'Village_Dimension_Main',
      expect.objectContaining({ batch_id: '', nearest_p4_version: null }),
      expect.any(Object),
    )
    expect(store.filters.batchId).toBe('gpm-latest')
    expect(store.selectedPointId).toBe(9)
  })

  it('重叠路由中已取消的 meta 响应不能再改筛选或发起旧 frame 请求', async () => {
    const oldMeta = deferred()
    const newMeta = deferred()
    apiMock.gpmHeatmapCatalog
      .mockReturnValueOnce(oldMeta.promise)
      .mockReturnValueOnce(newMeta.promise)
    apiMock.gpmHeatmapFrame.mockResolvedValue(frame('NewScene', 22, 'new-batch'))
    apiMock.gpmHeatmapPoint.mockResolvedValue({ id: 22, detail_data: [] })
    apiMock.gpmHeatmapTrends.mockResolvedValue({ available: false, points: [] })
    const store = useGpmHeatmapStore()

    const oldRoute = store.applyRoute({ mapName: 'OldScene', platform: 'Android', shadingQuality: 5 })
    const newRoute = store.applyRoute({ mapName: 'NewScene', platform: 'Android', shadingQuality: 5 })
    newMeta.resolve(meta('NewScene'))
    await newRoute
    oldMeta.resolve(meta('OldScene'))
    await oldRoute

    expect(store.filters.mapName).toBe('NewScene')
    expect(store.frame.map.map_name).toBe('NewScene')
    expect(store.initialized).toBe(true)
    expect(apiMock.gpmHeatmapFrame).toHaveBeenCalledTimes(1)
    expect(apiMock.gpmHeatmapFrame.mock.calls[0][0]).toBe('NewScene')
  })

  it('页面离开后使进行中的路由初始化失效且不再发后续请求', async () => {
    const pendingMeta = deferred()
    apiMock.gpmHeatmapCatalog.mockReturnValue(pendingMeta.promise)
    const store = useGpmHeatmapStore()

    const applying = store.applyRoute({
      mapName: 'Village_Dimension_Main', platform: 'Android', shadingQuality: 5,
    })
    store.dispose()
    pendingMeta.resolve(meta('Village_Dimension_Main'))
    await applying

    expect(apiMock.gpmHeatmapFrame).not.toHaveBeenCalled()
    expect(store.initialized).toBe(false)
  })
})
