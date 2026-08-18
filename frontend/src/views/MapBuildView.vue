<script setup>
import { computed, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api, isRequestCancelled } from '../api'
import { p4Label, useStore } from '../store'
import {
  atlasColor,
  formatExactBytes,
  formatMiB,
  rankMetricDetails,
} from '../mapBuildPresentation'
import MapBuildTrendChart from '../components/MapBuildTrendChart.vue'
import { registerPageRefresh } from '../pageActions'

const store = useStore()
const route = useRoute()
const router = useRouter()
const meta = ref({ scene_ids: [] })
const overview = ref(null)
const trend = ref({ selection: { label: '主分块 · 仅自身' }, points: [] })
const filters = reactive({
  branchTag: 'main',
  sceneId: '',
  batchId: '',
  days: 30,
})
const selection = reactive({ blockIndex: null, subBlockIndex: null, registryPath: null })
const metricScope = ref('self')
const trendRangeMode = ref('recent')
const customDateRange = ref([])
const metaLoading = ref(false)
const overviewLoading = ref(false)
const trendLoading = ref(false)
const error = ref('')
const routeReady = ref(false)
const requests = {
  meta: { sequence: 0, controller: null },
  overview: { sequence: 0, controller: null },
  trend: { sequence: 0, controller: null },
}
let unregisterPageRefresh = null
let routeApplySequence = 0
const DEFAULT_TREND_DAYS = 30
const VALID_TREND_DAYS = new Set([7, 14, 30, 60, 90])

function beginRequest(channel) {
  const runtime = requests[channel]
  runtime.controller?.abort()
  runtime.controller = new AbortController()
  const sequence = ++runtime.sequence
  return {
    signal: runtime.controller.signal,
    isLatest: () => runtime.sequence === sequence,
  }
}

function keepOrDefault(current, options, preferred = null) {
  const values = options.map((option) => option?.value ?? option)
  if (values.includes(current)) return current
  if (preferred !== null && values.includes(preferred)) return preferred
  return values[0] ?? ''
}

function metricScopeLabel(scope) {
  return scope === 'self' ? '仅自身' : '含子级汇总'
}

function trendSelectionLabel(label) {
  return (label || '主分块 · 仅自身').replace('自身数据', '仅自身')
}

function invalidateRequest(channel) {
  const runtime = requests[channel]
  runtime.controller?.abort()
  runtime.controller = null
  runtime.sequence += 1
}

function clearSceneData() {
  invalidateRequest('overview')
  invalidateRequest('trend')
  overview.value = null
  trend.value = { selection: { label: '主分块 · 仅自身' }, points: [] }
  filters.batchId = ''
  overviewLoading.value = false
  trendLoading.value = false
}

function routeSceneId() {
  const rawSceneId = route.params.sceneId
  return (Array.isArray(rawSceneId) ? rawSceneId[0] : rawSceneId) || ''
}

function routeQueryValue(name) {
  const value = route.query?.[name]
  return Array.isArray(value) ? value[0] : value
}

function availableBranchTag(value) {
  const normalized = String(value || 'main').trim().toLowerCase()
  return store.meta.branch_tags?.includes(normalized) ? normalized : 'main'
}

function dateStamp(value) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value || '')) return null
  const stamp = Date.parse(`${value}T00:00:00Z`)
  if (Number.isNaN(stamp) || new Date(stamp).toISOString().slice(0, 10) !== value) return null
  return stamp
}

function customRangeDays(range) {
  if (!Array.isArray(range) || range.length !== 2) return 0
  const start = dateStamp(range[0])
  const end = dateStamp(range[1])
  if (start === null || end === null) return 0
  return Math.floor((end - start) / 86_400_000) + 1
}

function parseNonNegativeInteger(value) {
  if (value === undefined || value === null || value === '') return null
  const parsed = Number(value)
  return Number.isInteger(parsed) && parsed >= 0 ? parsed : null
}

function routeAnalysisState() {
  const requestedDays = Number(routeQueryValue('days'))
  const blockIndex = parseNonNegativeInteger(routeQueryValue('block'))
  const requestedRange = [routeQueryValue('start'), routeQueryValue('end')]
  const requestedRangeDays = customRangeDays(requestedRange)
  const hasValidCustomRange = requestedRangeDays >= 1 && requestedRangeDays <= 90
  return {
    batchId: routeQueryValue('batch') || '',
    days: VALID_TREND_DAYS.has(requestedDays) ? requestedDays : DEFAULT_TREND_DAYS,
    trendRangeMode: hasValidCustomRange ? 'custom' : 'recent',
    customDateRange: hasValidCustomRange ? requestedRange : [],
    metricScope: routeQueryValue('scope') === 'subtree' ? 'subtree' : 'self',
    blockIndex,
    subBlockIndex: blockIndex === null
      ? null
      : parseNonNegativeInteger(routeQueryValue('sub')),
    registryPath: routeQueryValue('registry') || null,
  }
}

function applyAnalysisState(state) {
  filters.batchId = state.batchId
  filters.days = state.days
  trendRangeMode.value = state.trendRangeMode
  customDateRange.value = state.customDateRange
  metricScope.value = state.metricScope
  selection.registryPath = state.registryPath
  selection.blockIndex = state.registryPath === null ? state.blockIndex : null
  selection.subBlockIndex = state.registryPath === null ? state.subBlockIndex : null
}

function analysisQuery() {
  if (!overview.value) return { branch_tag: filters.branchTag }
  const query = {
    branch_tag: filters.branchTag,
    batch: String(filters.batchId),
    scope: metricScope.value,
  }
  if (trendRangeMode.value === 'custom' && customRangeDays(customDateRange.value) > 0) {
    query.start = customDateRange.value[0]
    query.end = customDateRange.value[1]
  } else query.days = String(filters.days)
  if (selection.registryPath !== null) query.registry = selection.registryPath
  else if (selection.blockIndex !== null) {
    query.block = String(selection.blockIndex)
    if (selection.subBlockIndex !== null) query.sub = String(selection.subBlockIndex)
  }
  return query
}

