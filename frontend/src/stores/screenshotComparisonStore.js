import { defineStore } from 'pinia'

import { api, isRequestCancelled } from '../api'
import {
  DATE_RANGE_MODE_FIXED,
  DATE_RANGE_MODE_ROLLING,
  cloneRequestParams,
  defaultDateRange,
  isDateRangeAllowed,
  normalizeDateRangeMode,
  normalizeSelectedDates,
  normalizeShadingQuality,
  refreshRollingDateRange,
} from '../store'
import { useProjectStore } from './projectStore'
import { qualityColumnKey, sameQualityColumn } from '../qualityRuns'

const GRID_CACHE_LIMIT = 8
const gridCache = new Map()
const runtimes = new WeakMap()

function emptyGrid() {
  return { batches: [], rows: [], total: 0 }
}

function runtime(store) {
  if (!runtimes.has(store)) {
    runtimes.set(store, {
      route: { sequence: 0, controller: null },
      availability: { sequence: 0, controller: null, promise: null },
      grid: { sequence: 0, key: '', controller: null, promise: null },
      lookup: { sequence: 0, key: '', controller: null, promise: null },
      creation: { sequence: 0, key: '', controller: null, promise: null },
      polling: { sequence: 0, controller: null },
    })
  }
  return runtimes.get(store)
}

function abortChannel(store, channel) {
  const state = runtime(store)[channel]
  state.controller?.abort()
  state.controller = null
  state.promise = null
  state.key = ''
  state.sequence += 1
}

function cacheKey(sceneId, filters) {
  return JSON.stringify({ scene_id: sceneId, ...cloneRequestParams(filters) })
}

function rememberGrid(key, data) {
  gridCache.delete(key)
  gridCache.set(key, data)
  if (gridCache.size > GRID_CACHE_LIMIT) gridCache.delete(gridCache.keys().next().value)
}

function queryId(value) {
  const selected = Array.isArray(value) ? value[0] : value
  return selected == null || selected === '' ? '' : String(selected)
}

function routeFilters(project, branchTag, sceneId, requested) {
  const quality = project.settings.default_shading_quality
  const defaultRangeDays = project.settings.default_date_range_days ?? 7
  const defaults = {
    branch_tag: branchTag,
    scene_id: sceneId,
    shading_quality: (quality === -1 || quality == null) ? '' : quality,
    dateMode: 'range',
    rangeMode: DATE_RANGE_MODE_ROLLING,
    ...defaultDateRange(defaultRangeDays),
    created_dates: [],
  }
  defaults.shading_quality = normalizeShadingQuality(
    requested.shadingQuality,
    defaults.shading_quality,
  )
  if (requested.dateMode === 'days') {
    const requestedDates = Array.isArray(requested.createdDates)
      ? requested.createdDates
      : [requested.createdDates].filter((value) => value != null && value !== '')
    const dates = normalizeSelectedDates(requestedDates)
    // `dates=` 是用户尚未选择日期的合法空态；只有实际传入但全部非法时才回退默认范围。
    if (!requestedDates.length || dates.length) {
      defaults.dateMode = 'days'
      defaults.created_dates = dates
    }
  } else if (
    (requested.dateMode === 'range'
      || (!requested.dateMode && (requested.createdFrom || requested.createdTo)))
    && isDateRangeAllowed(requested.createdFrom, requested.createdTo)
  ) {
    defaults.rangeMode = normalizeDateRangeMode(
      requested.rangeMode,
      requested.createdFrom,
      requested.createdTo,
      defaultRangeDays,
    )
    if (defaults.rangeMode === DATE_RANGE_MODE_FIXED) {
      defaults.created_from = requested.createdFrom
      defaults.created_to = requested.createdTo
    }
  }
  return defaults
}

