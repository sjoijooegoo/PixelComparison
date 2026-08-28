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
let synchronizedRoutePath = ''

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
    trendMode: queryValue('trend_mode') || 'average',
    days: queryValue('days') || 14,
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
  if (state.trendMode !== 'average') query.trend_mode = state.trendMode
  if (state.days !== 14) query.days = String(state.days)
  return {
    path: state.sceneId ? `/gpm-heatmap/${encodeURIComponent(state.sceneId)}` : '/gpm-heatmap',
    query,
  }
}

function sameLocation(target) {
  return route.fullPath === router.resolve(target).fullPath
}

async function syncRoute() {
  const target = normalizedLocation()
  const targetPath = router.resolve(target).fullPath
  if (sameLocation(target)) {
    synchronizedRoutePath = ''
    return
  }
  synchronizedRoutePath = targetPath
  applyingRoute = true
  try {
    await router.replace(target)
  } catch (error) {
    if (synchronizedRoutePath === targetPath) synchronizedRoutePath = ''
    throw error
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
    const loading = store.selectPoint(pointId)
    // 点位身份先进入地址栏；详情仍可保留上一帧并以 loading 状态平滑过渡。
    await syncRoute()
    await loading
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

async function changeTrendMode(mode) {
  try {
    await store.changeTrendMode(mode)
    await syncRoute()
  } catch (error) {
    Message.error(error?.message || '趋势统计方式切换失败')
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

const trendGroups = computed(() => {
  const available = new Set((store.frame?.trend || []).map((item) => item.key))
  return [
    {
      key: 'draw-calls', title: 'DC 趋势',
      series: [
        { key: 'Drawcall', label: '全部 DC', color: '#3491fa' },
        { key: 'Scene_DC', label: '场景 DC', color: '#4cd6b0' },
      ].filter((item) => available.has(item.key)),
    },
    {
      key: 'triangles', title: '面数趋势',
      series: [
        { key: 'Triangle', label: '全部面数', color: '#3491fa' },
        { key: 'Scene_Tris', label: '场景面数', color: '#4cd6b0' },
      ].filter((item) => available.has(item.key)),
    },
  ].filter((group) => group.series.length)
})

const activeMetric = computed(() => store.frame?.heat_map?.find(
  (item) => item.key === store.metricKey,
) || null)

watch(() => route.fullPath, () => {
  if (route.fullPath === synchronizedRoutePath) {
    synchronizedRoutePath = ''
    return
  }
  if (applyingRoute) return
  applyCurrentRoute()
})

onMounted(() => {
  unregisterRefresh = registerPageRefresh(refresh)
  applyCurrentRoute()
})
onBeforeUnmount(() => {
  unregisterRefresh?.()
  store.dispose()
})
</script>

<template>
  <main class="gpm-page">
    <section class="gpm-filters card">
      <div class="filter-field compact"><span>平台</span>
        <a-select class="filter-select platform-select" size="small"
          popup-container=".gpm-page"
          :model-value="store.filters.platform" :loading="store.loading.meta"
          @change="changeScope({ platform: $event })">
          <a-option v-for="item in store.platformOptions" :key="item" :value="item">{{ item }}</a-option>
        </a-select>
      </div>
      <div class="filter-field scene"><span>场景 ID</span>
        <a-select class="filter-select scene-select" size="small"
          popup-container=".gpm-page"
          :model-value="store.filters.sceneId" allow-search :loading="store.loading.meta"
          @change="changeScope({ sceneId: $event })">
          <a-option v-for="item in store.sceneOptions" :key="item.value" :value="item.value">
            {{ item.value }}
          </a-option>
        </a-select>
      </div>
      <div class="filter-field compact"><span>画质</span>
        <a-select class="filter-select quality-select" size="small"
          popup-container=".gpm-page"
          :model-value="store.filters.shadingQuality" :loading="store.loading.meta"
          @change="changeScope({ shadingQuality: $event })">
          <a-option v-for="item in store.qualityOptions" :key="item.value" :value="item.value">
            {{ item.label }}
          </a-option>
        </a-select>
      </div>
      <div class="filter-field batch"><span>采集批次</span>
        <a-select class="filter-select batch-select" size="small"
          popup-container=".gpm-page"
          :model-value="store.filters.batchId" :loading="store.loading.frame"
          @change="changeScope({ batchId: $event })">
          <a-option v-for="item in store.batchOptions" :key="item.batch_id" :value="item.batch_id">
            {{ formatBatch(item) }}
          </a-option>
        </a-select>
      </div>
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
          <GpmDetailPanel :point="store.pointDetail" :summary-point="store.selectedPoint"
            :metric-key="store.metricKey" :metric-name="activeMetric?.name"
            :loading="store.loading.detail" :error="store.errors.detail" />
        </section>

        <GpmScreenshotStrip :points="store.frame.points" :selected-point-id="store.selectedPointId"
          @select="selectPoint" />
      </section>

      <section class="trend-section card">
        <header class="trend-section-header">
          <strong>数据趋势</strong>
          <div class="trend-card-controls">
            <a-radio-group :model-value="store.trendMode" type="button" size="small"
              @change="changeTrendMode">
              <a-radio value="average">整体平均</a-radio>
              <a-radio value="point">单个点位</a-radio>
            </a-radio-group>
            <a-select :model-value="store.days" class="days-select" size="small" @change="changeDays">
              <a-option v-for="value in [7, 14, 30]" :key="value" :value="value">
                最近 {{ value }} 天
              </a-option>
            </a-select>
          </div>
        </header>
        <div class="trend-grid">
          <GpmTrendCard v-for="item in trendGroups" :key="item.key"
            :title="item.title" :series="item.series"
            :storage-key="`pixelcomp.gpmTrend.${item.key}.visibleSeries.v1`"
            :current-batch-id="store.filters.batchId"
            :empty-label="store.trendMode === 'average' ? '整体平均' : '单个点位'"
            :points="store.trends?.points || []" />
        </div>
      </section>
    </template>
    <div v-else class="page-empty card">暂无 GPMHeatmap 上报数据</div>
  </main>
</template>

<style scoped>
.gpm-page {
  position: relative; flex: 1; min-height: 0; overflow-y: auto; padding: 10px 12px 18px;
  display: flex; flex-direction: column; gap: 10px;
}
.gpm-filters {
  flex: 0 0 auto; min-height: 48px; padding: 10px 14px; display: flex;
  flex-wrap: wrap; gap: 10px 16px; align-items: center; overflow: visible;
}
.filter-field { min-width: 0; display: flex; align-items: center; gap: 6px; }
.filter-field > span { color: var(--color-text-3); font-size: 12px; white-space: nowrap; }
.filter-field :deep(.platform-select) { width: 180px; }
.filter-field :deep(.scene-select) { width: 380px; }
.filter-field :deep(.quality-select) { width: 130px; }
.filter-field :deep(.batch-select) { width: 310px; }
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
.trend-section {
  min-width: 0; min-height: 1007px; height: 1007px;
  box-sizing: border-box; padding: 10px 12px 12px; overflow: visible;
  display: flex; flex-direction: column;
}
.trend-section-header {
  min-height: 30px; padding: 0 4px 8px; display: flex; align-items: center;
  justify-content: space-between; gap: 12px; flex-wrap: wrap;
}
.trend-section-header > strong {
  color: var(--color-text-1); font-size: 15px; font-weight: 600;
}
.trend-card-controls {
  min-width: 0; display: flex; align-items: center; justify-content: flex-end; gap: 8px;
}
.trend-card-controls :deep(.arco-radio-group) { flex: 0 0 auto; }
.trend-card-controls :deep(.arco-radio-button-content) {
  min-height: 22px; padding: 0 8px; font-size: 11px; line-height: 20px;
}
.trend-card-controls :deep(.days-select) { flex: 0 0 124px; width: 124px; }
.trend-card-controls :deep(.days-select.arco-select-view) {
  background: var(--color-fill-2); border-color: var(--color-border-1);
}
.trend-grid {
  flex: 1; min-width: 0; min-height: 0; display: grid;
  grid-template-columns: minmax(0, 1fr); grid-template-rows: repeat(2, minmax(0, 1fr)); gap: 8px;
}
@media (max-width: 1180px) {
  .overview-section { height: auto; min-height: 0; grid-template-rows: auto auto; }
  .workspace-grid { flex: 0 0 auto; min-height: 0; grid-template-columns: 1fr; grid-template-rows: repeat(2, 680px); }
}
@media (max-width: 700px) {
  .filter-field { width: 100%; }
  .filter-field :deep(.filter-select) { flex: 1; width: auto; min-width: 0; }
  .trend-card-controls { flex-wrap: wrap; }
  .trend-section { height: auto; min-height: 0; }
  .trend-grid { grid-template-rows: none; }
  .trend-grid :deep(.trend-card) { min-height: 285px; }
}
</style>
