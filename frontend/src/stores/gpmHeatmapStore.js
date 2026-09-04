import { defineStore } from 'pinia'

import { api, isRequestCancelled } from '../api'
import { mergeGpmPlatforms, mergeGpmQualities } from '../gpmHeatmap/filterOptions'

const runtimes = new WeakMap()

function runtime(store) {
  if (!runtimes.has(store)) {
    const state = Object.fromEntries(
      ['meta', 'frame', 'detail', 'trends'].map((name) => [
        name, { sequence: 0, key: '', controller: null, promise: null },
      ]),
    )
    state.routeSequence = 0
    runtimes.set(store, state)
  }
  return runtimes.get(store)
}

function invalidateRouteApplication(store) {
  runtime(store).routeSequence += 1
}

function cancelChannel(store, channel) {
  const state = runtime(store)[channel]
  state.controller?.abort()
  state.sequence += 1
  state.key = ''
  state.controller = null
  state.promise = null
}

function begin(store, channel, key) {
  const state = runtime(store)[channel]
  if (state.key === key && state.promise) return { duplicate: state.promise }
  state.controller?.abort()
  state.controller = new AbortController()
  state.key = key
  state.sequence += 1
  const sequence = state.sequence
  return {
    signal: state.controller.signal,
    isLatest: () => state.sequence === sequence,
    setPromise: (promise) => { state.promise = promise },
    finish: () => {
      if (state.sequence !== sequence) return
      state.promise = null
      state.controller = null
    },
  }
}

function firstValue(items) {
  return items?.[0]?.value ?? items?.[0] ?? ''
}

function keepValue(current, items, preferred = '') {
  const values = (items || []).map((item) => item?.value ?? item)
  if (values.includes(current)) return current
  if (values.includes(preferred)) return preferred
  return values[0] ?? ''
}

function qualityValue(value) {
  if (value === '' || value === null || value === undefined) return ''
  const parsed = Number(value)
  return Number.isInteger(parsed) ? parsed : ''
}

function dataQualities(map, platform) {
  return map?.platform_qualities?.find((item) => item.platform === platform)
    ?.shading_qualities || []
}

function defaultDataPlatform(meta, preferred = 'IOS') {
  const candidates = [...new Set([
    preferred,
    ...(meta.platforms || []),
    ...mergeGpmPlatforms(...(meta.maps || []).map((item) => item.platforms || [])),
  ])]
  return candidates.find((platform) => (
    meta.maps?.some((map) => dataQualities(map, platform).length)
  )) || preferred
}

function firstDataMap(meta, platform) {
  return meta.maps?.find((map) => dataQualities(map, platform).length)?.value
    || meta.maps?.find((map) => map.has_data)?.value
    || ''
}

function firstDataQuality(meta, mapName, platform) {
  const map = meta.maps?.find((item) => item.value === mapName)
  return firstValue(dataQualities(map, platform))
}

function pointIndexIdentity(value) {
  if (value === null || value === undefined || String(value).trim() === '') return null
  const pointIndex = Number(value)
  return Number.isInteger(pointIndex) && pointIndex >= 0 ? { pointIndex } : null
}

function pointSelectionIdentity(point) {
  return pointIndexIdentity(point?.index)
}

function matchingPoint(points, identity) {
  if (identity?.pointIndex == null) return null
  return points?.find((point) => Number(point.index) === identity.pointIndex) || null
}

