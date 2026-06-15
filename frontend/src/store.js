import { defineStore } from 'pinia'
import { api } from './api'

export const PAGE_SIZE = 10   // 默认每页条数;实际由场景列表按可用高度动态覆盖

export const STATUS_META = {
  fail: { label: '失败', color: 'red' },
  warn: { label: '警告', color: 'orange' },
  pass: { label: '通过', color: 'green' },
  added: { label: '新增', color: 'arcoblue' },
  missing: { label: '缺失', color: 'gray' },
}

export const useStore = defineStore('shotdiff', {
  state: () => ({
    meta: { scene_ids: [], platforms: [], baselines: [] },
    filters: { scene_id: '', platform: '', p4_min: null, p4_max: null, status: '' },

    // 顶部 tab:batch(批次管理) | 对比结果 | 基线管理 | 项目设置
    activeTab: 'batch',

    // 顶部:原始批次列表
    batches: [],
    batchTotal: 0,
    // 对比的两侧选择(角色)
    currentBatch: null,   // 对比批次(待检查)
    baselineBatch: null,  // 基线批次(参照)

    // 历史对比列表(对比结果页左侧)
    comparisons: [],
    // 运行后的活动对比
    selectedComparison: null,
    running: false,

    sceneSearch: '',
    page: 1,
    pageSize: PAGE_SIZE,   // 由 SceneList 按列表区可用高度动态设置
    scenes: [],
    sceneTotal: 0,
    counts: { all: 0, fail: 0, warn: 0, pass: 0, added: 0, missing: 0 },
    sceneSort: 'name',   // name(场景名) | diff(差异率降序)

    detail: null,        // /api/items/{id} 响应
    viewMode: 'tri',     // tri(三视图) | slide(滑动对比)
    loading: false,

    // 对比算法配置(项目设置页可改);默认与后端 DEFAULT_SETTINGS 一致
    settings: {
      pixel_diff_threshold: 8,
      fail_threshold: 2.0,
      warn_threshold: 0.3,
      heatmap_blur: 6,
      heatmap_sensitivity: 0.25,
    },
  }),

  getters: {
    canCompare: (s) =>
      !!(s.currentBatch && s.baselineBatch && s.currentBatch.id !== s.baselineBatch.id),
  },

  actions: {
    async init() {
      this.meta = await api.meta()
      await this.loadSettings()
      await this.loadBatches()
    },

    async loadSettings() {
      this.settings = await api.settings()
    },

    async saveSettings(patch) {
      this.settings = await api.saveSettings(patch)
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

    async loadComparisons() {
      const { items } = await api.comparisons(this.filters)
      this.comparisons = items
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
        await this.loadComparisons()   // 刷新历史(可能新增了一条)
        this.activeTab = '对比结果'    // 发起对比后自动跳到结果页
        return dto
      } finally {
        this.running = false
      }
    },

    // 强制重算当前对比(批次截图变更等场景)
    async rerunComparison() {
      const c = this.selectedComparison
      if (!c) return
      this.running = true
      try {
        const dto = await api.createComparison({
          batch_id: c.batch_id,
          ref_batch_id: c.ref_batch_id,
          force: true,
        })
        await this.openComparison(dto)
        await this.loadComparisons()
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
          page_size: this.pageSize,
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
