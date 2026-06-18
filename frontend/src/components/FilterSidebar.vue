<script setup>
import { computed } from 'vue'
import { useStore, SHADING_QUALITY_OPTIONS } from '../store'

const store = useStore()

// 创建时间范围:绑定到 filters.created_from/created_to(YYYY-MM-DD)
const dateRange = computed(() => {
  const { created_from, created_to } = store.filters
  return created_from && created_to ? [created_from, created_to] : undefined
})

// 任意筛选项变更即自动应用(静默)
async function applyNow() {
  store.batchPage = 1
  await store.loadBatches()
  if (store.batchView === 'grid') await store.loadGrid()
}

function onDateChange(v) {
  store.filters.created_from = v?.[0] || ''
  store.filters.created_to = v?.[1] || ''
  applyNow()
}

async function reset() {
  store.filters = { scene_id: '', shading_quality: null, created_from: '', created_to: '', status: '' }
  await applyNow()
}
</script>

<template>
  <div class="filter-bar card">
    <div class="field">
      <span class="label">场景ID</span>
      <a-select v-model="store.filters.scene_id" placeholder="全部场景" allow-clear size="small"
        style="width: 320px" @change="applyNow">
        <a-option v-for="s in store.meta.scene_ids" :key="s" :value="s">{{ s }}</a-option>
      </a-select>
    </div>
    <div class="field">
      <span class="label">画质</span>
      <a-select v-model="store.filters.shading_quality" placeholder="全部画质" allow-clear size="small"
        style="width: 110px" @change="applyNow">
        <a-option v-for="q in SHADING_QUALITY_OPTIONS" :key="q.value" :value="q.value">{{ q.label }}</a-option>
      </a-select>
    </div>
    <div class="field">
      <span class="label">创建时间</span>
      <a-range-picker size="small" style="width: 230px" :model-value="dateRange" @change="onDateChange" />
    </div>
    <div class="spacer"></div>
    <a-button size="small" @click="reset">清空</a-button>
  </div>
</template>

<style scoped>
.filter-bar {
  flex: 0 0 auto;
  display: flex; flex-wrap: wrap; align-items: center;
  gap: 10px 16px; padding: 10px 14px;
}
.field { display: flex; align-items: center; gap: 6px; }
.field .label { color: var(--color-text-3); font-size: 12px; white-space: nowrap; }
.spacer { flex: 1; }
</style>
