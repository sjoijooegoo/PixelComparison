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

    // 顶部:原始批次列表
    batches: [],
    batchTotal: 0,
    // 对比的两侧选择(角色)
    currentBatch: null,   // 对比批次(待检查)
    baselineBatch: null,  // 基线批次(参照)

    // 运行后的活动对比
    selectedComparison: null,
    running: false,

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

  getters: {
    canCompare: (s) =>
      !!(s.currentBatch && s.baselineBatch && s.currentBatch.id !== s.baselineBatch.id),
  },

  actions: {
    async init() {
      this.meta = await api.meta()
      await this.loadBatches()
    },

    async loadBatches() {
      const { items, total } = await api.batches(this.filters)
      this.batches = items
      this.batchTotal = total
    },

    // role: 'current'(对比) | 'baseline'(基线)
    setRole(batch, role) {
      const other = role === 'current' ? this.baselineBatch : this.currentBatch
      // 取消同一批次的另一角色,避免自比
      if (other && other.id === batch.id) {
        if (role === 'current') this.baselineBatch = null
        else this.currentBatch = null
      }
      if (role === 'current') this.currentBatch = batch
      else this.baselineBatch = batch
    },

    clearRole(role) {
      if (role === 'current') this.currentBatch = null
      else this.baselineBatch = null
    },

    async runComparison() {
      if (!this.canCompare) return
      this.running = true
      try {
        const dto = await api.createComparison({
          batch_id: this.currentBatch.id,
          ref_batch_id: this.baselineBatch.id,
        })
        await this.openComparison(dto)
        return dto
      } finally {
        this.running = false
      }
    },

    async openComparison(comparison) {
      this.selectedComparison = comparison
      this.page = 1
      this.sceneSearch = ''
      this.sceneSort = 'name'
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
