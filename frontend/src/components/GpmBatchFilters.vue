<script setup>
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  defaultGpmCapturedRange,
  gpmBatchLocation,
} from '../gpmBatchRoute'
import { vNoNativeTitle } from '../directives/noNativeTitle'
import { useGpmBatchStore } from '../stores/gpmBatchStore'

const store = useGpmBatchStore()
const route = useRoute()
const router = useRouter()

const capturedRange = computed(() => [
  store.filters.capturedFrom,
  store.filters.capturedTo,
])

function target(overrides = {}, page = 1) {
  return gpmBatchLocation({
    returnTo: route.query.return_to || '',
    ...store.filters,
    ...overrides,
    page,
  })
}

function change(field, value) {
  return router.push(target({ [field]: value ?? '' }))
}

function changeRange(value) {
  if (!value?.[0] || !value?.[1]) return
  return router.push(target({
    rangeMode: 'fixed', capturedFrom: value[0], capturedTo: value[1],
  }))
}

function reset() {
  return router.replace(gpmBatchLocation({
    returnTo: route.query.return_to || '',
    branchTag: 'main', platform: '', mapName: '', shadingQuality: '',
    rangeMode: 'rolling', ...defaultGpmCapturedRange(), page: 1,
  }))
}
</script>

<template>
  <section v-no-native-title class="gpm-batch-filters card">
    <label class="filter-field">
      <span>分支</span>
      <a-select class="select-branch" :model-value="store.filters.branchTag" size="small"
        @change="change('branchTag', $event)">
        <a-option v-for="item in store.meta.branch_tags" :key="item" :value="item">
          {{ item }}
        </a-option>
      </a-select>
    </label>
    <label class="filter-field">
      <span>平台</span>
      <a-select class="select-platform" :model-value="store.filters.platform" size="small"
        placeholder="全部平台" allow-clear @change="change('platform', $event)">
        <a-option v-for="item in store.meta.platforms" :key="item" :value="item">
          {{ item }}
        </a-option>
      </a-select>
    </label>
    <label class="filter-field">
      <span>地图名称</span>
      <a-select class="select-scene" :model-value="store.filters.mapName" size="small"
        placeholder="全部地图" allow-clear allow-search @change="change('mapName', $event)">
        <a-option v-for="item in store.meta.maps" :key="item" :value="item">
          {{ item }}
        </a-option>
      </a-select>
    </label>
    <label class="filter-field">
      <span>画质</span>
      <a-select class="select-quality" :model-value="store.filters.shadingQuality" size="small"
        placeholder="全部画质" allow-clear @change="change('shadingQuality', $event)">
        <a-option v-for="item in store.meta.shading_qualities" :key="item.value" :value="item.value">
          {{ item.label }}
        </a-option>
      </a-select>
    </label>
    <label class="filter-field">
      <span>采集时间</span>
      <a-range-picker class="select-range" :model-value="capturedRange" size="small"
        :allow-clear="false" value-format="YYYY-MM-DD" @change="changeRange" />
    </label>
    <a-button class="reset-button" size="small" @click="reset">清空</a-button>
  </section>
</template>

<style scoped>
.gpm-batch-filters {
  flex: 0 0 auto; padding: 10px 14px; display: flex; align-items: center;
  flex-wrap: wrap; gap: 10px 16px; overflow: visible;
}
.filter-field { min-width: 0; display: flex; align-items: center; gap: 6px; }
.filter-field > span { color: var(--color-text-3); font-size: 12px; white-space: nowrap; }
.filter-field :deep(.arco-select-view) { background: var(--color-fill-2); border-color: transparent; }
.filter-field :deep(.select-branch), .filter-field :deep(.select-platform) { width: 120px; }
.filter-field :deep(.select-scene) { width: 280px; }
.filter-field :deep(.select-quality) { width: 100px; }
.filter-field :deep(.select-range) { width: 260px; }
.reset-button { margin-left: auto; }
</style>
