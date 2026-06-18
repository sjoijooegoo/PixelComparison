<script setup>
import { computed } from 'vue'
import { Message } from '@arco-design/web-vue'
import { useStore, SHADING_QUALITY_OPTIONS } from '../store'

const store = useStore()

// 创建时间范围:绑定到 filters.created_from/created_to(YYYY-MM-DD)
const dateRange = computed(() => {
  const { created_from, created_to } = store.filters
  return created_from && created_to ? [created_from, created_to] : undefined
})
function onDateChange(v) {
  store.filters.created_from = v?.[0] || ''
  store.filters.created_to = v?.[1] || ''
}

async function apply() {
  store.batchPage = 1
  await store.loadBatches()
  if (store.batchView === 'grid') await store.loadGrid()
  Message.success('筛选已应用')
}

// 切换场景即时应用(不弹提示,避免频繁打扰)
async function onSceneChange() {
  store.batchPage = 1
  await store.loadBatches()
  if (store.batchView === 'grid') await store.loadGrid()
}

async function reset() {
  store.filters = { scene_id: '', platform: '', shading_quality: null, p4_min: null, p4_max: null, created_from: '', created_to: '', status: '' }
  await apply()
}
</script>

<template>
  <div class="filter-bar card">
    <div class="field">
      <span class="label">场景ID</span>
      <a-select v-model="store.filters.scene_id" placeholder="全部场景" allow-clear size="small"
        style="width: 320px" @change="onSceneChange">
        <a-option v-for="s in store.meta.scene_ids" :key="s" :value="s">{{ s }}</a-option>
      </a-select>
    </div>
    <div class="field">
      <span class="label">P4版本</span>
      <div class="p4-range">
        <a-input-number v-model="store.filters.p4_min" placeholder="最小" size="small" :min="0" hide-button style="width: 88px" />
        <span class="sep">-</span>
        <a-input-number v-model="store.filters.p4_max" placeholder="最大" size="small" :min="0" hide-button style="width: 88px" />
      </div>
    </div>
    <div class="field">
      <span class="label">平台</span>
      <a-select v-model="store.filters.platform" placeholder="全部平台" allow-clear size="small" style="width: 120px">
        <a-option v-for="p in store.meta.platforms" :key="p" :value="p">{{ p }}</a-option>
      </a-select>
    </div>
    <div class="field">
      <span class="label">画质</span>
      <a-select v-model="store.filters.shading_quality" placeholder="全部画质" allow-clear size="small" style="width: 110px">
        <a-option v-for="q in SHADING_QUALITY_OPTIONS" :key="q.value" :value="q.value">{{ q.label }}</a-option>
      </a-select>
    </div>
    <div class="field">
      <span class="label">创建时间</span>
      <a-range-picker size="small" style="width: 230px" :model-value="dateRange" @change="onDateChange" />
    </div>
    <div class="spacer"></div>
    <a-button size="small" @click="reset">清空</a-button>
    <a-button size="small" type="primary" @click="apply">应用筛选</a-button>
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
.p4-range { display: flex; align-items: center; gap: 6px; }
.p4-range .sep { color: var(--color-text-4); }
.spacer { flex: 1; }
</style>
