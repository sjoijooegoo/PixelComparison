import { defineStore } from 'pinia'

import { api, isRequestCancelled } from '../api'

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

export const useGpmHeatmapStore = defineStore('gpmHeatmap', {
  state: () => ({
    meta: { branch_tag: 'main', platforms: [], shading_qualities: [], scene_ids: [] },
    filters: {
      branchTag: 'main', platform: '', sceneId: '', shadingQuality: '', batchId: '',
    },
    metricKey: 'Scene_DC',
    trendMode: 'average',
    days: 14,
    frame: null,
    selectedPointId: null,
    pointDetail: null,
    trends: null,
    loading: { meta: false, frame: false, detail: false, trends: false },
    errors: { meta: '', frame: '', detail: '', trends: '' },
    initialized: false,
  }),

  getters: {
    sceneOptions: (state) => state.meta.scene_ids || [],
    platformOptions: (state) => {
      const scene = state.meta.scene_ids?.find((item) => item.value === state.filters.sceneId)
      return scene?.platforms || state.meta.platforms || []
    },
    qualityOptions: (state) => {
      const scene = state.meta.scene_ids?.find((item) => item.value === state.filters.sceneId)
      const platformScope = scene?.platform_qualities?.find(
        (item) => item.platform === state.filters.platform,
      )
      if (platformScope) return platformScope.shading_qualities || []
      return scene?.shading_qualities || state.meta.shading_qualities || []
    },
    selectedPoint: (state) => state.frame?.points?.find(
      (point) => Number(point.id) === Number(state.selectedPointId),
    ) || null,
    metricOptions: (state) => (state.frame?.heat_map || [])
      .slice()
      .sort((a, b) => Number(a.index) - Number(b.index)),
    batchOptions: (state) => state.frame?.available_batches || [],
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
      const promise = api.gpmHeatmapMeta(
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

    async loadFrame(requestedBatchId = this.filters.batchId) {
      if (!this.filters.sceneId) {
        cancelChannel(this, 'frame')
        this.frame = null
        return null
      }
      const params = {
        branch_tag: this.filters.branchTag,
        platform: this.filters.platform,
        shading_quality: this.filters.shadingQuality,
        batch_id: requestedBatchId,
      }
      const key = JSON.stringify([this.filters.sceneId, params])
      const request = begin(this, 'frame', key)
      if (request.duplicate) return request.duplicate
      this.loading.frame = true
      this.errors.frame = ''
      const promise = api.gpmHeatmapFrame(this.filters.sceneId, params, { signal: request.signal })
      request.setPromise(promise)
      try {
        const data = await promise
        if (!request.isLatest()) return null
        this.frame = data
        this.filters.batchId = data.batch.batch_id
        this.metricKey = data.heat_map?.some((item) => item.key === this.metricKey)
          ? this.metricKey
          : firstValue(data.heat_map?.map((item) => item.key))
        const currentStillExists = data.points?.some(
          (point) => Number(point.id) === Number(this.selectedPointId),
        )
        this.selectedPointId = currentStillExists ? this.selectedPointId : (data.points?.[0]?.id ?? null)
        return data
      } catch (error) {
        if (isRequestCancelled(error) || !request.isLatest()) return null
        this.errors.frame = error?.message || 'GPMHeatmap 场景数据加载失败'
        this.frame = null
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
      if (this.trendMode === 'point' && pointId == null) {
        this.trends = null
        return null
      }
      if (this.trendMode === 'average' && !this.filters.sceneId) {
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
        ? JSON.stringify(['average', this.filters.sceneId, scope])
        : `point:${pointId}:${this.days}`
      const request = begin(this, 'trends', key)
      if (request.duplicate) return request.duplicate
      this.loading.trends = true
      this.errors.trends = ''
      const promise = this.trendMode === 'average'
        ? api.gpmHeatmapSceneTrends(this.filters.sceneId, scope, { signal: request.signal })
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
      this.filters.sceneId = keepValue(requested.sceneId || '', this.meta.scene_ids)
      this.filters.platform = keepValue(requested.platform || '', this.platformOptions, 'Android')
      this.filters.shadingQuality = keepValue(
        qualityValue(requested.shadingQuality), this.qualityOptions, 5,
      )
      this.metricKey = requested.metric || 'Scene_DC'
      this.trendMode = requested.trendMode === 'point' ? 'point' : 'average'
      this.days = [7, 14, 30].includes(Number(requested.days)) ? Number(requested.days) : 14
      this.selectedPointId = requested.point ? Number(requested.point) : null
      await this.loadFrame(requested.batchId || '')
      if (!isCurrentRoute()) return null
      if (this.selectedPointId != null && !this.frame?.points?.some(
        (point) => Number(point.id) === Number(this.selectedPointId),
      )) this.selectedPointId = this.frame?.points?.[0]?.id ?? null
      await Promise.all([this.loadPoint(), this.loadTrends()])
      if (!isCurrentRoute()) return null
      this.initialized = true
      return this.routeState()
    },

    async changeScope({ sceneId, platform, shadingQuality, batchId } = {}) {
      invalidateRouteApplication(this)
      if (sceneId !== undefined) this.filters.sceneId = sceneId
      if (platform !== undefined) this.filters.platform = platform
      if (shadingQuality !== undefined) this.filters.shadingQuality = qualityValue(shadingQuality)
      this.filters.platform = keepValue(this.filters.platform, this.platformOptions, 'Android')
      this.filters.shadingQuality = keepValue(this.filters.shadingQuality, this.qualityOptions, 5)
      this.selectedPointId = null
      this.pointDetail = null
      this.trends = null
      await this.loadFrame(batchId ?? '')
      await Promise.all([this.loadPoint(), this.loadTrends()])
      return this.routeState()
    },

    async refresh() {
      invalidateRouteApplication(this)
      this.cancelAll()
      await this.loadMeta()
      await this.loadFrame(this.filters.batchId)
      await Promise.all([this.loadPoint(), this.loadTrends()])
    },

    routeState() {
      return {
        sceneId: this.filters.sceneId,
        platform: this.filters.platform,
        shadingQuality: this.filters.shadingQuality,
        batchId: this.filters.batchId,
        metric: this.metricKey,
        point: this.selectedPointId,
        trendMode: this.trendMode,
        days: this.days,
      }
    },
  },
})
