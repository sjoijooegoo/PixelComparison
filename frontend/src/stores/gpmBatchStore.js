import { defineStore } from 'pinia'
import { api } from '../api'
import { PAGE_SIZE } from '../store'

function optionValues(items) {
  return (items || []).map((item) => item?.value ?? item)
}

function keep(value, items) {
  return optionValues(items).includes(value) ? value : ''
}

export const useGpmBatchStore = defineStore('gpmBatch', {
  state: () => ({
    meta: { branch_tags: ['main'], platforms: [], scene_ids: [], shading_qualities: [] },
    filters: {
      branchTag: 'main', platform: '', sceneId: '', shadingQuality: '',
      capturedFrom: '', capturedTo: '',
    },
    batches: [],
    batchTotal: 0,
    batchPage: 1,
    batchPageSize: PAGE_SIZE,
    loading: false,
    error: '',
    initialized: false,
    requestSequence: 0,
    metaSequence: 0,
    routeSequence: 0,
  }),

  getters: {
    requestParams: (state) => ({
      branch_tag: state.filters.branchTag,
      platform: state.filters.platform,
      scene_id: state.filters.sceneId,
      shading_quality: state.filters.shadingQuality,
      captured_from: state.filters.capturedFrom,
      captured_to: state.filters.capturedTo,
      page: state.batchPage,
      page_size: state.batchPageSize,
    }),
  },

  actions: {
    async loadMeta(branchTag = this.filters.branchTag || 'main') {
      const sequence = ++this.metaSequence
      const data = await api.gpmHeatmapUploadMeta({ branch_tag: branchTag })
      if (sequence === this.metaSequence) this.meta = data
      return data
    },

    async applyRoute(requested) {
      const routeSequence = ++this.routeSequence
      const isLatest = () => routeSequence === this.routeSequence
      let branchTag = String(requested.branchTag || 'main').trim().toLowerCase()
      let meta = await this.loadMeta(branchTag)
      if (!isLatest()) return null
      if (!meta.branch_tags.includes(branchTag)) {
        branchTag = 'main'
        meta = await this.loadMeta('main')
        if (!isLatest()) return null
      }
      this.filters.branchTag = branchTag
      this.filters.platform = keep(requested.platform || '', meta.platforms)
      this.filters.sceneId = keep(requested.sceneId || '', meta.scene_ids)
      this.filters.shadingQuality = keep(requested.shadingQuality, meta.shading_qualities)
      this.filters.capturedFrom = requested.capturedFrom || ''
      this.filters.capturedTo = requested.capturedTo || ''
      this.batchPage = Number(requested.page) || 1
      await this.loadBatches()
      if (!isLatest()) return null
      this.initialized = true
      return this.routeState(requested.returnTo)
    },

    routeState(returnTo = '') {
      return {
        returnTo,
        ...this.filters,
        page: this.batchPage,
      }
    },

    async loadBatches() {
      const sequence = ++this.requestSequence
      this.loading = true
      this.error = ''
      try {
        const result = await api.gpmHeatmapUploads(this.requestParams)
        if (sequence !== this.requestSequence) return null
        this.batches = result.items || []
        this.batchTotal = Number(result.total) || 0
        return result
      } catch (error) {
        if (sequence !== this.requestSequence) return null
        this.error = error?.message || '热力图批次加载失败'
        throw error
      } finally {
        if (sequence === this.requestSequence) this.loading = false
      }
    },

    async refresh() {
      const meta = await this.loadMeta(this.filters.branchTag)
      this.filters.platform = keep(this.filters.platform, meta.platforms)
      this.filters.sceneId = keep(this.filters.sceneId, meta.scene_ids)
      this.filters.shadingQuality = keep(this.filters.shadingQuality, meta.shading_qualities)
      return await this.loadBatches()
    },

    async deleteBatch(batchId, branchTag) {
      await api.deleteGpmHeatmapUpload(batchId, branchTag)
      const lastItemOnPage = this.batches.length === 1 && this.batchPage > 1
      if (lastItemOnPage) this.batchPage -= 1
      await this.refresh()
    },

    deactivate() {
      this.requestSequence += 1
      this.metaSequence += 1
      this.routeSequence += 1
      this.loading = false
    },
  },
})
