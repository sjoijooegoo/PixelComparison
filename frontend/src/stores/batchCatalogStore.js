import { defineStore } from 'pinia'

import { api } from '../api'
import { PAGE_SIZE, defaultDateRange } from '../store'
import { useProjectStore } from './projectStore'

function cloneParams(params) {
  return Object.fromEntries(
    Object.entries(params).map(([key, value]) => [key, Array.isArray(value) ? [...value] : value]),
  )
}

export const useBatchCatalogStore = defineStore('batchCatalog', {
  state: () => ({
    filters: {
      branch_tag: 'main',
      scene_id: '',
      shading_quality: 5,
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
    initialized: false,
    _requestSequence: 0,
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
      const quality = project.settings.default_shading_quality
      return {
        branch_tag: 'main',
        scene_id: '',
        shading_quality: (quality === -1 || quality == null) ? '' : quality,
        dateMode: 'range',
        ...defaultDateRange(project.settings.default_date_range_days ?? 7),
        created_dates: [],
      }
    },

    async init() {
      if (this.initialized) return
      this.filters = this.defaultFilters()
      await this.loadBatches()
      this.initialized = true
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
      const params = cloneParams({
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

    async applyFilters() {
      this.batchPage = 1
      return await this.loadBatches()
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
      return await this.loadBatches()
    },

    async deleteBatch(id) {
      await api.deleteBatch(id)
      await this.refresh()
    },
  },
})
