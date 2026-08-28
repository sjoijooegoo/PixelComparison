<script setup>
import { computed, reactive, ref } from 'vue'

import GpmDetailNode from './GpmDetailNode.vue'

const props = defineProps({
  point: { type: Object, default: null },
  summaryPoint: { type: Object, default: null },
  metricKey: { type: String, default: '' },
  metricName: { type: String, default: '' },
  loading: { type: Boolean, default: false },
  error: { type: String, default: '' },
})

const openRootIndex = ref(null)
const expansionState = reactive({})
const tableSortState = reactive({})
const headerPoint = computed(() => props.summaryPoint || props.point)
const metricValue = computed(() => headerPoint.value?.heat_map_data?.[props.metricKey])
// 展开状态属于当前页面会话，不属于某一个点位。切换点位或重新获取详情时
// 按相同结构路径恢复；浏览器刷新导致组件重新挂载后自然清空。

function formatValue(value) {
  const number = Number(value)
  if (!Number.isFinite(number)) return value ?? '—'
  return new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 2 }).format(number)
}

function formatCoordinate(value) {
  const number = Number(value)
  if (!Number.isFinite(number)) return value ?? '—'
  return String(Number(number.toFixed(2)))
}

function pointLabel(point) {
  const value = point?.index ?? point?.id
  return value == null ? '—' : String(value).padStart(2, '0')
}

function toggleRoot(index) {
  openRootIndex.value = openRootIndex.value === index ? null : index
}
</script>

<template>
  <section class="detail-card card">
    <header>
      <div v-if="headerPoint" class="point-meta" aria-label="当前点位信息">
        <span class="meta-block point-id">
          <small>序号</small>
          <b>{{ pointLabel(headerPoint) }}</b>
        </span>
        <span class="meta-block coordinates">
          <small>坐标</small>
          <b>X: {{ formatCoordinate(headerPoint.position?.[0]) }}, Y: {{ formatCoordinate(headerPoint.position?.[1]) }}</b>
        </span>
        <span v-if="metricKey" class="meta-block metric-value">
          <small>{{ metricName || metricKey }}</small>
          <b>{{ formatValue(metricValue) }}</b>
        </span>
      </div>
    </header>
    <div v-if="loading && !point" class="panel-state"><a-spin /> 正在加载点位详情</div>
    <div v-else-if="error && !point" class="panel-state error">{{ error }}</div>
    <div v-else-if="point" class="detail-list">
      <GpmDetailNode v-for="(node, index) in point.detail_data || []"
        :key="`${point.id}-${node.name}-${index}`" :node="node"
        :expanded="openRootIndex === index" :expansion-state="expansionState"
        :table-sort-state="tableSortState"
        :node-path="String(index)" @toggle="toggleRoot(index)" />
    </div>
    <div v-else class="panel-state">选择地图点位或下方截图查看详细数据</div>
  </section>
</template>

<style scoped>
.detail-card { display: flex; flex-direction: column; min-width: 0; min-height: 0; }
header {
  height: 43px; flex: 0 0 43px; padding: 7px 14px;
  display: flex; align-items: center;
  border-bottom: 1px solid var(--color-border-1);
}
.point-meta {
  min-width: 0; display: flex; align-items: center; justify-content: flex-start; gap: 12px;
}
.meta-block {
  flex: 0 0 auto; width: fit-content; min-width: 0;
  display: flex; align-items: baseline; gap: 5px;
  font-variant-numeric: tabular-nums; white-space: nowrap;
}
.meta-block + .meta-block { padding-left: 12px; border-left: 1px solid var(--color-border-2); }
.meta-block small { color: var(--color-text-4); font-size: 12px; line-height: 18px; }
.meta-block b {
  overflow: hidden; color: var(--color-text-2); font-size: 13px; font-weight: 500;
  line-height: 18px; text-overflow: ellipsis;
}
.coordinates { max-width: 220px; }
.detail-list { flex: 1; min-height: 0; overflow: auto; padding: 6px 8px 10px; }
.panel-state { flex: 1; display: flex; gap: 8px; align-items: center; justify-content: center; color: var(--color-text-3); }
.panel-state.error { color: rgb(var(--red-6)); }
</style>