function sameRouteQuery(left, right) {
  const normalize = (query) => Object.fromEntries(
    Object.entries(query || {})
      .filter(([, value]) => value !== undefined && value !== null && value !== '')
      .map(([key, value]) => [key, String(Array.isArray(value) ? value[0] : value)])
      .sort(([a], [b]) => a.localeCompare(b)),
  )
  return JSON.stringify(normalize(left)) === JSON.stringify(normalize(right))
}

async function syncAnalysisRoute() {
  if (!route.path.startsWith('/map-build')) return
  const path = filters.sceneId
    ? `/map-build/${encodeURIComponent(filters.sceneId)}`
    : '/map-build'
  const query = analysisQuery()
  if (route.path === path && sameRouteQuery(route.query, query)) return
  await router.replace(Object.keys(query).length ? { path, query } : path)
}

async function loadMeta(requestedSceneId) {
  const request = beginRequest('meta')
  metaLoading.value = true
  try {
    const data = await api.mapBuildMeta(
      { branch_tag: filters.branchTag },
      { signal: request.signal },
    )
    if (!request.isLatest()) return null
    if (!data || !Array.isArray(data.scene_ids)) {
      throw new Error('烘培数据筛选项格式无效')
    }
    meta.value = data
    const preferredSceneId = data.scene_ids[0]?.value || ''
    const currentSceneId = requestedSceneId === undefined ? filters.sceneId : requestedSceneId
    filters.sceneId = keepOrDefault(currentSceneId, sceneOptions.value, preferredSceneId)
    return data
  } catch (cause) {
    if (isRequestCancelled(cause) || !request.isLatest()) return null
    error.value = cause?.message || '烘培数据筛选项加载失败'
    return null
  } finally {
    if (request.isLatest()) metaLoading.value = false
  }
}

function selectionExists(data) {
  if (selection.registryPath !== null) {
    return data?.auxiliary_blocks?.some((item) => item.path === selection.registryPath) || false
  }
  if (selection.blockIndex === null) return true
  const block = data?.blocks?.find((item) => item.index === selection.blockIndex)
  if (!block) return false
  if (selection.subBlockIndex === null) return true
  return block.sub_blocks.some((item) => item.index === selection.subBlockIndex)
}

function normalizeMetricScope(data) {
  if (!data?.world?.has_children) {
    metricScope.value = 'self'
    return
  }
  const world = data?.world
  if (metricScope.value === 'self' && !world?.self_metrics) metricScope.value = 'subtree'
  else if (metricScope.value === 'subtree' && !world?.subtree_metrics) metricScope.value = 'self'
}

async function loadOverview(
  requestedBatchId = filters.batchId,
  { preserveOnError = false, onFailure = null } = {},
) {
  if (!filters.sceneId) {
    overview.value = null
    return null
  }
  const request = beginRequest('overview')
  overviewLoading.value = true
  try {
    const data = await api.mapBuildOverview(filters.sceneId, {
      branch_tag: filters.branchTag,
      batch_id: requestedBatchId,
    }, { signal: request.signal })
    if (!request.isLatest()) return null
    overview.value = data
    filters.batchId = data.batch.id
    if (!selectionExists(data)) {
      selection.blockIndex = null
      selection.subBlockIndex = null
      selection.registryPath = null
    }
    normalizeMetricScope(data)
    return data
  } catch (cause) {
    if (isRequestCancelled(cause) || !request.isLatest()) return null
    if (!preserveOnError) overview.value = null
    error.value = cause?.message || '烘培分块数据加载失败'
    onFailure?.(cause)
    return null
  } finally {
    if (request.isLatest()) overviewLoading.value = false
  }
}

async function loadTrend({ preserveOnError = false } = {}) {
  if (!filters.sceneId) {
    trend.value = { selection: { label: '主分块 · 仅自身' }, points: [] }
    return null
  }
  const request = beginRequest('trend')
  trendLoading.value = true
  try {
    const auxiliary = selection.registryPath === null
      ? null
      : overview.value?.auxiliary_blocks?.find((item) => item.path === selection.registryPath)
    const effectiveMetricScope = auxiliary && !auxiliary.has_children
      ? 'self'
      : metricScope.value
    const params = {
      branch_tag: filters.branchTag,
      days: filters.days,
      metric_scope: effectiveMetricScope,
    }
    if (trendRangeMode.value === 'custom') {
      if (customRangeDays(customDateRange.value) < 1) return null
      delete params.days
      params.start_date = customDateRange.value[0]
      params.end_date = customDateRange.value[1]
    }
    if (selection.registryPath !== null) params.registry_path = selection.registryPath
    else if (selection.blockIndex !== null) params.block_index = selection.blockIndex
    if (selection.subBlockIndex !== null) params.sub_block_index = selection.subBlockIndex
    const data = await api.mapBuildTrend(filters.sceneId, params, { signal: request.signal })
    if (!request.isLatest()) return null
    trend.value = data
    return data
  } catch (cause) {
    if (isRequestCancelled(cause) || !request.isLatest()) return null
    if (!preserveOnError) {
      trend.value = { selection: { label: '当前选择' }, points: [] }
    }
    error.value = cause?.message || '烘培趋势加载失败'
    return null
  } finally {
    if (request.isLatest()) trendLoading.value = false
  }
}

async function loadSelectedScene() {
  const requestedSceneId = filters.sceneId
  const requestedMetricScope = metricScope.value
  error.value = ''
  filters.batchId = ''
  selection.blockIndex = null
  selection.subBlockIndex = null
  selection.registryPath = null
  if (!selectedSceneHasData.value) {
    clearSceneData()
    return
  }
  const [loadedOverview] = await Promise.all([loadOverview(''), loadTrend()])
  if (
    loadedOverview
    && filters.sceneId === requestedSceneId
    && metricScope.value !== requestedMetricScope
  ) await loadTrend()
}

async function changeScene() {
  await loadSelectedScene()
  await syncAnalysisRoute()
}

async function changeBranch() {
  filters.branchTag = availableBranchTag(filters.branchTag)
  store.filters.branch_tag = filters.branchTag
  clearSceneData()
  selection.blockIndex = null
  selection.subBlockIndex = null
  selection.registryPath = null
  error.value = ''
  const loaded = await loadMeta(filters.sceneId)
  if (loaded && filters.sceneId && selectedSceneHasData.value) {
    const loadedOverview = await loadOverview('')
    if (loadedOverview) await loadTrend()
  }
  await syncAnalysisRoute()
}

