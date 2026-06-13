import { defineStore } from 'pinia'
import { api } from './api'

export const PAGE_SIZE = 10

export const STATUS_META = {
  fail: { label: '失败', color: 'red' },
  warn: { label: '警告', color: 'orange' },
  pass: { label: '通过', color: 'green' },
  added: { label: '新增', color: 'arcoblue' },
  missing: { label: '缺失', color: 'gray' },
}

export const useStore = defineStore('shotdiff', {
  state: () => ({
    meta: { projects: [], platforms: [], branches: [], baselines: [] },
    filters: { project: '', platform: '', branch: '', baseline: '', status: '' },
    comparisons: [],
    comparisonTotal: 0,
    selectedComparison: null,

    sceneFilter: '',     // '' | fail | warn | pass | added | missing
    sceneSearch: '',
    page: 1,
    scenes: [],
    sceneTotal: 0,
    counts: { all: 0, fail: 0, warn: 0, pass: 0, added: 0, missing: 0 },

    sceneSort: 'name',   // name(场景名) | diff(差异率降序)

    detail: null,        // /api/items/{id} 响应
    viewMode: 'tri',     // tri | slide | raw
    zoom: 100,
    loading: false,
  }),

  actions: {
    async init() {
      this.meta = await api.meta()
      await this.loadComparisons()
      if (this.comparisons.length) await this.selectComparison(this.comparisons[0])
    },

    async loadComparisons() {
      const { items, total } = await api.comparisons(this.filters)
      this.comparisons = items
      this.comparisonTotal = total
    },

    async createComparison(batchId, refBatchId) {
      const dto = await api.createComparison({ batch_id: batchId, ref_batch_id: refBatchId })
      await this.loadComparisons()
      await this.selectComparison(dto)
      return dto
    },

    async selectComparison(comparison) {
      this.selectedComparison = comparison
      this.page = 1
      this.sceneFilter = ''
      this.sceneSearch = ''
      await this.loadScenes()
      if (this.scenes.length) await this.selectScene(this.scenes[0].id)
      else this.detail = null
    },

    async toggleSceneSort() {
      this.sceneSort = this.sceneSort === 'diff' ? 'name' : 'diff'
      this.page = 1
      await this.loadScenes()
    },

    async loadScenes() {
      if (!this.selectedComparison) return
      this.loading = true
      try {
        const data = await api.scenes(this.selectedComparison.id, {
          status: this.sceneFilter,
          q: this.sceneSearch,
          sort: this.sceneSort,
          page: this.page,
          page_size: PAGE_SIZE,
        })
        this.scenes = data.items
        this.sceneTotal = data.total
        this.counts = data.counts
      } finally {
        this.loading = false
      }
    },

    async selectScene(id) {
      this.detail = await api.item(id)
    },

    async gotoPrev() {
      if (this.detail?.prev_id) await this.selectScene(this.detail.prev_id)
    },
    async gotoNext() {
      if (this.detail?.next_id) await this.selectScene(this.detail.next_id)
    },
  },
})