export const useGpmHeatmapStore = defineStore('gpmHeatmap', {
  state: () => ({
    meta: { branch_tag: 'main', platforms: [], shading_qualities: [], maps: [] },
    filters: {
      branchTag: 'main', platform: '', mapName: '', shadingQuality: '', batchId: '',
    },
    metricKey: 'Scene_DC',
    trendMode: 'average',
    days: 14,
    frame: null,
    selectedPointId: null,
    pointDetail: null,
    trends: null,
    scopeEmpty: false,
    loading: { meta: false, frame: false, detail: false, trends: false },
    errors: { meta: '', frame: '', detail: '', trends: '' },
    initialized: false,
  }),

  getters: {
    mapOptions: (state) => state.meta.maps || [],
    platformOptions: (state) => {
      const map = state.meta.maps?.find((item) => item.value === state.filters.mapName)
      return mergeGpmPlatforms(state.meta.platforms || [], map?.platforms || [])
    },
    qualityOptions: (state) => {
      const map = state.meta.maps?.find((item) => item.value === state.filters.mapName)
      const platformScope = map?.platform_qualities?.find(
        (item) => item.platform === state.filters.platform,
      )
      return mergeGpmQualities(
        state.meta.shading_qualities || [],
        map?.shading_qualities || [],
        platformScope?.shading_qualities || [],
      )
    },
    mapHasBatches: (state) => (mapName) => {
      if (state.loading.meta) return null
      const map = state.meta.maps?.find((item) => item.value === mapName)
      if (!map) return false
      const platformScope = map.platform_qualities?.find(
        (item) => item.platform === state.filters.platform,
      )
      const qualities = platformScope?.shading_qualities || []
      if (state.filters.shadingQuality === '') return qualities.length > 0
      return qualities.some(
        (item) => Number(item.value) === Number(state.filters.shadingQuality),
      )
    },
    qualityHasBatches: (state) => (quality) => {
      if (state.loading.meta) return null
      const map = state.meta.maps?.find(
        (item) => item.value === state.filters.mapName,
      )
      const platformScope = map?.platform_qualities?.find(
        (item) => item.platform === state.filters.platform,
      )
      return (platformScope?.shading_qualities || []).some(
        (item) => Number(item.value) === Number(quality),
      )
    },
    selectedPoint: (state) => state.frame?.points?.find(
      (point) => Number(point.id) === Number(state.selectedPointId),
    ) || null,
    metricOptions: (state) => (state.frame?.heat_map || [])
      .slice()
      .sort((a, b) => Number(a.index) - Number(b.index)),
    batchOptions: (state) => (
      state.loading.frame && !state.filters.batchId ? [] : (state.frame?.available_batches || [])
    ),
  },

  actions: {
    cancelAll() {
      for (const channel of ['meta', 'frame', 'detail', 'trends']) cancelChannel(this, channel)
    },

    dispose() {
      invalidateRouteApplication(this)
      this.cancelAll()
    },

    async loadMeta() {
      const key = this.filters.branchTag || 'main'
      const request = begin(this, 'meta', key)
      if (request.duplicate) return request.duplicate
      this.loading.meta = true
      this.errors.meta = ''
      const promise = api.gpmHeatmapCatalog(
        { branch_tag: this.filters.branchTag },
        { signal: request.signal },
      )
      request.setPromise(promise)
      try {
        const data = await promise
        if (!request.isLatest()) return null
        this.meta = data
        return data
      } catch (error) {
        if (isRequestCancelled(error) || !request.isLatest()) return null
        this.errors.meta = error?.message || 'GPMHeatmap 筛选项加载失败'
        throw error
      } finally {
        if (request.isLatest()) this.loading.meta = false
        request.finish()
      }
    },

    async loadFrame(
      requestedBatchId = this.filters.batchId,
      nearestP4Version = null,
      preferredPoint = null,
    ) {
      if (!this.filters.mapName) {
        cancelChannel(this, 'frame')
        this.frame = null
        this.scopeEmpty = false
        return null
      }
      const configuredMap = this.meta.maps?.some((item) => item.value === this.filters.mapName)
      if (configuredMap && this.mapHasBatches(this.filters.mapName) === false) {
        cancelChannel(this, 'frame')
        this.frame = null
        this.filters.batchId = ''
        this.selectedPointId = null
        this.pointDetail = null
        this.trends = null
        this.errors.frame = ''
        this.scopeEmpty = true
        return null
      }
      const params = {
        branch_tag: this.filters.branchTag,
        platform: this.filters.platform,
        shading_quality: this.filters.shadingQuality,
        batch_id: requestedBatchId,
        nearest_p4_version: requestedBatchId ? null : nearestP4Version,
      }
      const key = JSON.stringify([this.filters.mapName, params])
      const request = begin(this, 'frame', key)
      if (request.duplicate) return request.duplicate
      this.loading.frame = true
      this.errors.frame = ''
      this.scopeEmpty = false
      const promise = api.gpmHeatmapFrame(this.filters.mapName, params, { signal: request.signal })
      request.setPromise(promise)
      try {
        const data = await promise
        if (!request.isLatest()) return null
        this.frame = data
        this.scopeEmpty = false
        this.filters.batchId = data.batch.batch_id
        this.metricKey = data.heat_map?.some((item) => item.key === this.metricKey)
          ? this.metricKey
          : firstValue(data.heat_map?.map((item) => item.key))
        const restoredPoint = matchingPoint(data.points, preferredPoint)
        const currentStillExists = data.points?.some(
          (point) => Number(point.id) === Number(this.selectedPointId),
        )
        this.selectedPointId = restoredPoint?.id
          ?? (currentStillExists ? this.selectedPointId : (data.points?.[0]?.id ?? null))
        return data
      } catch (error) {
        if (isRequestCancelled(error) || !request.isLatest()) return null
        if (error?.code === 'GPM_MAP_DATA_NOT_FOUND') {
          this.frame = null
          this.filters.batchId = ''
          this.selectedPointId = null
          this.pointDetail = null
          this.trends = null
          this.scopeEmpty = true
          return null
        }
        this.errors.frame = error?.message || 'GPMHeatmap 场景数据加载失败'
        this.frame = null
        this.scopeEmpty = false
        throw error
      } finally {
        if (request.isLatest()) this.loading.frame = false
        request.finish()
      }
    },

    async loadPoint() {
      const pointId = this.selectedPointId
      if (pointId == null) {
        this.pointDetail = null
        if (this.trendMode === 'point') this.trends = null
        return null
      }
      const key = String(pointId)
      const request = begin(this, 'detail', key)
      if (request.duplicate) return request.duplicate
      this.loading.detail = true
      this.errors.detail = ''
      const promise = api.gpmHeatmapPoint(pointId, { signal: request.signal })
      request.setPromise(promise)
      try {
        const data = await promise
        if (!request.isLatest()) return null
        this.pointDetail = data
        return data
      } catch (error) {
        if (isRequestCancelled(error) || !request.isLatest()) return null
        this.errors.detail = error?.message || '点位详情加载失败'
        throw error
      } finally {
        if (request.isLatest()) this.loading.detail = false
        request.finish()
      }
    },

    async loadTrends() {
      const pointId = this.selectedPointId
      if (this.scopeEmpty) {
        this.trends = null
        return null
      }
      if (this.trendMode === 'point' && pointId == null) {
        this.trends = null
        return null
      }
      if (this.trendMode === 'average' && !this.filters.mapName) {
        this.trends = null
        return null
      }
      const scope = {
        branch_tag: this.filters.branchTag,
        platform: this.filters.platform,
        shading_quality: this.filters.shadingQuality,
        days: this.days,
      }
      const key = this.trendMode === 'average'
        ? JSON.stringify(['average', this.filters.mapName, scope])
        : `point:${pointId}:${this.days}`
      const request = begin(this, 'trends', key)
      if (request.duplicate) return request.duplicate
      this.loading.trends = true
      this.errors.trends = ''
      const promise = this.trendMode === 'average'
        ? api.gpmHeatmapMapTrends(this.filters.mapName, scope, { signal: request.signal })
        : api.gpmHeatmapTrends(pointId, { days: this.days }, { signal: request.signal })
      request.setPromise(promise)
      try {
        const data = await promise
        if (!request.isLatest()) return null
        this.trends = data
        return data
      } catch (error) {
        if (isRequestCancelled(error) || !request.isLatest()) return null
        this.errors.trends = error?.message || '趋势数据加载失败'
        throw error
      } finally {
        if (request.isLatest()) this.loading.trends = false
        request.finish()
      }
    },

    async selectPoint(pointId) {
      if (Number(pointId) === Number(this.selectedPointId) && this.pointDetail) return this.pointDetail
      invalidateRouteApplication(this)
      cancelChannel(this, 'detail')
      if (this.trendMode === 'point') cancelChannel(this, 'trends')
      this.selectedPointId = pointId
      await Promise.all([
        this.loadPoint(),
        this.trendMode === 'point' ? this.loadTrends() : Promise.resolve(null),
      ])
      return this.pointDetail
    },

    async changeTrendMode(mode) {
      const nextMode = mode === 'average' ? 'average' : 'point'
      if (nextMode === this.trendMode && this.trends) return this.trends
      invalidateRouteApplication(this)
      cancelChannel(this, 'trends')
      this.trendMode = nextMode
      return this.loadTrends()
    },

    async applyRoute(requested = {}) {
      const state = runtime(this)
      const routeSequence = state.routeSequence + 1
      state.routeSequence = routeSequence
      const isCurrentRoute = () => runtime(this).routeSequence === routeSequence
      this.cancelAll()
      this.initialized = false
      this.filters.branchTag = String(requested.branchTag || 'main').trim().toLowerCase() || 'main'
      await this.loadMeta()
      if (!isCurrentRoute()) return null
      const requestedPlatform = String(requested.platform || '')
      const preferredPlatform = requestedPlatform || defaultDataPlatform(this.meta, 'IOS')
      this.filters.platform = keepValue(
        preferredPlatform, mergeGpmPlatforms(this.meta.platforms || []), 'IOS',
      )
      const preferredMap = firstDataMap(this.meta, this.filters.platform)
      this.filters.mapName = keepValue(
        requested.mapName || '', this.meta.maps, preferredMap,
      )
      const preferredQuality = firstDataQuality(
        this.meta, this.filters.mapName, this.filters.platform,
      )
      this.filters.shadingQuality = keepValue(
        qualityValue(requested.shadingQuality), this.qualityOptions, preferredQuality,
      )
      this.metricKey = requested.metric || 'Scene_DC'
      this.trendMode = requested.trendMode === 'point' ? 'point' : 'average'
      this.days = [7, 14, 30].includes(Number(requested.days)) ? Number(requested.days) : 14
      const requestedPoint = pointIndexIdentity(requested.point)
      this.selectedPointId = null
      await this.loadFrame(requested.batchId || '', null, requestedPoint)
      if (!isCurrentRoute()) return null
      await Promise.all([this.loadPoint(), this.loadTrends()])
      if (!isCurrentRoute()) return null
      this.initialized = true
      return this.routeState()
    },

    async changeScope({ mapName, platform, shadingQuality, batchId } = {}) {
      invalidateRouteApplication(this)
      const routeSequence = runtime(this).routeSequence
      const isCurrent = () => routeSequence === runtime(this).routeSequence
      const switchingPlatform = platform !== undefined && platform !== this.filters.platform
      const nearestP4Version = switchingPlatform
        ? (this.frame?.batch?.p4_version ?? null)
        : null
      const selectingBatch = batchId !== undefined
      const keepsMap = mapName === undefined || mapName === this.filters.mapName
      const keepsPointScope = keepsMap
      const preferredPoint = keepsPointScope ? pointSelectionIdentity(this.selectedPoint) : null
      cancelChannel(this, 'detail')
      cancelChannel(this, 'trends')
      if (mapName !== undefined) this.filters.mapName = mapName
      if (platform !== undefined) this.filters.platform = platform
      if (shadingQuality !== undefined) this.filters.shadingQuality = qualityValue(shadingQuality)
      this.filters.platform = keepValue(this.filters.platform, this.platformOptions, 'Android')
      this.filters.shadingQuality = keepValue(this.filters.shadingQuality, this.qualityOptions, 5)
      this.filters.batchId = selectingBatch ? batchId : ''
      if (!keepsPointScope) {
        this.selectedPointId = null
        this.pointDetail = null
        this.trends = null
      }
      await this.loadFrame(
        selectingBatch ? batchId : '',
        selectingBatch ? null : nearestP4Version,
        preferredPoint,
      )
      if (!isCurrent()) return null
      await Promise.all([this.loadPoint(), this.loadTrends()])
      if (!isCurrent()) return null
      return this.routeState()
    },

    async refresh() {
      invalidateRouteApplication(this)
      const preferredPoint = pointSelectionIdentity(this.selectedPoint)
      this.cancelAll()
      await this.loadMeta()
      await this.loadFrame('', null, preferredPoint)
      await Promise.all([this.loadPoint(), this.loadTrends()])
    },

    routeState() {
      return {
        mapName: this.filters.mapName,
        platform: this.filters.platform,
        shadingQuality: this.filters.shadingQuality,
        batchId: this.filters.batchId,
        metric: this.metricKey,
        point: pointSelectionIdentity(this.selectedPoint)?.pointIndex ?? null,
        trendMode: this.trendMode,
        days: this.days,
      }
    },
  },
})