async function applyRouteState() {
  if (!routeReady.value) return
  const sequence = ++routeApplySequence
  const nextBranchTag = availableBranchTag(routeQueryValue('branch_tag'))
  if (filters.branchTag !== nextBranchTag) {
    filters.branchTag = nextBranchTag
    store.filters.branch_tag = nextBranchTag
    clearSceneData()
    applyAnalysisState(routeAnalysisState())
    const loadedMeta = await loadMeta(routeSceneId())
    if (sequence !== routeApplySequence) return
    if (loadedMeta && filters.sceneId && selectedSceneHasData.value) {
      const loadedOverview = await loadOverview(filters.batchId)
      if (loadedOverview) await loadTrend()
    }
    await syncAnalysisRoute()
    return
  }
  const preferredSceneId = meta.value.scene_ids[0]?.value || ''
  const nextSceneId = keepOrDefault(routeSceneId(), sceneOptions.value, preferredSceneId)
  const nextState = routeAnalysisState()
  const sceneChanged = filters.sceneId !== nextSceneId
  const batchChanged = String(filters.batchId) !== String(nextState.batchId)
  const analysisChanged = filters.days !== nextState.days
    || trendRangeMode.value !== nextState.trendRangeMode
    || customDateRange.value.join('|') !== nextState.customDateRange.join('|')
    || metricScope.value !== nextState.metricScope
    || selection.blockIndex !== nextState.blockIndex
    || selection.subBlockIndex !== nextState.subBlockIndex
    || selection.registryPath !== nextState.registryPath
  if (!sceneChanged && !batchChanged && !analysisChanged) return

  const previousBatchId = overview.value?.batch?.id ?? ''
  if (sceneChanged) {
    filters.sceneId = nextSceneId
    overview.value = null
    trend.value = { selection: { label: '主分块 · 仅自身' }, points: [] }
  }
  applyAnalysisState(nextState)
  if (!filters.sceneId || !selectedSceneHasData.value) {
    clearSceneData()
    await syncAnalysisRoute()
    return
  }

  let failed = false
  if (sceneChanged || batchChanged) {
    const loaded = await loadOverview(nextState.batchId, {
      preserveOnError: !sceneChanged,
      onFailure: () => { failed = true },
    })
    if (sequence !== routeApplySequence) return
    if (failed && !sceneChanged) filters.batchId = previousBatchId
    if (!loaded) {
      await syncAnalysisRoute()
      return
    }
  }
  if (!selectionExists(overview.value)) {
    selection.blockIndex = null
    selection.subBlockIndex = null
    selection.registryPath = null
  }
  normalizeMetricScope(overview.value)
  await loadTrend({ preserveOnError: !sceneChanged })
  if (sequence !== routeApplySequence) return
  await syncAnalysisRoute()
}

async function changeBatch() {
  error.value = ''
  const requestedBatchId = filters.batchId
  const previousBatchId = overview.value?.batch?.id ?? ''
  const previousSelectionKey = selectionKey.value
  const previousMetricScope = metricScope.value
  let failed = false
  const loaded = await loadOverview(requestedBatchId, {
    preserveOnError: true,
    onFailure: () => { failed = true },
  })
  if (failed && String(filters.batchId) === String(requestedBatchId)) {
    filters.batchId = previousBatchId
  }
  if (
    loaded
    && (
      selectionKey.value !== previousSelectionKey
      || metricScope.value !== previousMetricScope
    )
  ) {
    await loadTrend()
  }
  await syncAnalysisRoute()
}

async function selectTrendBatch(batch) {
  if (batch?.id === undefined || batch?.id === null) return
  if (String(filters.batchId) === String(batch.id)) return
  filters.batchId = batch.id
  await changeBatch()
}

async function choose(blockIndex = null, subBlockIndex = null) {
  if (isSelected(blockIndex, subBlockIndex) && !error.value) return
  selection.blockIndex = blockIndex
  selection.subBlockIndex = subBlockIndex
  selection.registryPath = null
  error.value = ''
  await loadTrend()
  await syncAnalysisRoute()
}

async function chooseAuxiliary(registryPath) {
  if (isAuxiliarySelected(registryPath) && !error.value) return
  selection.blockIndex = null
  selection.subBlockIndex = null
  selection.registryPath = registryPath
  error.value = ''
  await loadTrend()
  await syncAnalysisRoute()
}

async function changeMetricScope(scope) {
  if (!['self', 'subtree'].includes(scope) || scope === metricScope.value) return
  metricScope.value = scope
  error.value = ''
  await loadTrend()
  await syncAnalysisRoute()
}

async function changeTrendRangeMode(value) {
  if (value === 'custom') {
    trendRangeMode.value = 'custom'
    error.value = ''
    if (customRangeDays(customDateRange.value) >= 1) {
      await loadTrend()
      await syncAnalysisRoute()
    }
    return
  }
  trendRangeMode.value = 'recent'
  filters.days = Number(value)
  error.value = ''
  await loadTrend()
  await syncAnalysisRoute()
}

async function changeCustomDateRange(range) {
  const days = customRangeDays(range)
  if (days < 1) {
    error.value = '结束日期不能早于开始日期'
    return
  }
  if (days > 90) {
    error.value = '自定义日期范围最多 90 天'
    return
  }
  customDateRange.value = [...range]
  error.value = ''
  await loadTrend()
  await syncAnalysisRoute()
}

async function refresh() {
  error.value = ''
  const loaded = await loadMeta()
  if (!loaded) return
  if (!filters.sceneId || !selectedSceneHasData.value) {
    clearSceneData()
    await syncAnalysisRoute()
    return
  }
  const [loadedOverview] = await Promise.all([
    loadOverview(filters.batchId, { preserveOnError: true }),
    loadTrend({ preserveOnError: true }),
  ])
  if (loadedOverview) await syncAnalysisRoute()
}

