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
    uploadingMap: '',
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

    async mutate(request, reconcile) {
      this.catalogSequence += 1
      this.loading = false
      this.saving = true
      this.error = ''
      try {
        const result = await request()
        reconcile?.(result)
        try {
          await this.load()
        } catch (error) {
          // 命令已在后端提交，不能因随后的目录刷新失败而误报“保存失败”。
          // 先保留局部合并后的服务器返回值，用户可继续操作或手动刷新。
          this.error = `配置已保存，但列表刷新失败：${error?.message || '请稍后重试'}`
        }
        return result
      } catch (error) {
        this.error = error?.message || '颜色标尺配置保存失败'
        throw error
      } finally {
        this.saving = false
      }
    },

    saveMetricScale(scaleId, body) {
      return this.mutate(() => (scaleId != null
        ? api.updateGpmMetricScale(scaleId, body)
        : api.createGpmMetricScale(body)), (saved) => {
        const items = this.catalog.metric_scales || []
        const index = items.findIndex((item) => item.id === saved.id)
        this.catalog.metric_scales = index >= 0
          ? items.map((item, itemIndex) => (itemIndex === index ? saved : item))
          : [...items, saved].sort((left, right) => left.id - right.id)
      })
    },

    removeMetricScale(scaleId) {
      return this.mutate(() => api.deleteGpmMetricScale(scaleId), () => {
        this.catalog.metric_scales = (this.catalog.metric_scales || [])
          .filter((item) => item.id !== scaleId)
      })
    },

    saveScaleSet(scaleSetId, body) {
      return this.mutate(() => (scaleSetId != null
        ? api.updateGpmMetricScaleSet(scaleSetId, body)
        : api.createGpmMetricScaleSet(body)), (saved) => {
        const items = this.catalog.scale_sets || []
        const index = items.findIndex((item) => item.id === saved.id)
        this.catalog.scale_sets = index >= 0
          ? items.map((item, itemIndex) => (itemIndex === index ? saved : item))
          : [...items, saved].sort((left, right) => left.id - right.id)
      })
    },

    removeScaleSet(scaleSetId) {
      return this.mutate(() => api.deleteGpmMetricScaleSet(scaleSetId), () => {
        this.catalog.scale_sets = (this.catalog.scale_sets || [])
          .filter((item) => item.id !== scaleSetId)
      })
    },

    async saveMapConfiguration({ mapName, configuration, image }) {
      this.catalogSequence += 1
      this.loading = false
      this.saving = true
      this.uploadingMap = image ? mapName : ''
      this.error = ''
      try {
        const saved = await api.saveGpmMapConfiguration(mapName, configuration, image)
        const maps = this.catalog.maps || []
        const index = maps.findIndex((item) => item.map_name === saved.map_name)
        this.catalog.maps = index >= 0
          ? maps.map((item, itemIndex) => (itemIndex === index ? saved : item))
          : [...maps, saved].sort((left, right) => left.id - right.id)
        try {
          await this.load()
        } catch (error) {
          this.error = `地图已保存，但列表刷新失败：${error?.message || '请稍后重试'}`
        }
        return saved
      } catch (error) {
        this.error = error?.message || '地图配置保存失败'
        throw error
      } finally {
        this.saving = false
        this.uploadingMap = ''
      }
    },
  },
})
