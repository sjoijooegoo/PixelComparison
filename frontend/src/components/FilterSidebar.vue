<script setup>
import { computed } from 'vue'
import { Message } from '@arco-design/web-vue'
import { useStore } from '../store'

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
  Message.success('筛选已应用')
}

async function reset() {
  store.filters = { scene_id: '', platform: '', p4_min: null, p4_max: null, created_from: '', created_to: '', status: '' }
  await apply()
}
</script>

<template>
  <aside class="sidebar card">
    <div class="scroll">
      <div class="head">
        <b>筛选条件</b>
        <a-link @click="reset">清空</a-link>
      </div>

      <div class="group">
        <div class="label">场景ID</div>
        <a-select v-model="store.filters.scene_id" placeholder="全部场景" allow-clear size="small">
          <a-option v-for="s in store.meta.scene_ids" :key="s" :value="s">{{ s }}</a-option>
        </a-select>
      </div>
      <div class="group">
        <div class="label">平台</div>
        <a-select v-model="store.filters.platform" placeholder="全部平台" allow-clear size="small">
          <a-option v-for="p in store.meta.platforms" :key="p" :value="p">{{ p }}</a-option>
        </a-select>
      </div>
      <div class="group">
        <div class="label">P4 版本范围</div>
        <div class="p4-range">
          <a-input-number v-model="store.filters.p4_min" placeholder="最小" size="small"
            :min="0" hide-button />
          <span class="sep">-</span>
          <a-input-number v-model="store.filters.p4_max" placeholder="最大" size="small"
            :min="0" hide-button />
        </div>
      </div>
      <div class="group">
        <div class="label">创建时间</div>
        <a-range-picker size="small" style="width: 100%"
          :model-value="dateRange" @change="onDateChange" />
      </div>

      <a-button type="primary" long @click="apply">应用筛选</a-button>
    </div>
    <div class="foot">
      <a-button long @click="Message.info('当前筛选已保存为视图(示例)')">保存为视图</a-button>
    </div>
  </aside>
</template>

<style scoped>
.sidebar { width: 244px; flex: 0 0 244px; display: flex; flex-direction: column; min-height: 0; }
.scroll { flex: 1; overflow-y: auto; padding: 14px; }
.head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; }
.group { margin-bottom: 14px; }
.label { color: var(--color-text-3); font-size: 12px; margin-bottom: 5px; }
.p4-range { display: flex; align-items: center; gap: 6px; }
.p4-range .sep { color: var(--color-text-4); }
.p4-range :deep(.arco-input-number) { flex: 1; min-width: 0; }
.foot { padding: 12px 14px; border-top: 1px solid var(--color-border-2); }
</style>