const allCells = computed(() => overview.value?.blocks?.flatMap((block) => block.sub_blocks) || [])
const maximumCellMipBytes = computed(() => Math.max(
  0,
  ...allCells.value
    .map((cell) => Number(
      cell.self_metrics?.all_mips_bytes ?? cell.metrics?.all_mips_bytes ?? 0,
    ))
    .filter(Number.isFinite),
))
const selectionKey = computed(() => (
  selection.registryPath !== null
    ? `registry:${selection.registryPath}`
    : selection.blockIndex === null
    ? 'world'
    : `${selection.blockIndex}:${selection.subBlockIndex ?? 'block'}`
))
const mapBuildSceneIds = computed(() => new Set(
  meta.value.scene_ids.map((scene) => scene.value),
))
const sceneOptions = computed(() => {
  const sharedOptions = store.meta.scene_ids || []
  return sharedOptions.length
    ? sharedOptions
    : meta.value.scene_ids.map((scene) => scene.value)
})
const unlistedSceneIds = computed(() => new Set(store.meta.unlisted_scene_ids || []))
const hasSceneOptions = computed(() => sceneOptions.value.length > 0)
const selectedSceneHasData = computed(() => mapBuildSceneIds.value.has(filters.sceneId))
const hasBlockTree = computed(() => (
  (overview.value?.blocks?.length || 0) + (overview.value?.auxiliary_blocks?.length || 0)
) > 0)
const selectedDetail = computed(() => {
  if (!overview.value) return null
  let label
  let context
  let node
  let forceSelfScope = false
  if (selection.registryPath !== null) {
    node = overview.value.auxiliary_blocks?.find(
      (item) => item.path === selection.registryPath,
    )
    if (!node) return null
    label = node.label
    context = node.path
    forceSelfScope = !node.has_children
  } else if (selection.blockIndex === null) {
    node = overview.value.world
    label = node.label || '主分块'
    context = node.path || '主分块'
  } else {
    const block = overview.value.blocks.find((item) => item.index === selection.blockIndex)
    if (!block) return null
    if (selection.subBlockIndex === null) {
      node = block
      label = block.label
      context = block.path || '分块'
    } else {
      const cell = block.sub_blocks.find((item) => item.index === selection.subBlockIndex)
      if (!cell) return null
      node = cell
      label = `${block.label} / ${cell.label}`
      context = cell.path
    }
  }
  const effectiveScope = !forceSelfScope && metricScope.value === 'subtree' && node.subtree_metrics
    ? 'subtree'
    : node.self_metrics
      ? 'self'
      : 'subtree'
  return {
    label,
    context,
    metrics: effectiveScope === 'subtree'
      ? node.subtree_metrics || node.metrics
      : node.self_metrics,
    effectiveScope,
  }
})
const detailRows = computed(() => rankMetricDetails(selectedDetail.value?.metrics))
const detailMaximum = computed(() => detailRows.value[0]?.value || 0)

function isSelected(blockIndex = null, subBlockIndex = null) {
  const key = blockIndex === null ? 'world' : `${blockIndex}:${subBlockIndex ?? 'block'}`
  return selectionKey.value === key
}
function isAuxiliarySelected(registryPath) {
  return selectionKey.value === `registry:${registryPath}`
}
function gridHeaderScope(node) {
  if (metricScope.value === 'subtree' && node?.subtree_metrics) return 'subtree'
  return node?.self_metrics ? 'self' : 'subtree'
}
function gridHeaderMetrics(node) {
  return gridHeaderScope(node) === 'self'
    ? node.self_metrics || node.metrics
    : node.subtree_metrics || node.metrics
}
function detailBarWidth(value) {
  if (!detailMaximum.value || !value) return '0%'
  return `${Math.max(3, value * 100 / detailMaximum.value)}%`
}
function formatCount(value) {
  return Number(value || 0).toLocaleString('zh-CN')
}
function batchLabel(batch, isLatest = false) {
  const date = batch.created_at?.replace('T', ' ').slice(0, 16) || '—'
  return `#${batch.id} · ${date} · ${p4Label(batch.p4_version)}${isLatest ? '（最新）' : ''}`
}

onMounted(async () => {
  unregisterPageRefresh = registerPageRefresh(refresh)
  const requestedBranchTag = routeQueryValue('branch_tag') || store.filters.branch_tag
  // bootstrap 会先启动 store.init() 再挂载页面。等待同一轮初始化完成后再校验
  // 深链分支，避免 meta 尚只有默认 main 时把有效的 engine-ue5 错误回退。
  if (!store.initialized && typeof store.init === 'function') {
    try {
      await store.init('', requestedBranchTag)
    } catch {
      // 页面自己的错误态会继续承接 map-build 请求失败，外壳仍保持可操作。
    }
  }
  filters.branchTag = availableBranchTag(requestedBranchTag)
  store.filters.branch_tag = filters.branchTag
  applyAnalysisState(routeAnalysisState())
  const loaded = await loadMeta(routeSceneId())
  if (loaded && filters.sceneId && selectedSceneHasData.value) {
    const loadedOverview = await loadOverview(filters.batchId)
    if (loadedOverview) await loadTrend()
  }
  routeReady.value = true
  await syncAnalysisRoute()
})
watch(
  () => [
    route.params.sceneId,
    route.query?.branch_tag,
    route.query?.batch,
    route.query?.days,
    route.query?.start,
    route.query?.end,
    route.query?.scope,
    route.query?.block,
    route.query?.sub,
    route.query?.registry,
  ],
  applyRouteState,
)
onUnmounted(() => {
  unregisterPageRefresh?.()
  Object.values(requests).forEach((request) => request.controller?.abort())
})
</script>

