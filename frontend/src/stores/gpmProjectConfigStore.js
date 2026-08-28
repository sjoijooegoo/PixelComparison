import { defineStore } from 'pinia'
import { api } from '../api'

const emptyCatalog = () => ({
  latest_import: null,
  maps: [],
  summary: { total: 0, configured: 0, missing: 0 },
})

export const useGpmProjectConfigStore = defineStore('gpmProjectConfig', {
  state: () => ({
    catalog: emptyCatalog(),
    loading: false,
    importing: false,
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
        const catalog = await api.gpmProjectConfig()
        if (sequence === this.catalogSequence) this.catalog = catalog
        return catalog
      } catch (error) {
        if (sequence === this.catalogSequence) {
          this.error = error?.message || '地图配置加载失败'
        }
        throw error
      } finally {
        if (sequence === this.catalogSequence) this.loading = false
      }
    },

    async importConfig(file) {
      const sequence = ++this.catalogSequence
      this.loading = false
      this.importing = true
      this.error = ''
      try {
        const catalog = await api.importGpmProjectConfig(file)
        if (sequence === this.catalogSequence) this.catalog = catalog
        return catalog
      } catch (error) {
        this.error = error?.message || '地图清单导入失败'
        throw error
      } finally {
        this.importing = false
      }
    },

    async uploadImage(mapName, file) {
      this.uploadingMap = mapName
      this.error = ''
      try {
        const result = await api.uploadGpmProjectMapImage(mapName, file)
        await this.load()
        return result
      } catch (error) {
        this.error = error?.message || '地图图片上传失败'
        throw error
      } finally {
        this.uploadingMap = ''
      }
    },
  },
})
