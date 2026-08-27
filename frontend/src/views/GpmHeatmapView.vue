<script setup>
import { computed, onBeforeUnmount, onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Message } from '@arco-design/web-vue'

import GpmDetailPanel from '../components/GpmDetailPanel.vue'
import GpmMapCanvas from '../components/GpmMapCanvas.vue'
import GpmScreenshotStrip from '../components/GpmScreenshotStrip.vue'
import GpmTrendCard from '../components/GpmTrendCard.vue'
import { registerPageRefresh } from '../pageActions'
import { useGpmHeatmapStore } from '../stores/gpmHeatmapStore'

defineOptions({ name: 'GpmHeatmapView' })
const store = useGpmHeatmapStore()
const route = useRoute()
const router = useRouter()
let unregisterRefresh = null
let applyingRoute = false
let routeSequence = 0

const routeSceneId = () => {
  const value = route.params.sceneId
  return (Array.isArray(value) ? value[0] : value) || ''
}
const queryValue = (key) => {
  const value = route.query[key]
  return Array.isArray(value) ? value[0] : value
}

function routeRequest() {
  return {
    branchTag: queryValue('branch_tag') || 'main',
    sceneId: routeSceneId(),
    platform: queryValue('platform') || '',
    shadingQuality: queryValue('quality') ?? '',
    batchId: queryValue('batch') || '',
    metric: queryValue('metric') || 'Scene_DC',
    point: queryValue('point') || '',
    days: queryValue('days') || 30,
  }
}

function normalizedLocation() {
  const state = store.routeState()
  const query = {}
  if (store.filters.branchTag !== 'main') query.branch_tag = store.filters.branchTag
  if (state.platform) query.platform = state.platform
  if (state.shadingQuality !== '') query.quality = String(state.shadingQuality)
  if (state.batchId) query.batch = state.batchId
  if (state.metric && state.metric !== 'Scene_DC') query.metric = state.metric
  if (state.point != null) query.point = String(state.point)
  if (state.days !== 30) query.days = String(state.days)
  return {
    path: state.sceneId ? `/gpm-heatmap/${encodeURIComponent(state.sceneId)}` : '/gpm-heatmap',
    query,
  }
}

function sameLocation(target) {
  const current = Object.fromEntries(Object.entries(route.query).map(([key, value]) => [
    key, String(Array.isArray(value) ? value[0] : value),
  ]))
  const desired = Object.fromEntries(Object.entries(target.query).map(([key, value]) => [key, String(value)]))
  return route.path === target.path && JSON.stringify(current) === JSON.stringify(desired)
}

async function syncRoute() {
  const target = normalizedLocation()
  if (sameLocation(target)) return
  applyingRoute = true
  try {
    await router.replace(target)
  } finally {
    applyingRoute = false
  }
}

async function applyCurrentRoute() {
  const sequence = ++routeSequence
  try {
    await store.applyRoute(routeRequest())
    if (sequence !== routeSequence) return
    await syncRoute()
  } catch (error) {
    if (sequence === routeSequence) Message.error(error?.message || 'GPMHeatmap 页面加载失败')
  }
}

async function changeScope(change) {
  try {
    await store.changeScope(change)
    await syncRoute()
  } catch (error) {
    Message.error(error?.message || '筛选切换失败')
  }
}

async function selectPoint(pointId) {
  try {
    await store.selectPoint(pointId)
    await syncRoute()
  } catch (error) {
    Message.error(error?.message || '点位数据加载失败')
  }
}

async function changeDays(days) {
  store.days = Number(days)
  try {
    await store.loadTrends()
    await syncRoute()
  } catch (error) {
    Message.error(error?.message || '趋势数据加载失败')
  }
}

async function refresh() {
  await store.refresh()
  await syncRoute()
}

function formatBatch(batch) {
  const time = String(batch?.captured_at || '').replace('T', ' ').slice(0, 16)
  return `P4 ${batch?.p4_version ?? '—'} · ${time || '时间未知'}`
}

const trendDefinitions = computed(() => {
  const labels = {
    Scene_DC: '场景 DC', Scene_Tris: '场景面数', Drawcall: 'DrawCall', Triangle: 'Triangle',
  }
  const colors = ['#3491fa', '#f7ba1e', '#4cd6b0', '#a871e3']
  return (store.frame?.trend || []).slice(0, 4).map((item, index) => ({
    key: item.key, title: labels[item.key] || item.name || item.key, color: colors[index],
  }))
})

watch(() => route.fullPath, () => {
  if (!applyingRoute) applyCurrentRoute()
})

onMounted(() => {
  unregisterRefresh = registerPageRefresh(refresh)
  applyCurrentRoute()
})
onBeforeUnmount(() => {
  unregisterRefresh?.()
  store.cancelAll()
})
</script>

