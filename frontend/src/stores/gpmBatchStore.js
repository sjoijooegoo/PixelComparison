import { defineStore } from 'pinia'
import { api } from '../api'
import {
  gpmMapValues,
  mergeGpmPlatforms,
  mergeGpmQualities,
} from '../gpmHeatmap/filterOptions'
import { defaultGpmCapturedRange } from '../gpmBatchRoute'
import { PAGE_SIZE } from '../store'

function optionValues(items) {
  return (items || []).map((item) => item?.value ?? item)
}

function keep(value, items) {
  return optionValues(items).includes(value) ? value : ''
}

export const useGpmBatchStore = defineStore('gpmBatch', {
  state: () => ({
    meta: { branch_tags: ['main'], platforms: [], maps: [], shading_qualities: [] },
    filters: {
      branchTag: 'main', platform: '', mapName: '', shadingQuality: '',
      rangeMode: 'rolling', capturedFrom: '', capturedTo: '',
    },
    batches: [],
    batchTotal: 0,
    batchPage: 1,
    batchPageSize: PAGE_SIZE,
    focusBatchId: '',
    locationMessage: '',
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
      map_name: state.filters.mapName,
      shading_quality: state.filters.shadingQuality,
      captured_from: state.filters.capturedFrom,
      captured_to: state.filters.capturedTo,
      page: state.batchPage,
      page_size: state.batchPageSize,
      ...(state.focusBatchId ? { locate_batch_id: state.focusBatchId } : {}),
    }),
  },

  actions: {
    async loadMeta(branchTag = this.filters.branchTag || 'main') {
      const sequence = ++this.metaSequence
      const heatmapMeta = await api.gpmHeatmapCatalog({ branch_tag: branchTag })
      const data = {
        branch_tags: heatmapMeta.branch_tags || ['main'],
        platforms: mergeGpmPlatforms(heatmapMeta.platforms || []),
        maps: gpmMapValues(heatmapMeta.maps),
        shading_qualities: mergeGpmQualities(heatmapMeta.shading_qualities || []),
      }
      if (sequence === this.metaSequence) this.meta = data
      return data
    },

    async applyRoute(requested) {
      const routeSequence = ++this.routeSequence
      // 切换筛选后，即使新元数据尚未返回，旧定位响应也不能再修改页码和高亮。
      this.requestSequence += 1
      this.loading = false
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
      this.filters.mapName = keep(requested.mapName || '', meta.maps)
      this.filters.shadingQuality = keep(requested.shadingQuality, meta.shading_qualities)
      this.filters.capturedFrom = requested.capturedFrom || ''
      this.filters.capturedTo = requested.capturedTo || ''
      this.filters.rangeMode = requested.rangeMode === 'fixed' ? 'fixed' : 'rolling'
      this.batchPage = Number(requested.page) || 1
      this.focusBatchId = requested.focusBatchId || ''
      this.locationMessage = ''
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
        focusBatchId: this.focusBatchId,
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
        this.batchPage = Number(result.page) || this.batchPage
        if (this.focusBatchId && result.located_batch_id !== this.focusBatchId) {
          this.locationMessage = `来源批次 ${this.focusBatchId} 已删除或不在当前筛选范围内`
          this.focusBatchId = ''
        }
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
      if (this.filters.rangeMode === 'rolling') {
        const { capturedFrom, capturedTo } = defaultGpmCapturedRange()
        this.filters.capturedFrom = capturedFrom
        this.filters.capturedTo = capturedTo
      }
      const meta = await this.loadMeta(this.filters.branchTag)
      this.filters.platform = keep(this.filters.platform, meta.platforms)
      this.filters.mapName = keep(this.filters.mapName, meta.maps)
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