<template>
  <div class="map-build-page">
    <div class="map-build-shell">
      <section class="toolbar card" aria-label="烘培数据筛选">
        <div class="filter-field branch-field">
          <span class="label">分支</span>
          <a-select v-model="filters.branchTag" size="small" style="width: 160px"
            @change="changeBranch">
            <a-option v-for="branch in store.meta.branch_tags" :key="branch" :value="branch">
              {{ branch }}
            </a-option>
          </a-select>
        </div>
        <div class="filter-field scene-field">
          <span class="label">场景ID</span>
          <a-select v-model="filters.sceneId" class="scene-select" :loading="metaLoading"
            placeholder="全部场景" allow-clear allow-search size="small" style="width: 320px"
            @change="changeScene">
            <a-option v-for="scene in sceneOptions" :key="scene" :value="scene">
              <span class="scene-option">
                <span>{{ scene }}</span>
                <span v-if="unlistedSceneIds.has(scene)" class="unlisted">未配置</span>
              </span>
            </a-option>
          </a-select>
        </div>
        <div class="filter-field batch-field">
          <span class="label">网格批次</span>
          <a-select v-model="filters.batchId" class="batch-select" :loading="overviewLoading"
            :disabled="!selectedSceneHasData" allow-search size="small" style="width: 520px"
            @change="changeBatch">
            <a-option v-for="(batch, index) in overview?.available_batches || []"
              :key="batch.id" :value="batch.id">
              {{ batchLabel(batch, index === 0) }}
            </a-option>
          </a-select>
        </div>
      </section>

      <a-alert v-if="error" type="error" closable @close="error = ''">{{ error }}</a-alert>

      <div v-if="metaLoading && !overview" class="page-state card">
        <a-spin :size="30" tip="正在读取烘培数据…" />
      </div>
      <div v-else-if="!hasSceneOptions" class="page-state card">
        <div class="state-glyph">▦</div>
        <div class="state-title">还没有场景数据</div>
        <div class="state-sub">批次上报后，场景会自动出现在这里。</div>
      </div>
      <div v-else-if="!filters.sceneId" class="page-state card">
        <div class="state-glyph">▦</div>
        <div class="state-title">请选择场景</div>
        <div class="state-sub">选择一个场景以查看对应的烘培数据。</div>
      </div>
      <div v-else-if="!selectedSceneHasData" class="page-state card">
        <div class="state-glyph">▦</div>
        <div class="state-title">该场景还没有烘培数据</div>
        <div class="state-sub">电影档批次上报 map_build_data 后即可查看。</div>
      </div>

      <template v-else>
        <div class="atlas-row">
          <div v-if="overviewLoading && overview" class="overview-loading-veil" aria-live="polite">
            <a-spin />
            <span>正在切换批次…</span>
          </div>
          <section class="atlas-card card" :class="{
            'world-selected': overview && isSelected()
              && (metricScope === 'subtree' || !overview.world?.has_children),
            'self-head-selected': overview && isSelected()
              && metricScope === 'self' && overview.world?.has_children,
          }">
            <button type="button" class="atlas-head world-head" :class="{ selected: isSelected() }"
              :aria-pressed="isSelected()" @click="choose()">
              <span class="world-select">
                <span class="section-stripe"></span>
                <b>主分块</b>
              </span>
              <span v-if="overview" class="world-total">
                <span>
                  <small>{{ metricScopeLabel(gridHeaderScope(overview.world)) }}</small>
                  <b :title="formatExactBytes(gridHeaderMetrics(overview.world)?.all_mips_bytes)">
                    {{ formatMiB(gridHeaderMetrics(overview.world)?.all_mips_bytes) }}
                  </b>
                </span>
              </span>
            </button>

            <div v-if="overviewLoading && !overview" class="atlas-loading"><a-spin tip="正在整理分块…" /></div>
            <div v-else-if="overview && !hasBlockTree" class="no-block-tree" role="status">
              该场景没有分块数据，仅展示主分块数据
            </div>
            <div v-else-if="overview?.blocks?.length" class="block-layout">
              <article v-for="block in overview.blocks" :key="block.index" class="block-panel"
                :class="{
                  selected: isSelected(block.index) && (metricScope === 'subtree' || !block.has_children),
                  'self-head-selected': isSelected(block.index) && metricScope === 'self' && block.has_children,
                }">
                <button class="block-head" :class="{ selected: isSelected(block.index) }"
                  :aria-pressed="isSelected(block.index)"
                  @click="choose(block.index)">
                  <span><i></i>{{ block.label }}</span>
                  <span class="block-values">
                    <small>{{ metricScopeLabel(gridHeaderScope(block)) }}</small>
                    <b :title="formatExactBytes(gridHeaderMetrics(block)?.all_mips_bytes)">
                      {{ formatMiB(gridHeaderMetrics(block)?.all_mips_bytes) }}
                    </b>
                  </span>
                </button>
                <div class="sub-grid">
                  <button v-for="cell in block.sub_blocks" :key="cell.index" class="sub-cell"
                    :class="{ selected: isSelected(block.index, cell.index) }"
                    :style="{ backgroundColor: atlasColor(cell.self_metrics?.all_mips_bytes ?? cell.metrics.all_mips_bytes, maximumCellMipBytes) }"
                    :aria-pressed="isSelected(block.index, cell.index)"
                    :title="`${block.label} / ${cell.label} · 总 Mip ${formatExactBytes(cell.self_metrics?.all_mips_bytes ?? cell.metrics.all_mips_bytes)}`"
                    @click="choose(block.index, cell.index)">
                    <span>{{ cell.label }}</span>
                    <b :title="formatExactBytes(cell.self_metrics?.all_mips_bytes ?? cell.metrics.all_mips_bytes)">
                      {{ formatMiB(cell.self_metrics?.all_mips_bytes ?? cell.metrics.all_mips_bytes) }}
                    </b>
                  </button>
                </div>
              </article>
            </div>
            <footer v-if="overview && hasBlockTree" class="atlas-card-footer"
              :class="{ 'auxiliary-only': !overview.blocks?.length }">
              <div v-if="overview.auxiliary_blocks?.length" class="auxiliary-block-list">
                <button v-for="block in overview.auxiliary_blocks" :key="block.key || block.path"
                  type="button" class="auxiliary-block"
                  :class="{ selected: isAuxiliarySelected(block.path) }"
                  :aria-pressed="isAuxiliarySelected(block.path)"
                  :title="block.path"
                  @click="chooseAuxiliary(block.path)">
                  <span><i></i><b>{{ block.label }}</b></span>
                  <b :title="formatExactBytes(gridHeaderMetrics(block)?.all_mips_bytes)">
                    {{ formatMiB(gridHeaderMetrics(block)?.all_mips_bytes) }}
                  </b>
                </button>
              </div>
              <div class="atlas-scope-control">
                <div class="metric-scope-switch" role="group" aria-label="分块网格统计口径">
                  <button type="button" :class="{ active: metricScope === 'self' }"
                    :aria-pressed="metricScope === 'self'" @click="changeMetricScope('self')">
                    仅自身
                  </button>
                  <button type="button" :class="{ active: metricScope === 'subtree' }"
                    :aria-pressed="metricScope === 'subtree'" @click="changeMetricScope('subtree')">
                    含子级
                  </button>
                </div>
              </div>
            </footer>
          </section>

          <aside v-if="selectedDetail" class="detail-panel card" aria-live="polite">
            <header class="detail-head">
              <div class="detail-title">
                <h3>{{ selectedDetail.label }}<small v-if="selectedDetail.effectiveScope === 'subtree'">（含子级汇总）</small></h3>
                <p :title="selectedDetail.context">{{ selectedDetail.context }}</p>
              </div>
            </header>
            <div class="detail-summary">
              <div>
                <span>总 Mip</span>
                <b :title="formatExactBytes(selectedDetail.metrics.all_mips_bytes)">
                  {{ formatMiB(selectedDetail.metrics.all_mips_bytes) }}
                </b>
              </div>
              <div>
                <span>Cook 估算</span>
                <b :title="formatExactBytes(selectedDetail.metrics.cook_estimate_bytes)">
                  {{ formatMiB(selectedDetail.metrics.cook_estimate_bytes) }}
                </b>
              </div>
              <div>
                <span>纹理数</span>
                <b>{{ formatCount(selectedDetail.metrics.texture_count) }}</b>
              </div>
            </div>
            <div class="detail-section-title">
              <span>指标明细</span>
              <small>从高到低</small>
            </div>
            <ol class="detail-list">
              <li v-for="(row, index) in detailRows" :key="row.key" class="detail-row">
                <div class="detail-row-head">
                  <span><i>{{ String(index + 1).padStart(2, '0') }}</i>{{ row.label }}</span>
                  <b :title="formatExactBytes(row.value)">{{ formatMiB(row.value) }}</b>
                </div>
                <div class="detail-track" aria-hidden="true">
                  <i :style="{ width: detailBarWidth(row.value), backgroundColor: row.color }"></i>
                </div>
              </li>
            </ol>
          </aside>
        </div>

        <section class="trend-card card">
          <header class="section-head">
            <div class="section-title">
              <span>数据趋势</span>
              <span class="selection-pill">{{ trendSelectionLabel(trend.selection?.label) }}</span>
            </div>
            <div class="trend-controls">
              <a-select :model-value="trendRangeMode === 'custom' ? 'custom' : filters.days"
                size="small" class="days-select" @change="changeTrendRangeMode">
                <a-option :value="7">最近 7 天</a-option>
                <a-option :value="14">最近 14 天</a-option>
                <a-option :value="30">最近 30 天</a-option>
                <a-option :value="60">最近 60 天</a-option>
                <a-option :value="90">最近 90 天</a-option>
                <a-option value="custom">自定义</a-option>
              </a-select>
              <a-range-picker v-if="trendRangeMode === 'custom'" class="custom-range-picker"
                size="small" value-format="YYYY-MM-DD" :allow-clear="false"
                :model-value="customDateRange" @change="changeCustomDateRange" />
            </div>
          </header>
          <div class="trend-body" :class="{ loading: trendLoading }">
            <MapBuildTrendChart :points="trend.points" :current-batch-id="filters.batchId"
              @select-batch="selectTrendBatch" />
            <div v-if="trendLoading" class="loading-veil"><a-spin /></div>
          </div>
        </section>
      </template>
    </div>
  </div>