<template>
  <main class="gpm-page">
    <section class="gpm-filters card">
      <label class="filter-field compact"><span>平台</span>
        <a-select :model-value="store.filters.platform" :loading="store.loading.meta"
          @change="changeScope({ platform: $event })">
          <a-option v-for="item in store.platformOptions" :key="item" :value="item">{{ item }}</a-option>
        </a-select>
      </label>
      <label class="filter-field scene"><span>场景 ID</span>
        <a-select :model-value="store.filters.sceneId" allow-search :loading="store.loading.meta"
          @change="changeScope({ sceneId: $event })">
          <a-option v-for="item in store.sceneOptions" :key="item.value" :value="item.value">
            {{ item.value }}
          </a-option>
        </a-select>
      </label>
      <label class="filter-field compact"><span>画质</span>
        <a-select :model-value="store.filters.shadingQuality" :loading="store.loading.meta"
          @change="changeScope({ shadingQuality: $event })">
          <a-option v-for="item in store.qualityOptions" :key="item.value" :value="item.value">
            {{ item.label }}
          </a-option>
        </a-select>
      </label>
      <label class="filter-field batch"><span>采集批次</span>
        <a-select :model-value="store.filters.batchId" :loading="store.loading.frame"
          @change="changeScope({ batchId: $event })">
          <a-option v-for="item in store.batchOptions" :key="item.batch_id" :value="item.batch_id">
            {{ formatBatch(item) }}
          </a-option>
        </a-select>
      </label>
    </section>

    <div v-if="store.errors.meta && !store.sceneOptions.length" class="page-error card">
      {{ store.errors.meta }}
      <a-button size="small" @click="applyCurrentRoute">重新加载</a-button>
    </div>
    <div v-else-if="store.loading.frame && !store.frame" class="page-loading card">
      <a-spin /> 正在加载 GPMHeatmap 数据
    </div>
    <div v-else-if="store.errors.frame && !store.frame" class="page-error card">
      {{ store.errors.frame }}
      <a-button size="small" @click="applyCurrentRoute">重新加载</a-button>
    </div>
    <template v-else-if="store.frame">
      <section class="overview-section">
        <section class="workspace-grid">
          <GpmMapCanvas :frame="store.frame" :metric-key="store.metricKey"
            :selected-point-id="store.selectedPointId"
            @metric="store.metricKey = $event; syncRoute()" @select="selectPoint" />
          <GpmDetailPanel :point="store.pointDetail" :loading="store.loading.detail"
            :error="store.errors.detail" />
        </section>

        <GpmScreenshotStrip :points="store.frame.points" :selected-point-id="store.selectedPointId"
          @select="selectPoint" />
      </section>

      <section class="trend-section">
        <header class="trend-header card">
          <div><strong>点位 {{ String(store.selectedPoint?.index || '').padStart(2, '0') }} · 版本趋势</strong>
            <span>跟随当前选中点位</span></div>
          <a-select :model-value="store.days" class="days-select" @change="changeDays">
            <a-option v-for="value in [7, 14, 30, 60, 90]" :key="value" :value="value">
              最近 {{ value }} 天
            </a-option>
          </a-select>
        </header>
        <div class="trend-grid">
          <GpmTrendCard v-for="item in trendDefinitions" :key="item.key"
            :title="item.title" :metric-key="item.key" :color="item.color"
            :available="store.trends?.available !== false" :points="store.trends?.points || []" />
        </div>
      </section>
    </template>
    <div v-else class="page-empty card">暂无 GPMHeatmap 上报数据</div>
  </main>
</template>

<style scoped>
.gpm-page {
  flex: 1; min-height: 0; overflow-y: auto; padding: 10px 12px 18px;
  display: flex; flex-direction: column; gap: 10px;
}
.gpm-filters {
  flex: 0 0 auto; min-height: 54px; padding: 8px 12px; display: grid;
  grid-template-columns: minmax(180px, .75fr) minmax(300px, 1.35fr) minmax(180px, .75fr) minmax(330px, 1.4fr);
  gap: 12px; align-items: center; overflow: visible;
}
.filter-field { min-width: 0; display: grid; grid-template-columns: auto minmax(0, 1fr); align-items: center; gap: 10px; }
.filter-field > span { color: var(--color-text-3); white-space: nowrap; }
.filter-field :deep(.arco-select-view) { background: var(--color-fill-2); border-color: transparent; }
.overview-section {
  flex: 0 0 auto; min-width: 0; height: max(838px, calc(100dvh - 144px)); display: grid;
  grid-template-columns: minmax(0, 1fr); grid-template-rows: minmax(620px, 1fr) auto; gap: 10px;
}
.workspace-grid {
  width: 100%; min-width: 0; min-height: 0; display: grid;
  grid-template-columns: minmax(0, 1.04fr) minmax(0, .96fr); gap: 10px;
}
.page-loading, .page-error, .page-empty { min-height: 240px; display: flex; align-items: center; justify-content: center; gap: 12px; color: var(--color-text-3); }
.page-error { color: rgb(var(--red-6)); }
.trend-section { display: flex; flex-direction: column; gap: 10px; }
.trend-header { min-height: 54px; padding: 7px 14px; display: flex; align-items: center; justify-content: space-between; overflow: visible; }
.trend-header div { display: flex; align-items: baseline; gap: 10px; }
.trend-header strong { font-size: 14px; }
.trend-header span { color: var(--color-text-3); }
.days-select { width: 150px; }
.trend-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; }
@media (max-width: 1180px) {
  .gpm-filters { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .overview-section { height: auto; min-height: 0; grid-template-rows: auto auto; }
  .workspace-grid { flex: 0 0 auto; min-height: 0; grid-template-columns: 1fr; grid-template-rows: repeat(2, 680px); }
  .trend-grid { grid-template-columns: 1fr; }
}
</style>