function normalizedRoute(filters, baseline = null, current = null) {
  return {
    branchTag: filters.branch_tag || 'main',
    sceneId: filters.scene_id || '',
    baselineId: baseline?.id == null ? '' : String(baseline.id),
    baselineQuality: baseline?.shading_quality ?? '',
    currentId: current?.id == null ? '' : String(current.id),
    currentQuality: current?.shading_quality ?? '',
    shadingQuality: filters.shading_quality,
    dateMode: filters.dateMode,
    rangeMode: filters.rangeMode,
    createdFrom: filters.created_from,
    createdTo: filters.created_to,
    createdDates: [...filters.created_dates],
  }
}

function routeQuality(value) {
  if (value === undefined || value === null || value === '') return null
  const quality = normalizeShadingQuality(value, null)
  return quality === '' ? null : quality
}

function findRouteColumn(columns, batchId, requestedQuality) {
  if (!batchId) return null
  const candidates = columns.filter((column) => String(column.id) === String(batchId))
  const quality = routeQuality(requestedQuality)
  if (quality != null) {
    return candidates.find((column) => Number(column.shading_quality) === quality) || null
  }
  // 旧链接没有角色画质时，只允许对单画质批次做无歧义恢复。
  return candidates.length === 1 ? candidates[0] : null
}

function comparisonPairKey(current, baseline) {
  return `${qualityColumnKey(current)}|${qualityColumnKey(baseline)}`
}

function wait(ms, signal) {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(resolve, ms)
    signal?.addEventListener('abort', () => {
      clearTimeout(timer)
      const error = new Error('请求已取消')
      error.code = 'ABORTED'
      error.cancelled = true
      reject(error)
    }, { once: true })
  })
}

