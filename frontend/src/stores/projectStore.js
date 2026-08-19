import { defineStore } from 'pinia'

import { api } from '../api'

const DEFAULT_META = {
  branch_tags: ['main'],
  scene_ids: [],
  scene_data_flags: {},
  unlisted_scene_ids: [],
  scene_catalog_configured: false,
  show_unlisted_scene_ids: false,
  platforms: [],
  baselines: [],
}

const DEFAULT_SETTINGS = {
  pixel_diff_threshold: 8,
  fail_threshold: 2.0,
  warn_threshold: 0.3,
  heatmap_blur: 6,
  heatmap_sensitivity: 0.25,
  heatmap_method: 'enhanced',
  heatmap_norm_scale: 80.0,
  heatmap_gamma: 1.4,
  heatmap_density_radius: 16.0,
  heatmap_density_floor: 0.2,
  default_shading_quality: 5,
  default_date_range_days: 7,
  filter_shading_qualities: [5, 4, 3, 2, 1, 0],
  scene_id_order: null,
  show_unlisted_scene_ids: false,
}

let initialization = null

export const useProjectStore = defineStore('project', {
  state: () => ({
    meta: { ...DEFAULT_META },
    settings: { ...DEFAULT_SETTINGS },
    uploadVisible: false,
    initialized: false,
    initializing: false,
    initError: '',
  }),

  actions: {
    async init() {
      if (this.initialized) return
      if (initialization) return await initialization
      initialization = this._initialize()
      try {
        return await initialization
      } finally {
        initialization = null
      }
    },

    async _initialize() {
      this.initializing = true
      this.initError = ''
      try {
        await Promise.all([this.loadMeta(), this.loadSettings()])
        this.initialized = true
      } catch (error) {
        this.initialized = false
        this.initError = error?.message || '初始化失败，请重试'
        throw error
      } finally {
        this.initializing = false
      }
    },

    async loadMeta() {
      const next = await api.meta()
      this.meta = { ...DEFAULT_META, ...next }
      if (!this.meta.branch_tags.includes('main')) {
        this.meta.branch_tags = ['main', ...this.meta.branch_tags]
      }
      return this.meta
    },

    async loadSettings() {
      this.settings = { ...DEFAULT_SETTINGS, ...(await api.settings()) }
      return this.settings
    },

    async saveSettings(patch) {
      this.settings = { ...DEFAULT_SETTINGS, ...(await api.saveSettings(patch)) }
      return this.settings
    },
  },
})