</template>

<style scoped>
.map-build-page { flex: 1; min-height: 0; overflow: auto; padding: 10px 12px 18px; }
.map-build-shell { width: min(1760px, 100%); margin: 0 auto; display: flex; flex-direction: column; gap: 10px; }
.toolbar {
  padding: 10px 14px; display: flex; flex-wrap: wrap; align-items: center;
  gap: 10px 16px; overflow: visible;
}
.filter-field { min-width: 0; display: flex; align-items: center; gap: 6px; }
.filter-field .label { flex: 0 0 auto; color: var(--color-text-3); font-size: 12px; white-space: nowrap; }
.scene-field { flex: 0 0 auto; }
.batch-field { flex: 0 0 auto; }
.scene-option { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.unlisted { color: var(--color-text-3); font-size: 11px; }
.page-state { min-height: 420px; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 8px; color: var(--color-text-3); }
.state-glyph { font-size: 38px; color: var(--color-text-4); }
.state-title { color: var(--color-text-2); font-size: 15px; font-weight: 600; }
.state-sub { color: var(--color-text-4); font-size: 12px; }
.trend-card, .atlas-card, .detail-panel { overflow: hidden; }
.atlas-row {
  position: relative;
  display: grid; grid-template-columns: minmax(0, 3fr) minmax(380px, 2fr);
  align-items: stretch; gap: 10px;
}
.overview-loading-veil {
  position: absolute; inset: 0; z-index: 8; display: flex; align-items: center; justify-content: center;
  gap: 9px; border-radius: 8px; background: color-mix(in srgb, var(--color-bg-1) 55%, transparent);
  color: var(--color-text-2); font-size: 12px; backdrop-filter: blur(1px);
}
.atlas-card {
  min-width: 0; display: flex; flex-direction: column;
  transition: border-color .14s ease, box-shadow .14s ease;
}
.atlas-card.world-selected {
  border-color: rgba(var(--arcoblue-6), .9);
  box-shadow: inset 0 0 0 1px rgba(var(--arcoblue-6), .18),
    0 0 0 1px rgba(var(--arcoblue-6), .3), 0 0 14px rgba(var(--arcoblue-6), .1);
}
.atlas-card.self-head-selected > .world-head {
  position: relative; z-index: 1;
  border-top-left-radius: inherit; border-top-right-radius: inherit;
  background: color-mix(in srgb, rgb(var(--arcoblue-6)) 7%, transparent);
  box-shadow: inset 0 0 0 1px rgba(var(--arcoblue-6), .78),
    0 0 12px rgba(var(--arcoblue-6), .12);
}
.atlas-scope-control { grid-column: 2; justify-self: end; flex: 0 0 auto; display: flex; align-items: center; }
.section-head, .atlas-head { min-height: 50px; padding: 0 16px; display: flex; align-items: center; justify-content: space-between; border-bottom: 1px solid var(--color-border-1); }
.section-title { display: flex; align-items: center; gap: 10px; font-size: 14px; font-weight: 600; }
.selection-pill { padding: 4px 9px; border-radius: 5px; border: 1px solid var(--color-border-2); color: var(--color-text-3); font-size: 11px; font-weight: 500; }
.trend-controls { display: flex; flex-wrap: wrap; align-items: center; justify-content: flex-end; gap: 8px 14px; }
.trend-controls :deep(.days-select) { width: 130px; }
.trend-controls :deep(.custom-range-picker) { width: 230px; }
.trend-body { position: relative; min-height: 300px; padding: 12px 14px 4px 4px; transition: opacity .15s ease; }
.trend-body.loading > :first-child { opacity: .55; }
.loading-veil { position: absolute; inset: 0; display: grid; place-items: center; pointer-events: none; }
.atlas-head { min-height: 58px; }
.world-head {
  box-sizing: border-box; width: 100%; flex: 0 0 auto; padding-right: 8px; border: 0;
  border-bottom: 1px solid var(--color-border-1); background: transparent; color: var(--color-text-1);
  font: inherit; text-align: left; cursor: pointer; transition: background-color .14s ease;
}
.world-head:hover { background: var(--color-fill-1); }
.world-head:focus-visible { outline: 2px solid rgba(var(--arcoblue-6), .85); outline-offset: -3px; }
.world-head.selected { border-bottom-color: rgba(var(--arcoblue-6), .48); }
.world-select {
  min-width: 0; align-self: stretch; flex: 1 1 auto; display: flex; align-items: center; gap: 10px;
  padding: 6px 0;
}
.section-stripe { width: 3px; height: 32px; border-radius: 2px; background: var(--color-border-3); }
.world-head.selected .section-stripe { background: rgb(var(--arcoblue-6)); box-shadow: 0 0 12px rgba(var(--arcoblue-6), .35); }
.world-select b { display: block; font-size: 15px; }
.world-total {
  min-width: 66px; align-self: stretch; padding: 5px 0 5px 4px; display: flex; align-items: center;
  justify-content: flex-end; color: inherit; font-family: "Bahnschrift", "Segoe UI", sans-serif;
}
.world-total > span { display: flex; flex-direction: column; align-items: flex-end; gap: 2px; }
.world-total small { color: var(--color-text-4); font: 9px/1.2 "Segoe UI", sans-serif; }
.world-total b { color: var(--color-text-1); font-size: 13px; }
.atlas-loading { min-height: 360px; display: grid; place-items: center; }
.no-block-tree {
  flex: 1 1 auto; min-height: 260px; display: grid; place-items: center;
  color: var(--color-text-3); font-size: 13px; text-align: center;
}
.block-layout { min-width: 0; padding: 12px; display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }
.block-panel {
  min-width: 0; overflow: hidden; border: 1px solid var(--color-border-2); border-radius: 0;
  background: var(--color-fill-1); transition: border-color .14s ease, box-shadow .14s ease;
}
.block-panel.selected {
  border-color: rgba(var(--arcoblue-6), .95);
  box-shadow: inset 0 0 0 1px rgba(var(--arcoblue-6), .24),
    0 0 0 1px rgba(var(--arcoblue-6), .38), 0 0 14px rgba(var(--arcoblue-6), .14);
}
.block-panel.self-head-selected > .block-head {
  position: relative; z-index: 1;
  border-top-left-radius: inherit; border-top-right-radius: inherit;
  border-bottom-color: rgba(var(--arcoblue-6), .72);
  background: color-mix(in srgb, rgb(var(--arcoblue-6)) 7%, transparent);
  box-shadow: inset 0 0 0 1px rgba(var(--arcoblue-6), .82),
    0 0 10px rgba(var(--arcoblue-6), .12);
}
.block-head {
  width: 100%; min-height: 42px; padding: 7px 11px; display: flex; align-items: center; justify-content: space-between;
  border: 0; border-bottom: 1px solid var(--color-border-2); background: color-mix(in srgb, var(--color-fill-2) 65%, transparent);
  color: var(--color-text-2); cursor: pointer; text-align: left;
}
.block-head:hover, .block-head.selected { background: var(--color-fill-3); color: var(--color-text-1); }
.block-panel.selected .block-head { border-bottom-color: rgba(var(--arcoblue-6), .55); }
.block-head > span:first-child { display: flex; align-items: center; gap: 7px; font-size: 12px; font-weight: 600; }
.block-head i { width: 3px; height: 14px; border-radius: 2px; background: var(--color-border-3); }
.block-head.selected i { background: rgb(var(--arcoblue-6)); }
.block-values { display: flex; flex-direction: column; align-items: flex-end; gap: 1px; font-family: "Bahnschrift", "Segoe UI", sans-serif; }
.block-values small { color: var(--color-text-4); font: 9px/1.1 "Segoe UI", sans-serif; }
.block-values b { font-size: 12px; }
.sub-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 0; background: transparent; }
.atlas-card-footer {
  min-height: 12px; margin-top: auto; padding: 0 12px 10px; display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr)); align-items: end; gap: 12px;
}
.atlas-card-footer.auxiliary-only { padding-top: 12px; }
.auxiliary-block-list { min-width: 0; grid-column: 1; display: grid; gap: 8px; }
.auxiliary-block {
  box-sizing: border-box; width: 100%; min-height: 42px; padding: 7px 11px;
  display: flex; align-items: center; justify-content: space-between; gap: 12px;
  border: 1px solid var(--color-border-2); border-radius: 0;
  background: color-mix(in srgb, var(--color-fill-2) 65%, transparent);
  color: var(--color-text-2); font: inherit; cursor: pointer; text-align: left;
  transition: color .14s ease, background-color .14s ease, border-color .14s ease, box-shadow .14s ease;
}
.auxiliary-block:hover { background: var(--color-fill-3); color: var(--color-text-1); }
.auxiliary-block.selected {
  border-color: rgba(var(--arcoblue-6), .95); color: var(--color-text-1);
  box-shadow: inset 0 0 0 1px rgba(var(--arcoblue-6), .24),
    0 0 0 1px rgba(var(--arcoblue-6), .38), 0 0 14px rgba(var(--arcoblue-6), .14);
}
.auxiliary-block:focus-visible { outline: 2px solid rgba(var(--arcoblue-6), .85); outline-offset: 2px; }
.auxiliary-block > span { min-width: 0; display: flex; align-items: center; gap: 7px; }
.auxiliary-block i { width: 3px; height: 14px; flex: 0 0 auto; border-radius: 2px; background: var(--color-border-3); }
.auxiliary-block.selected i { background: rgb(var(--arcoblue-6)); }
.auxiliary-block span b { overflow: hidden; font-size: 12px; font-weight: 600; text-overflow: ellipsis; white-space: nowrap; }
.auxiliary-block > b { flex: 0 0 auto; color: var(--color-text-1); font: 600 12px "Bahnschrift", "Segoe UI", sans-serif; }
.sub-cell {
  box-sizing: border-box; position: relative; min-height: 72px; padding: 10px 7px 8px; display: flex; flex-direction: column;
  align-items: center; justify-content: center; border: 0; color: rgba(255, 255, 255, .94);
  font-family: "Bahnschrift", "Segoe UI", sans-serif; cursor: pointer; isolation: isolate;
  transition: filter .12s ease, box-shadow .12s ease, transform .12s ease;
}
.sub-cell:not(:nth-child(4n)) { border-right: 1px solid rgba(0,0,0,.26); }
.sub-cell:nth-child(-n+12) { border-bottom: 1px solid rgba(0,0,0,.26); }
.sub-cell:hover { filter: brightness(1.07); z-index: 1; }
.sub-cell:active { transform: scale(.985); }
.sub-cell.selected { z-index: 2; box-shadow: inset 0 0 0 2px #91bdff; }
.sub-cell span { font-size: 11px; opacity: .78; }
.sub-cell b { margin-top: 3px; font-size: 12px; font-weight: 600; }
.detail-panel { min-width: 0; display: flex; flex-direction: column; background: color-mix(in srgb, var(--color-bg-2) 94%, var(--color-fill-1)); }
.detail-head { padding: 15px 16px; display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; border-bottom: 1px solid var(--color-border-2); }
.detail-title { min-width: 0; }
.detail-head h3 { margin: 0; color: var(--color-text-1); font-size: 16px; line-height: 1.35; }
.detail-head h3 small { color: var(--color-text-3); font-size: 11px; font-weight: 500; }
.detail-head p { margin: 5px 0 0; overflow: hidden; color: var(--color-text-4); font: 11px/1.4 "Bahnschrift", "Segoe UI", sans-serif; text-overflow: ellipsis; white-space: nowrap; }
.metric-scope-switch { flex: 0 0 auto; padding: 1px; display: flex; gap: 2px; border: 1px solid var(--color-border-2); border-radius: 5px; background: var(--color-fill-1); }
.metric-scope-switch button { min-height: 23px; padding: 2px 8px; border: 0; border-radius: 4px; background: transparent; color: var(--color-text-3); font: 10px/1.2 "Segoe UI", sans-serif; cursor: pointer; transition: color .12s ease, background-color .12s ease, box-shadow .12s ease; }
.metric-scope-switch button:hover { color: var(--color-text-1); }
.metric-scope-switch button.active { color: rgb(var(--arcoblue-6)); background: color-mix(in srgb, rgb(var(--arcoblue-6)) 12%, var(--color-fill-2)); box-shadow: inset 0 0 0 1px rgba(var(--arcoblue-6), .22); }
.metric-scope-switch button:focus-visible { outline: 2px solid rgba(var(--arcoblue-6), .78); outline-offset: 1px; }
.detail-summary { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); border-bottom: 1px solid var(--color-border-2); }
.detail-summary > div { min-height: 76px; padding: 12px 16px; display: flex; flex-direction: column; justify-content: center; }
.detail-summary > div + div { border-left: 1px solid var(--color-border-2); }
.detail-summary span { color: var(--color-text-4); font-size: 12px; }
.detail-summary b { margin-top: 6px; color: var(--color-text-1); font: 600 15px/1.2 "Bahnschrift", "Segoe UI", sans-serif; }
.detail-section-title { padding: 12px 16px 7px; display: flex; align-items: baseline; justify-content: space-between; }
.detail-section-title span { color: var(--color-text-2); font-size: 13px; font-weight: 600; }
.detail-section-title small { color: var(--color-text-4); font-size: 10px; }
.detail-list { flex: 1; margin: 0; padding: 0 16px 9px; display: flex; flex-direction: column; justify-content: space-evenly; list-style: none; }
.detail-row { padding: 7px 0; }
.detail-row-head { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.detail-row-head span { min-width: 0; overflow: hidden; color: var(--color-text-3); font-size: 12px; text-overflow: ellipsis; white-space: nowrap; }
.detail-row-head span i { width: 25px; display: inline-block; color: var(--color-text-4); font: normal 10px "Bahnschrift", sans-serif; }
.detail-row-head b { flex: 0 0 auto; color: var(--color-text-2); font: 600 12px "Bahnschrift", "Segoe UI", sans-serif; }
.detail-track { height: 3px; margin: 6px 0 0 25px; overflow: hidden; border-radius: 2px; background: var(--color-fill-3); }
.detail-track i { height: 100%; display: block; border-radius: inherit; opacity: .9; transition: width .18s ease; }
@media (max-width: 1050px) {
  .batch-field { flex: 1 1 100%; }
  .atlas-row { grid-template-columns: 1fr; }
}
@media (max-width: 680px) {
  .map-build-page { padding: 8px; }
  .filter-field, .scene-field, .batch-field { width: 100%; flex: 1 1 100%; }
  .filter-field :deep(.scene-select), .filter-field :deep(.batch-select) {
    min-width: 0; flex: 1 1 auto;
  }
  .block-layout { grid-template-columns: 1fr; }
  .atlas-card-footer { grid-template-columns: 1fr; }
  .auxiliary-block-list, .atlas-scope-control { grid-column: 1; }
  .world-head { padding-right: 10px; }
  .section-head { align-items: flex-start; padding: 11px 12px; gap: 8px; }
  .trend-controls { align-items: flex-end; flex-direction: column; }
  .trend-controls :deep(.days-select),
  .trend-controls :deep(.custom-range-picker) { max-width: 100%; }
  .sub-cell { min-height: 62px; }
}
</style>