export const useScreenshotComparisonStore = defineStore('screenshotComparison', {
  state: () => ({
    filters: {
      branch_tag: 'main',
      scene_id: '',
      shading_quality: 5,
      dateMode: 'range',
      rangeMode: DATE_RANGE_MODE_ROLLING,
      ...defaultDateRange(),
      created_dates: [],
    },
    grid: emptyGrid(),
    gridCollapsed: new Set(),
    gridLoading: false,
    gridError: '',
    availableSceneIds: null,
    sceneAvailabilityError: '',
    baselineBatch: null,
    currentBatch: null,
    gridHeatmaps: null,
    gridHeatmapLoading: false,
    gridHeatmapError: '',
    running: false,
    progress: { done: 0, total: 0 },
    initialized: false,
  }),

  getters: {
    requestFilters: (state) => {
      const {
        dateMode, rangeMode, created_from, created_to, created_dates, ...rest
      } = state.filters
      return dateMode === 'days'
        ? { ...rest, created_dates }
        : { ...rest, created_from, created_to }
    },
    hasEmptyDateSelection: (state) => (
      state.filters.dateMode === 'days' && !state.filters.created_dates.length
    ),
    canCompare: (state) => Boolean(
      state.currentBatch
      && state.baselineBatch
      && !sameQualityColumn(state.currentBatch, state.baselineBatch)
      && state.currentBatch.has_screenshots !== false
      && state.baselineBatch.has_screenshots !== false
      && (state.currentBatch.branch_tag || 'main') === (state.baselineBatch.branch_tag || 'main')
      && state.currentBatch.scene_id === state.baselineBatch.scene_id
      && state.currentBatch.platform === state.baselineBatch.platform
      && Number(state.currentBatch.shading_quality) === Number(state.baselineBatch.shading_quality)
    ),
  },

  actions: {
    defaultFilters(branchTag = 'main', sceneId = '') {
      const project = useProjectStore()
      const quality = project.settings.default_shading_quality
      return {
        branch_tag: branchTag,
        scene_id: sceneId,
        shading_quality: (quality === -1 || quality == null) ? '' : quality,
        dateMode: 'range',
        rangeMode: DATE_RANGE_MODE_ROLLING,
        ...defaultDateRange(project.settings.default_date_range_days ?? 7),
        created_dates: [],
      }
    },

    async applyRoute(requested = {}) {
      const {
        branchTag = 'main', sceneId = '', baselineId = '', baselineQuality = '',
        currentId = '', currentQuality = '',
      } = requested
      const project = useProjectStore()
      const state = runtime(this).route
      state.controller?.abort()
      state.controller = new AbortController()
      const requestId = ++state.sequence
      const isLatest = () => state.sequence === requestId

      this.cancelDataRequests()
      this.initialized = false
      const requestedBranch = String(branchTag || 'main').trim().toLowerCase()
      const branch = project.meta.branch_tags.includes(requestedBranch) ? requestedBranch : 'main'
      const scene = project.meta.scene_ids.includes(sceneId) ? sceneId : ''
      this.filters = routeFilters(project, branch, scene, requested)
      this.baselineBatch = null
      this.currentBatch = null
      this.gridHeatmaps = null

      const availability = this.loadSceneAvailability()

      if (!scene) {
        this.grid = emptyGrid()
        await availability
        if (!isLatest()) return null
        this.initialized = true
        return normalizedRoute(this.filters)
      }

      await Promise.all([this.loadGrid(), availability])
      if (!isLatest()) return null
      this.baselineBatch = findRouteColumn(
        this.grid.batches, queryId(baselineId), baselineQuality,
      )
      this.currentBatch = findRouteColumn(
        this.grid.batches, queryId(currentId), currentQuality,
      )
      if (sameQualityColumn(this.baselineBatch, this.currentBatch)) this.baselineBatch = null
      if (this.baselineBatch && this.currentBatch
        && (Number(this.baselineBatch.shading_quality) !== Number(this.currentBatch.shading_quality)
          || this.baselineBatch.platform !== this.currentBatch.platform)) {
        this.currentBatch = null
      }
      this.initialized = true
      await this.loadGridHeatmaps()
      return normalizedRoute(this.filters, this.baselineBatch, this.currentBatch)
    },

    async loadGrid({ force = false } = {}) {
      const sceneId = this.filters.scene_id
      if (!sceneId || this.hasEmptyDateSelection) {
        abortChannel(this, 'grid')
        this.grid = emptyGrid()
        this.gridLoading = false
        this._clearRolesOutsideGrid()
        return this.grid
      }
      const params = cloneRequestParams(this.requestFilters)
      const key = cacheKey(sceneId, params)
      const state = runtime(this).grid
      if (!force && state.promise && state.key === key) return await state.promise
      state.controller?.abort()
      const controller = new AbortController()
      const requestId = ++state.sequence
      state.controller = controller
      state.key = key
      this.gridLoading = true
      this.gridError = ''

      const operation = (async () => {
        try {
          const data = !force && gridCache.has(key)
            ? gridCache.get(key)
            : await api.sceneGrid(sceneId, params, { signal: controller.signal })
          if (state.sequence !== requestId) return null
          if (!gridCache.has(key) || force) rememberGrid(key, data)
          this.grid = data
          this._clearRolesOutsideGrid()
          return data
        } catch (error) {
          if (isRequestCancelled(error) || state.sequence !== requestId) return null
          this.gridError = error?.message || '截图网格加载失败'
          throw error
        } finally {
          if (state.sequence === requestId) {
            this.gridLoading = false
            state.promise = null
          }
        }
      })()
      state.promise = operation
      return await operation
    },

    async loadSceneAvailability() {
      const state = runtime(this).availability
      state.controller?.abort()
      const controller = new AbortController()
      const requestId = ++state.sequence
      state.controller = controller
      this.availableSceneIds = null
      this.sceneAvailabilityError = ''
      if (this.hasEmptyDateSelection) {
        this.availableSceneIds = []
        state.controller = null
        state.promise = null
        return { scene_ids: [] }
      }
      const filters = cloneRequestParams(this.requestFilters)
      delete filters.scene_id
      const operation = (async () => {
        try {
          const result = await api.sceneAvailability({
            capability: 'screenshots',
            ...filters,
          }, { signal: controller.signal })
          if (state.sequence !== requestId) return null
          this.availableSceneIds = result.scene_ids || []
          return result
        } catch (error) {
          if (isRequestCancelled(error) || state.sequence !== requestId) return null
          this.availableSceneIds = null
          this.sceneAvailabilityError = error?.message || '场景可用性加载失败'
          return null
        } finally {
          if (state.sequence === requestId) {
            state.controller = null
            state.promise = null
          }
        }
      })()
      state.promise = operation
      return await operation
    },

    async applyFilters() {
      await Promise.all([this.loadGrid(), this.loadSceneAvailability()])
      await this.loadGridHeatmaps()
    },

    async resetFilters() {
      const { branch_tag: branchTag, scene_id: sceneId } = this.filters
      this.filters = this.defaultFilters(branchTag, sceneId)
      await this.applyFilters()
    },

    async refresh() {
      const project = useProjectStore()
      refreshRollingDateRange(
        this.filters,
        project.settings.default_date_range_days ?? 7,
      )
      await Promise.all([
        this.loadGrid({ force: true }),
        this.loadSceneAvailability(),
      ])
      await this.loadGridHeatmaps()
      return normalizedRoute(this.filters, this.baselineBatch, this.currentBatch)
    },

    _clearRolesOutsideGrid() {
      const visible = new Set(this.grid.batches.map(qualityColumnKey))
      if (this.baselineBatch && !visible.has(qualityColumnKey(this.baselineBatch))) this.baselineBatch = null
      if (this.currentBatch && !visible.has(qualityColumnKey(this.currentBatch))) this.currentBatch = null
    },

    setRole(batch, role) {
      // 网格接口本身只返回包含截图的批次；旧响应可能没有显式能力字段。
      if (!batch || batch.has_screenshots === false) return
      abortChannel(this, 'creation')
      if (role === 'baseline') {
        if (sameQualityColumn(this.currentBatch, batch)) this.currentBatch = null
        this.baselineBatch = batch
        if (this.currentBatch
          && (Number(this.currentBatch.shading_quality) !== Number(batch.shading_quality)
            || this.currentBatch.platform !== batch.platform)) this.currentBatch = null
      } else {
        if (this.baselineBatch
          && (Number(this.baselineBatch.shading_quality) !== Number(batch.shading_quality)
            || this.baselineBatch.platform !== batch.platform)) return
        if (sameQualityColumn(this.baselineBatch, batch)) this.baselineBatch = null
        this.currentBatch = batch
      }
      void this.loadGridHeatmaps()
    },

    clearRole(role) {
      abortChannel(this, 'creation')
      if (role === 'baseline') this.baselineBatch = null
      else this.currentBatch = null
      void this.loadGridHeatmaps()
    },

    async loadGridHeatmaps() {
      const current = this.currentBatch
      const baseline = this.baselineBatch
      if (!current || !baseline || sameQualityColumn(current, baseline)
        || Number(current.shading_quality) !== Number(baseline.shading_quality)) {
        abortChannel(this, 'lookup')
        abortChannel(this, 'polling')
        this.gridHeatmaps = null
        this.gridHeatmapLoading = false
        this.gridHeatmapError = ''
        this.running = false
        return null
      }
      const key = comparisonPairKey(current, baseline)
      const state = runtime(this).lookup
      if (state.promise && state.key === key) return await state.promise
      state.controller?.abort()
      abortChannel(this, 'polling')
      const controller = new AbortController()
      const requestId = ++state.sequence
      state.controller = controller
      state.key = key
      this.gridHeatmapLoading = true
      this.gridHeatmapError = ''

      const operation = (async () => {
        try {
          const response = await api.comparisonLookup(
            current.id, baseline.id, current.shading_quality, {
            signal: controller.signal,
          })
          if (state.sequence !== requestId || !this._isCurrentPair(key)) return null
          this.gridHeatmaps = {
            current_id: current.id,
            baseline_id: baseline.id,
            current_column_id: qualityColumnKey(current),
            baseline_column_id: qualityColumnKey(baseline),
            exists: Boolean(response.exists),
            ready: Boolean(response.ready ?? response.exists),
            status: response.status || (response.exists ? 'done' : 'missing'),
            map: response.heatmaps || {},
            comparison: response.comparison || null,
          }
          this.progress = { done: response.done || 0, total: response.total || 0 }
          if (this.gridHeatmaps.status === 'running' && response.task_id) {
            this.running = true
            // 页面恢复时的轮询在后台运行，错误已收敛到 store 状态；
            // 显式消化 rejection，避免任务失败变成全局未处理 Promise。
            void this.pollComparison(response.task_id, key).catch(() => {})
          } else this.running = false
          return this.gridHeatmaps
        } catch (error) {
          if (isRequestCancelled(error) || state.sequence !== requestId) return null
          this.gridHeatmapError = error?.message || '热力图查询失败'
          this.gridHeatmaps = null
          return null
        } finally {
          if (state.sequence === requestId) {
            this.gridHeatmapLoading = false
            state.promise = null
          }
        }
      })()
      state.promise = operation
      return await operation
    },

    _isCurrentPair(key) {
      return key === comparisonPairKey(this.currentBatch, this.baselineBatch)
    },

    async pollComparison(taskId, pairKey) {
      const state = runtime(this).polling
      state.controller?.abort()
      const controller = new AbortController()
      const requestId = ++state.sequence
      state.controller = controller
      try {
        while (state.sequence === requestId && this._isCurrentPair(pairKey)) {
          await wait(400, controller.signal)
          const task = await api.comparisonTask(taskId, { signal: controller.signal })
          if (state.sequence !== requestId || !this._isCurrentPair(pairKey)) return null
          this.progress = { done: task.done || 0, total: task.total || 0 }
          if (task.status === 'error') throw new Error(task.error || '对比失败')
          if (task.status === 'done') {
            this.running = false
            abortChannel(this, 'lookup')
            return await this.loadGridHeatmaps()
          }
        }
      } catch (error) {
        if (isRequestCancelled(error) || state.sequence !== requestId) return null
        this.running = false
        this.gridHeatmapError = error?.message || '对比失败'
        throw error
      } finally {
        if (state.sequence === requestId) state.controller = null
      }
      return null
    },

    async runComparison({ force = false } = {}) {
      if (!this.canCompare || this.running) return null
      const current = this.currentBatch
      const baseline = this.baselineBatch
      const pairKey = comparisonPairKey(current, baseline)
      const state = runtime(this).creation
      state.controller?.abort()
      const controller = new AbortController()
      const requestId = ++state.sequence
      state.controller = controller
      state.key = pairKey
      this.running = true
      this.progress = { done: 0, total: 0 }
      this.gridHeatmapError = ''
      try {
        const response = await api.createComparison({
          batch_id: current.id,
          ref_batch_id: baseline.id,
          shading_quality: current.shading_quality,
          force,
        }, { signal: controller.signal })
        if (state.sequence !== requestId || !this._isCurrentPair(pairKey)) return null
        if (response.status === 'done') {
          this.running = false
          return await this.loadGridHeatmaps()
        }
        this.gridHeatmaps = {
          current_id: current.id,
          baseline_id: baseline.id,
          current_column_id: qualityColumnKey(current),
          baseline_column_id: qualityColumnKey(baseline),
          exists: true,
          ready: false,
          status: 'running',
          map: {},
          comparison: null,
        }
        return await this.pollComparison(response.task_id, pairKey)
      } catch (error) {
        if (isRequestCancelled(error) || state.sequence !== requestId) return null
        this.gridHeatmapError = error?.message || '对比失败'
        throw error
      } finally {
        if (state.sequence === requestId) {
          state.controller = null
          state.key = ''
        }
        if (state.sequence === requestId
          && this._isCurrentPair(pairKey)
          && runtime(this).polling.controller == null) {
          this.running = false
        }
      }
    },

    async rerunComparison() {
      return await this.runComparison({ force: true })
    },

    cancelGridHeatmapRequest() {
      abortChannel(this, 'creation')
      abortChannel(this, 'lookup')
      abortChannel(this, 'polling')
      this.gridHeatmapLoading = false
      this.running = false
    },

    cancelDataRequests() {
      abortChannel(this, 'availability')
      abortChannel(this, 'grid')
      this.cancelGridHeatmapRequest()
    },

    deactivate() {
      abortChannel(this, 'route')
      this.cancelDataRequests()
    },
  },
})
