import { defineStore } from 'pinia'

import { api, isRequestCancelled } from '../api'
import {
  PAGE_SIZE,
  cloneRequestParams,
  defaultDateRange,
  isDateRangeAllowed,
  normalizeSelectedDates,
  normalizeShadingQuality,
} from '../store'
import { useProjectStore } from './projectStore'

const availabilityRuntimes = new WeakMap()

function availabilityRuntime(store) {
  if (!availabilityRuntimes.has(store)) {
    availabilityRuntimes.set(store, { sequence: 0, controller: null })
  }
  return availabilityRuntimes.get(store)
}

function abortAvailability(store) {
  const state = availabilityRuntime(store)
  state.controller?.abort()
  state.controller = null
  state.sequence += 1
}

function routeFilters(project, requested) {
  const requestedBranch = String(requested.branchTag || 'main').trim().toLowerCase()
  const branchTag = project.meta.branch_tags.includes(requestedBranch) ? requestedBranch : 'main'
  const sceneId = project.meta.scene_ids.includes(requested.sceneId) ? requested.sceneId : ''
  const filters = {
    branch_tag: branchTag,
    scene_id: sceneId,
    shading_quality: normalizeShadingQuality(requested.shadingQuality),
    dateMode: 'range',
    ...defaultDateRange(project.settings.default_date_range_days ?? 7),
    created_dates: [],
  }
  if (requested.dateMode === 'days') {
    const requestedDates = Array.isArray(requested.createdDates)
      ? requested.createdDates
      : [requested.createdDates].filter((value) => value != null && value !== '')
    const dates = normalizeSelectedDates(requestedDates)
    if (!requestedDates.length || dates.length) {
      filters.dateMode = 'days'
      filters.created_dates = dates
    }
  } else if (
    requested.dateMode === 'range'
    && isDateRangeAllowed(requested.createdFrom, requested.createdTo)
  ) {
    filters.created_from = requested.createdFrom
    filters.created_to = requested.createdTo
  }
  return filters
}

function normalizePage(value) {
  const page = Number(value)
  return Number.isInteger(page) && page > 0 ? page : 1
}

function normalizedRoute(filters, page) {
  return {
    branchTag: filters.branch_tag,
    sceneId: filters.scene_id,
    shadingQuality: filters.shading_quality,
    dateMode: filters.dateMode,
    createdFrom: filters.created_from,
    createdTo: filters.created_to,
    createdDates: [...filters.created_dates],
    page,
  }
}

export const useBatchCatalogStore = defineStore('batchCatalog', {
  state: () => ({
    filters: {
      branch_tag: 'main',
      scene_id: '',
      shading_quality: '',
      dateMode: 'range',
      ...defaultDateRange(),
      created_dates: [],
    },
    batches: [],
    batchTotal: 0,
    batchPage: 1,
    batchPageSize: PAGE_SIZE,
    batchLoading: false,
    batchError: '',
    availableSceneIds: null,
    sceneAvailabilityError: '',
    initialized: false,
    _requestSequence: 0,
    _routeSequence: 0,
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
  },

  actions: {
    defaultFilters() {
      const project = useProjectStore()
      return {
        branch_tag: 'main',
        scene_id: '',
        shading_quality: '',
        dateMode: 'range',
        ...defaultDateRange(project.settings.default_date_range_days ?? 7),
        created_dates: [],
      }
    },

    async init(requested = {}) {
      if (this.initialized) return normalizedRoute(this.filters, this.batchPage)
      return await this.applyRoute(requested)
    },

    async applyRoute(requested = {}) {
      const routeId = ++this._routeSequence
      const project = useProjectStore()
      this.filters = routeFilters(project, requested)
      this.batchPage = normalizePage(requested.page)
      await Promise.all([this.loadBatches(), this.loadSceneAvailability()])
      if (routeId !== this._routeSequence) return null
      this.initialized = true
      return normalizedRoute(this.filters, this.batchPage)
    },

    async loadBatches() {
      const requestId = ++this._requestSequence
      this.batchLoading = true
      this.batchError = ''
      if (this.hasEmptyDateSelection) {
        this.batches = []
        this.batchTotal = 0
        this.batchLoading = false
        return { items: [], total: 0 }
      }
      const params = cloneRequestParams({
        ...this.requestFilters,
        page: this.batchPage,
        page_size: this.batchPageSize,
      })
      try {
        const result = await api.batches(params)
        if (requestId !== this._requestSequence) return null
        this.batches = result.items
        this.batchTotal = result.total
        return result
      } catch (error) {
        if (requestId !== this._requestSequence) return null
        this.batchError = error?.message || '批次列表加载失败'
        throw error
      } finally {
        if (requestId === this._requestSequence) this.batchLoading = false
      }
    },

    async loadSceneAvailability() {
      const state = availabilityRuntime(this)
      state.controller?.abort()
      const controller = new AbortController()
      const requestId = ++state.sequence
      state.controller = controller
      this.availableSceneIds = null
      this.sceneAvailabilityError = ''
      if (this.hasEmptyDateSelection) {
        this.availableSceneIds = []
        state.controller = null
        return { scene_ids: [] }
      }
      const filters = cloneRequestParams(this.requestFilters)
      delete filters.scene_id
      try {
        const result = await api.sceneAvailability({
          capability: 'batches',
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
        if (state.sequence === requestId) state.controller = null
      }
    },

    async applyFilters() {
      this.batchPage = 1
      const [result] = await Promise.all([
        this.loadBatches(),
        this.loadSceneAvailability(),
      ])
      return result
    },

    async changeBranch(branchTag) {
      const project = useProjectStore()
      const requested = String(branchTag || 'main').trim().toLowerCase()
      this.filters.branch_tag = project.meta.branch_tags.includes(requested) ? requested : 'main'
      return await this.applyFilters()
    },

    async resetFilters() {
      this.filters = this.defaultFilters()
      return await this.applyFilters()
    },

    async refresh({ refreshMeta = true } = {}) {
      const project = useProjectStore()
      if (refreshMeta) await project.loadMeta()
      const [result] = await Promise.all([
        this.loadBatches(),
        this.loadSceneAvailability(),
      ])
      return result
    },

    async deleteBatch(id) {
      await api.deleteBatch(id)
      await this.refresh()
    },

    deactivate() {
      abortAvailability(this)
      this._routeSequence += 1
      this._requestSequence += 1
      this.batchLoading = false
    },
  },
})
