import { defineStore } from 'pinia'

import { api } from '../api'

const emptyCatalog = () => ({
  palette: { id: 'gpm-five-v1', colors: [], labels: [] },
  platforms: [],
  shading_qualities: [],
  metric_scales: [],
  scale_sets: [],
  maps: [],
})

export const useGpmScaleConfigStore = defineStore('gpmScaleConfig', {
  state: () => ({
    catalog: emptyCatalog(),
    loading: false,
    saving: false,
    error: '',
    catalogSequence: 0,
  }),

  actions: {
    async load() {
      const sequence = ++this.catalogSequence
      this.loading = true
      this.error = ''
      try {
        const catalog = await api.gpmScaleCatalog()
        if (sequence === this.catalogSequence) this.catalog = catalog
        return catalog
      } catch (error) {
        if (sequence === this.catalogSequence) {
          this.error = error?.message || '颜色标尺配置加载失败'
        }
        throw error
      } finally {
        if (sequence === this.catalogSequence) this.loading = false
      }
    },

    async mutate(request) {
      this.catalogSequence += 1
      this.loading = false
      this.saving = true
      this.error = ''
      try {
        const result = await request()
        await this.load()
        return result
      } catch (error) {
        this.error = error?.message || '颜色标尺配置保存失败'
        throw error
      } finally {
        this.saving = false
      }
    },

    saveMetricScale(scaleId, body) {
      return this.mutate(() => (scaleId
        ? api.updateGpmMetricScale(scaleId, body)
        : api.createGpmMetricScale(body)))
    },

    removeMetricScale(scaleId) {
      return this.mutate(() => api.deleteGpmMetricScale(scaleId))
    },

    saveScaleSet(scaleSetId, body) {
      return this.mutate(() => (scaleSetId
        ? api.updateGpmMetricScaleSet(scaleSetId, body)
        : api.createGpmMetricScaleSet(body)))
    },

    removeScaleSet(scaleSetId) {
      return this.mutate(() => api.deleteGpmMetricScaleSet(scaleSetId))
    },

    saveMapBindings(mapName, body) {
      return this.mutate(() => api.updateGpmMapScaleBindings(mapName, body))
    },
  },
})
