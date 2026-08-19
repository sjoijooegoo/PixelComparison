import { defineStore } from 'pinia'

import { api, isRequestCancelled } from '../api'
import {
  SHADING_QUALITY_OPTIONS,
  defaultDateRange,
  inclusiveDateRangeDays,
  isDateRangeAllowed,
} from '../store'
import { useProjectStore } from './projectStore'

const GRID_CACHE_LIMIT = 8
const gridCache = new Map()
const runtimes = new WeakMap()
const shadingQualities = new Set(SHADING_QUALITY_OPTIONS.map((option) => option.value))

function emptyGrid() {
  return { batches: [], rows: [], total: 0 }
}

function runtime(store) {
  if (!runtimes.has(store)) {
    runtimes.set(store, {
      route: { sequence: 0, controller: null },
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

function cloneParams(params) {
  return Object.fromEntries(
    Object.entries(params).map(([key, value]) => [key, Array.isArray(value) ? [...value] : value]),
  )
}

function cacheKey(sceneId, filters) {
  return JSON.stringify({ scene_id: sceneId, ...cloneParams(filters) })
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

function normalizeQuality(value, fallback) {
  if (value === undefined || value === null) return fallback
  if (value === '' || String(value).trim().toLowerCase() === 'all') return ''
  const quality = Number(value)
  return Number.isInteger(quality) && shadingQualities.has(quality) ? quality : fallback
}

function validDate(value) {
  return inclusiveDateRangeDays(value, value) === 1
}

function normalizeDates(value) {
  const values = Array.isArray(value) ? value : [value]
  return [...new Set(
    values
      .flatMap((item) => String(item ?? '').split(','))
      .map((item) => item.trim())
      .filter(validDate),
  )].sort()
}

function routeFilters(project, branchTag, sceneId, requested) {
  const quality = project.settings.default_shading_quality
  const defaults = {
    branch_tag: branchTag,
    scene_id: sceneId,
    shading_quality: (quality === -1 || quality == null) ? '' : quality,
    dateMode: 'range',
    ...defaultDateRange(project.settings.default_date_range_days ?? 7),
    created_dates: [],
  }
  defaults.shading_quality = normalizeQuality(requested.shadingQuality, defaults.shading_quality)
  if (requested.dateMode === 'days') {
    const requestedDates = Array.isArray(requested.createdDates)
      ? requested.createdDates
      : [requested.createdDates].filter((value) => value != null && value !== '')
    const dates = normalizeDates(requestedDates)
    // `dates=` 是用户尚未选择日期的合法空态；只有实际传入但全部非法时才回退默认范围。
    if (!requestedDates.length || dates.length) {
      defaults.dateMode = 'days'
      defaults.created_dates = dates
    }
  } else if (
    requested.dateMode === 'range'
    && isDateRangeAllowed(requested.createdFrom, requested.createdTo)
  ) {
    defaults.created_from = requested.createdFrom
    defaults.created_to = requested.createdTo
  }
  return defaults
}

function normalizedRoute(filters, baselineId = '', currentId = '') {
  return {
    branchTag: filters.branch_tag || 'main',
    sceneId: filters.scene_id || '',
    baselineId,
    currentId,
    shadingQuality: filters.shading_quality,
    dateMode: filters.dateMode,
    createdFrom: filters.created_from,
    createdTo: filters.created_to,
    createdDates: [...filters.created_dates],
  }
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
      ...defaultDateRange(),
      created_dates: [],
    },
    grid: emptyGrid(),
    gridCollapsed: new Set(),
    gridLoading: false,
    gridError: '',
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
      const { dateMode, created_from, created_to, created_dates, ...rest } = state.filters
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
      && String(state.currentBatch.id) !== String(state.baselineBatch.id)
      && state.currentBatch.has_screenshots !== false
      && state.baselineBatch.has_screenshots !== false
      && (state.currentBatch.branch_tag || 'main') === (state.baselineBatch.branch_tag || 'main')
      && state.currentBatch.scene_id === state.baselineBatch.scene_id,
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
        ...defaultDateRange(project.settings.default_date_range_days ?? 7),
        created_dates: [],
      }
    },

    async resolveBatch(id, signal) {
      if (!id) return null
      try {
        return await api.batch(id, { signal })
      } catch (error) {
        if (error?.status === 404) return null
        throw error
      }
    },

    async applyRoute(requested = {}) {
      const { branchTag = 'main', sceneId = '', baselineId = '', currentId = '' } = requested
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

      if (!scene) {
        this.grid = emptyGrid()
        this.initialized = true
        return normalizedRoute(this.filters)
      }

      const rawBaselineId = queryId(baselineId)
      const rawCurrentId = queryId(currentId)
      let [baseline, current] = await Promise.all([
        this.resolveBatch(rawBaselineId, state.controller.signal),
        this.resolveBatch(rawCurrentId, state.controller.signal),
      ])
      if (!isLatest()) return null
      const valid = (batch) => Boolean(
        batch
        && batch.has_screenshots
        && (batch.branch_tag || 'main') === branch
        && batch.scene_id === scene,
      )
      if (!valid(baseline)) baseline = null
      if (!valid(current)) current = null
      if (baseline && current && String(baseline.id) === String(current.id)) baseline = null

      await this.loadGrid()
      if (!isLatest()) return null

      const visible = new Map(this.grid.batches.map((batch) => [String(batch.id), batch]))
      this.baselineBatch = baseline ? visible.get(String(baseline.id)) || null : null
      this.currentBatch = current ? visible.get(String(current.id)) || null : null
      this.initialized = true
      await this.loadGridHeatmaps()
      return normalizedRoute(
        this.filters,
        this.baselineBatch ? String(this.baselineBatch.id) : '',
        this.currentBatch ? String(this.currentBatch.id) : '',
      )
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
      const params = cloneParams(this.requestFilters)
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

    async applyFilters() {
      await this.loadGrid()
      await this.loadGridHeatmaps()
    },

    async resetFilters() {
      const { branch_tag: branchTag, scene_id: sceneId } = this.filters
      this.filters = this.defaultFilters(branchTag, sceneId)
      await this.applyFilters()
    },

    async refresh() {
      await this.loadGrid({ force: true })
      await this.loadGridHeatmaps()
    },

    _clearRolesOutsideGrid() {
      const visible = new Set(this.grid.batches.map((batch) => String(batch.id)))
      if (this.baselineBatch && !visible.has(String(this.baselineBatch.id))) this.baselineBatch = null
      if (this.currentBatch && !visible.has(String(this.currentBatch.id))) this.currentBatch = null
    },

    setRole(batch, role) {
      // 网格接口本身只返回包含截图的批次；旧响应可能没有显式能力字段。
      if (!batch || batch.has_screenshots === false) return
      abortChannel(this, 'creation')
      if (role === 'baseline') {
        if (String(this.currentBatch?.id) === String(batch.id)) this.currentBatch = null
        this.baselineBatch = batch
      } else {
        if (String(this.baselineBatch?.id) === String(batch.id)) this.baselineBatch = null
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
      if (!current || !baseline || String(current.id) === String(baseline.id)) {
        abortChannel(this, 'lookup')
        abortChannel(this, 'polling')
        this.gridHeatmaps = null
        this.gridHeatmapLoading = false
        this.gridHeatmapError = ''
        this.running = false
        return null
      }
      const key = `${current.id}|${baseline.id}`
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
          const response = await api.comparisonLookup(current.id, baseline.id, {
            signal: controller.signal,
          })
          if (state.sequence !== requestId || !this._isCurrentPair(key)) return null
          this.gridHeatmaps = {
            current_id: current.id,
            baseline_id: baseline.id,
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
      return key === `${this.currentBatch?.id || ''}|${this.baselineBatch?.id || ''}`
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
      const pairKey = `${current.id}|${baseline.id}`
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
      abortChannel(this, 'grid')
      this.cancelGridHeatmapRequest()
    },

    deactivate() {
      abortChannel(this, 'route')
      this.cancelDataRequests()
    },
  },
})
