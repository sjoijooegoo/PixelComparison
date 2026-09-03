<script setup>
import { computed, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api, isRequestCancelled } from '../api'
import { p4Label } from '../store'
import { useProjectStore } from '../stores/projectStore'
import {
  metricComparisonPercentRange,
} from '../mapBuildPresentation'
import MapBuildDetailPanel from '../components/MapBuildDetailPanel.vue'
import MapBuildAtlas from '../components/MapBuildAtlas.vue'
import MapBuildTrendChart from '../components/MapBuildTrendChart.vue'
import { vNoNativeTitle } from '../directives/noNativeTitle'
import { registerPageRefresh } from '../pageActions'
import { createLatestRequestChannels } from '../latestRequestChannels'
import { mapBuildBatchWindow, mapBuildComparison, mapBuildRoute } from '../mapBuildRoute'

const store = useProjectStore()
const route = useRoute()
const router = useRouter()
const meta = ref({ scene_ids: [] })
const overview = ref(null)
const trend = ref({ selection: { label: '主分块 · 仅自身' }, points: [] })
const filters = reactive({
  branchTag: 'main',
  sceneId: '',
  batchId: '',
  comparisonSelection: 'previous',
  batchDateRange: [],
})
const selection = reactive({ blockIndex: null, subBlockIndex: null, registryPath: null })
const metricScope = ref('self')
const metaLoading = ref(false)
const overviewLoading = ref(false)
const trendLoading = ref(false)
const batchWindowEmpty = ref(false)
const error = ref('')
const routeReady = ref(false)
const batchDateRangeMode = ref(mapBuildBatchWindow.rollingMode)
const loadedBatchDateRange = ref([])
const loadedBatchDateRangeMode = ref(mapBuildBatchWindow.rollingMode)
const requestChannels = createLatestRequestChannels(['meta', 'overview', 'trend'])
let unregisterPageRefresh = null
let routeApplySequence = 0

function keepOrDefault(current, options, preferred = null) {
  const values = options.map((option) => option?.value ?? option)
  if (values.includes(current)) return current
  if (preferred !== null && values.includes(preferred)) return preferred
  return values[0] ?? ''
}

function trendSelectionLabel(label) {
  return (label || '主分块 · 仅自身').replace('自身数据', '仅自身')
}

function clearTrendData() {
  requestChannels.invalidate('trend')
  trend.value = { selection: { label: '主分块 · 仅自身' }, points: [] }
  trendLoading.value = false
}

function clearSceneData() {
  requestChannels.invalidate('overview')
  clearTrendData()
  overview.value = null
  filters.batchId = ''
  filters.comparisonSelection = 'previous'
  batchWindowEmpty.value = false
  overviewLoading.value = false
}

function availableBranchTag(value) {
  const normalized = String(value || 'main').trim().toLowerCase()
  return store.meta.branch_tags?.includes(normalized) ? normalized : 'main'
}

function applyAnalysisState(state) {
  filters.batchId = state.batchId
  filters.comparisonSelection = state.comparisonSelection
  filters.batchDateRange = state.batchDateRange
  batchDateRangeMode.value = state.batchDateRangeMode
  metricScope.value = state.metricScope
  selection.registryPath = state.registryPath
  selection.blockIndex = state.registryPath === null ? state.blockIndex : null
  selection.subBlockIndex = state.registryPath === null ? state.subBlockIndex : null
}

async function syncAnalysisRoute() {
  if (!route.path.startsWith('/map-build')) return
  const location = mapBuildRoute.location({
    sceneId: filters.sceneId,
    branchTag: filters.branchTag,
    rangeMode: batchDateRangeMode.value,
    batchDateRange: filters.batchDateRange,
    hasOverview: Boolean(overview.value),
    batchId: filters.batchId,
    comparisonSelection: filters.comparisonSelection,
    metricScope: metricScope.value,
    selection,
  })
  if (mapBuildRoute.matches(route, location)) return
  await router.replace(location)
}

async function loadMeta(requestedSceneId) {
  const request = requestChannels.begin('meta')
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
  const request = requestChannels.begin('overview')
  overviewLoading.value = true
  try {
    const params = {
      branch_tag: filters.branchTag,
      batch_id: requestedBatchId,
      ...mapBuildComparison.requestParams(filters.comparisonSelection),
    }
    if (
      batchDateRangeMode.value === mapBuildBatchWindow.fixedMode
      && mapBuildBatchWindow.days(filters.batchDateRange) >= 1
    ) {
      params.batch_start = filters.batchDateRange[0]
      params.batch_end = filters.batchDateRange[1]
    }
    const data = await api.mapBuildOverview(
      filters.sceneId,
      params,
      { signal: request.signal },
    )
    if (!request.isLatest()) return null
    overview.value = data
    batchWindowEmpty.value = false
    const resolvedBatchDateRange = [
      data.batch_window?.start_date,
      data.batch_window?.end_date,
    ]
    if (mapBuildBatchWindow.days(resolvedBatchDateRange) >= 1) {
      filters.batchDateRange = resolvedBatchDateRange
    }
    loadedBatchDateRange.value = [...filters.batchDateRange]
    loadedBatchDateRangeMode.value = batchDateRangeMode.value
    filters.batchId = data.batch.id
    filters.comparisonSelection = mapBuildComparison.fromResponse(data.comparison)
    if (!selectionExists(data)) {
      selection.blockIndex = null
      selection.subBlockIndex = null
      selection.registryPath = null
    }
    normalizeMetricScope(data)
    return data
  } catch (cause) {
    if (isRequestCancelled(cause) || !request.isLatest()) return null
    if (cause?.status === 404) {
      requestChannels.invalidate('trend')
      overview.value = null
      trend.value = { selection: { label: '主分块 · 仅自身' }, points: [] }
      filters.batchId = ''
      filters.comparisonSelection = ''
      selection.blockIndex = null
      selection.subBlockIndex = null
      selection.registryPath = null
      loadedBatchDateRange.value = [...filters.batchDateRange]
      loadedBatchDateRangeMode.value = batchDateRangeMode.value
      batchWindowEmpty.value = true
      trendLoading.value = false
      error.value = ''
      return null
    }
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
  if (mapBuildBatchWindow.days(filters.batchDateRange) < 1) return null
  const request = requestChannels.begin('trend')
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
      start_date: filters.batchDateRange[0],
      end_date: filters.batchDateRange[1],
      metric_scope: effectiveMetricScope,
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
  error.value = ''
  clearTrendData()
  filters.batchId = ''
  // “关闭对比”只属于原场景的当前分析状态；进入新场景时重新采用默认上一批次。
  filters.comparisonSelection = 'previous'
  selection.blockIndex = null
  selection.subBlockIndex = null
  selection.registryPath = null
  if (!selectedSceneHasData.value) {
    clearSceneData()
    return
  }
  const loadedOverview = await loadOverview('')
  if (
    loadedOverview
    && filters.sceneId === requestedSceneId
  ) {
    await loadTrend()
  }
}

async function changeScene() {
  await loadSelectedScene()
  await syncAnalysisRoute()
}

async function changeBranch() {
  filters.branchTag = availableBranchTag(filters.branchTag)
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
  const nextBranchTag = availableBranchTag(mapBuildRoute.queryValue(route, 'branch_tag'))
  if (filters.branchTag !== nextBranchTag) {
    filters.branchTag = nextBranchTag
    clearSceneData()
    applyAnalysisState(mapBuildRoute.parse(route, { routeReady: routeReady.value }))
    const loadedMeta = await loadMeta(mapBuildRoute.sceneId(route))
    if (sequence !== routeApplySequence) return
    if (loadedMeta && filters.sceneId && selectedSceneHasData.value) {
      const loadedOverview = await loadOverview(filters.batchId)
      if (loadedOverview) await loadTrend()
    }
    await syncAnalysisRoute()
    return
  }
  const preferredSceneId = meta.value.scene_ids[0]?.value || ''
  const nextSceneId = keepOrDefault(mapBuildRoute.sceneId(route), sceneOptions.value, preferredSceneId)
  const nextState = mapBuildRoute.parse(route, { routeReady: routeReady.value })
  const sceneChanged = filters.sceneId !== nextSceneId
  const batchChanged = String(filters.batchId) !== String(nextState.batchId)
  const comparisonChanged = filters.comparisonSelection !== nextState.comparisonSelection
  const batchDateRangeChanged = batchDateRangeMode.value !== nextState.batchDateRangeMode
    || (
      nextState.batchDateRangeMode === mapBuildBatchWindow.fixedMode
      && filters.batchDateRange.join('|') !== nextState.batchDateRange.join('|')
    )
  const trendAnalysisChanged = metricScope.value !== nextState.metricScope
    || selection.blockIndex !== nextState.blockIndex
    || selection.subBlockIndex !== nextState.subBlockIndex
    || selection.registryPath !== nextState.registryPath
  if (
    !sceneChanged
    && !batchChanged
    && !comparisonChanged
    && !batchDateRangeChanged
    && !trendAnalysisChanged
  ) return

  const previousBatchId = overview.value?.batch?.id ?? ''
  const previousComparisonSelection = filters.comparisonSelection
  const previousBatchDateRange = [...loadedBatchDateRange.value]
  const previousBatchDateRangeMode = loadedBatchDateRangeMode.value
  if (sceneChanged) {
    filters.sceneId = nextSceneId
    overview.value = null
    clearTrendData()
  }
  applyAnalysisState(nextState)
  if (!filters.sceneId || !selectedSceneHasData.value) {
    clearSceneData()
    await syncAnalysisRoute()
    return
  }

  let failed = false
  if (sceneChanged || batchChanged || comparisonChanged || batchDateRangeChanged) {
    const loaded = await loadOverview(nextState.batchId, {
      preserveOnError: !sceneChanged,
      onFailure: () => { failed = true },
    })
    if (sequence !== routeApplySequence) return
    if (failed && !sceneChanged) {
      filters.batchId = previousBatchId
      filters.comparisonSelection = previousComparisonSelection
      filters.batchDateRange = previousBatchDateRange
      batchDateRangeMode.value = previousBatchDateRangeMode
    }
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
  if (sceneChanged || batchChanged || batchDateRangeChanged || trendAnalysisChanged) {
    await loadTrend({ preserveOnError: !sceneChanged })
    if (sequence !== routeApplySequence) return
  }
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

async function changeComparisonBatch() {
  error.value = ''
  const requestedSelection = filters.comparisonSelection
  const previousSelection = mapBuildComparison.fromResponse(overview.value?.comparison)
  let failed = false
  const loaded = await loadOverview(filters.batchId, {
    preserveOnError: true,
    onFailure: () => { failed = true },
  })
  if (failed && filters.comparisonSelection === requestedSelection) {
    filters.comparisonSelection = previousSelection
  }
  await syncAnalysisRoute()
}

async function changeBatchDateRange(range) {
  error.value = ''
  const nextWindow = mapBuildBatchWindow.fromPicker(range)
  if (!nextWindow.valid) {
    error.value = nextWindow.message
    filters.batchDateRange = [...loadedBatchDateRange.value]
    return
  }
  const requestedBatchDateRange = nextWindow.range
  const requestedRangeMode = nextWindow.mode
  const previousBatchDateRange = [...loadedBatchDateRange.value]
  const previousBatchDateRangeMode = loadedBatchDateRangeMode.value
  const previousComparisonSelection = filters.comparisonSelection
  filters.batchDateRange = requestedBatchDateRange
  batchDateRangeMode.value = requestedRangeMode
  filters.comparisonSelection = 'previous'
  const loaded = await loadOverview('', { preserveOnError: true })
  if (loaded) await loadTrend({ preserveOnError: true })
  if (
    !loaded
    && !batchWindowEmpty.value
    && batchDateRangeMode.value === requestedRangeMode
    && filters.batchDateRange.join('|') === requestedBatchDateRange.join('|')
  ) {
    filters.batchDateRange = previousBatchDateRange
    batchDateRangeMode.value = previousBatchDateRangeMode
    filters.comparisonSelection = previousComparisonSelection
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

async function refresh() {
  error.value = ''
  if (batchDateRangeMode.value === mapBuildBatchWindow.rollingMode) {
    filters.batchDateRange = mapBuildBatchWindow.rollingRange()
  }
  const loaded = await loadMeta()
  if (!loaded) return
  if (!filters.sceneId || !selectedSceneHasData.value) {
    clearSceneData()
    await syncAnalysisRoute()
    return
  }
  // 刷新代表获取当前筛选下的最新烘培批次；空 batch_id 由后端选择最新项。
  const loadedOverview = await loadOverview('', { preserveOnError: true })
  if (loadedOverview) {
    await loadTrend({ preserveOnError: true })
    await syncAnalysisRoute()
  }
}

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
function sceneHasMapBuildData(sceneId) {
  if (metaLoading.value) return null
  return mapBuildSceneIds.value.has(sceneId)
}
const comparisonBatch = computed(() => overview.value?.comparison?.batch || null)
const comparisonCandidates = computed(() => overview.value?.comparison?.available_batches || [])
const selectableComparisonCandidates = computed(() => comparisonCandidates.value.filter(
  (batch) => String(batch.id) !== String(overview.value?.batch?.id),
))
const defaultComparisonBatch = computed(() => (
  overview.value?.comparison?.default_batch
  || (overview.value?.comparison?.selection === 'previous' ? comparisonBatch.value : null)
))
const comparisonAvailable = computed(() => Boolean(comparisonBatch.value))
const comparisonSelectTitle = computed(() => {
  if (!selectedSceneHasData.value) return '当前场景没有烘培数据'
  if (!selectableComparisonCandidates.value.length) return '没有可用的对比批次'
  return undefined
})
const comparisonPercentRange = computed(() => {
  if (!comparisonAvailable.value || !overview.value) return [0, 0]
  const pairs = []
  const addNode = (node, scope = gridHeaderScope(node)) => {
    if (!node) return
    const current = scope === 'self'
      ? node.self_metrics || node.metrics
      : node.subtree_metrics || node.metrics
    pairs.push({ current, previous: node.comparison_metrics?.[scope] || null })
  }
  addNode(overview.value.world)
  for (const block of overview.value.blocks || []) {
    addNode(block)
    for (const cell of block.sub_blocks || []) addNode(cell, 'self')
  }
  for (const block of overview.value.auxiliary_blocks || []) addNode(block)
  return metricComparisonPercentRange(pairs)
})
const comparisonDisplayProps = computed(() => ({
  enabled: comparisonAvailable.value,
  baselineAvailable: comparisonAvailable.value,
  comparisonLabel: '对比批次',
  percentRange: comparisonPercentRange.value,
}))
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
    comparisonMetrics: node.comparison_metrics?.[effectiveScope] || null,
    effectiveScope,
  }
})
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
function batchLabel(batch, isLatest = false) {
  const date = batch.created_at?.replace('T', ' ').slice(0, 16) || '—'
  return `${p4Label(batch.p4_version)} · ${date}${isLatest ? '（最新）' : ''}`
}

function comparisonOptionValue(batch) {
  if (String(batch.id) === String(overview.value?.batch?.id)) {
    return `baseline:${batch.id}`
  }
  return String(batch.id) === String(defaultComparisonBatch.value?.id)
    ? 'previous'
    : mapBuildComparison.batchValue(batch)
}

function comparisonOptionLabel(batch) {
  const label = batchLabel(batch)
  return String(batch.id) === String(overview.value?.batch?.id)
    ? `${label}（当前基线）`
    : label
}

onMounted(async () => {
  unregisterPageRefresh = registerPageRefresh(refresh)
  const requestedBranchTag = mapBuildRoute.queryValue(route, 'branch_tag') || 'main'
  // bootstrap 会先启动项目初始化再挂载页面。等待同一轮初始化完成后再校验
  // 深链分支，避免 meta 尚只有默认 main 时把有效的 engine-ue5 错误回退。
  if (!store.initialized && typeof store.init === 'function') {
    try {
      await store.init()
    } catch {
      // 页面自己的错误态会继续承接 map-build 请求失败，外壳仍保持可操作。
    }
  }
  filters.branchTag = availableBranchTag(requestedBranchTag)
  applyAnalysisState(mapBuildRoute.parse(route, { routeReady: routeReady.value }))
  // 与热力图一致，浏览器重新进入/刷新工作区时跳到最新批次；
  // 用户在页面内主动选择历史批次仍会立即生效并同步 URL。
  filters.batchId = ''
  const loaded = await loadMeta(mapBuildRoute.sceneId(route))
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
    route.query?.compare,
    route.query?.compare_batch,
    route.query?.range_mode,
    route.query?.from,
    route.query?.to,
    route.query?.scope,
    route.query?.block,
    route.query?.sub,
    route.query?.registry,
  ],
  applyRouteState,
)
onUnmounted(() => {
  unregisterPageRefresh?.()
  requestChannels.abortAll()
})
</script>

<template>
  <div class="map-build-page">
    <div class="map-build-shell">
      <section v-no-native-title class="toolbar card" aria-label="烘培数据筛选">
        <div class="filter-field branch-field">
          <span class="label">分支</span>
          <a-select v-model="filters.branchTag" size="small" style="width: 160px"
            popup-container=".map-build-page"
            @change="changeBranch">
            <a-option v-for="branch in store.meta.branch_tags" :key="branch" :value="branch">
              {{ branch }}
            </a-option>
          </a-select>
        </div>
        <div class="filter-field scene-field">
          <span class="label">场景ID</span>
          <a-select v-model="filters.sceneId" class="scene-select" :loading="metaLoading"
            placeholder="全部场景" allow-clear allow-search size="small"
            popup-container=".map-build-page"
            @change="changeScene">
            <a-option v-for="scene in sceneOptions" :key="scene" :value="scene">
              <span class="scene-option">
                <span class="scene-option-name"
                  :class="{ 'is-data-empty': sceneHasMapBuildData(scene) === false }"
                  :title="sceneHasMapBuildData(scene) === false ? '当前分支没有烘培数据' : undefined">
                  {{ scene }}
                </span>
                <span v-if="unlistedSceneIds.has(scene)" class="unlisted">未配置</span>
              </span>
            </a-option>
          </a-select>
        </div>
        <div class="filter-field batch-date-field">
          <span class="label">创建时间</span>
          <a-range-picker :model-value="filters.batchDateRange" class="batch-date-picker"
            :disabled="!selectedSceneHasData" size="small" value-format="YYYY-MM-DD"
            format="YYYY-MM-DD" :placeholder="['开始日期', '结束日期']" allow-clear
            @change="changeBatchDateRange" />
        </div>
        <div class="filter-field batch-field">
          <span class="label">基线批次</span>
          <a-select v-model="filters.batchId" class="batch-select" :loading="overviewLoading"
            :disabled="!selectedSceneHasData" allow-search size="small"
            popup-container=".map-build-page"
            @change="changeBatch">
            <a-option v-for="(batch, index) in overview?.available_batches || []"
              :key="batch.id" :value="batch.id">
              {{ batchLabel(batch, index === 0) }}
            </a-option>
          </a-select>
        </div>
        <div class="filter-field compare-field" :title="comparisonSelectTitle">
          <span class="label">对比批次</span>
          <a-select v-model="filters.comparisonSelection" class="compare-select"
            :disabled="!selectedSceneHasData || selectableComparisonCandidates.length === 0"
            allow-clear allow-search placeholder="选择对比批次"
            size="small"
            popup-container=".map-build-page"
            @change="changeComparisonBatch">
            <a-option v-for="batch in comparisonCandidates" :key="batch.id"
              :value="comparisonOptionValue(batch)" :label="comparisonOptionLabel(batch)"
              :disabled="String(batch.id) === String(overview?.batch?.id)">
              {{ comparisonOptionLabel(batch) }}
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
      <div v-else-if="batchWindowEmpty" class="page-state card date-range-empty" role="status">
        <div class="state-glyph">▦</div>
        <div class="state-title">当前时间范围没有烘培数据</div>
        <div class="state-sub">请调整上方的创建时间范围。</div>
      </div>

      <template v-else>
        <div class="atlas-row">
          <div v-if="overviewLoading && overview" class="overview-loading-veil" aria-live="polite">
            <a-spin />
            <span>正在切换批次…</span>
          </div>
          <MapBuildAtlas :overview="overview" :loading="overviewLoading"
            :selection-key="selectionKey" :metric-scope="metricScope"
            :comparison-props="comparisonDisplayProps"
            @select="choose" @select-auxiliary="chooseAuxiliary"
            @change-metric-scope="changeMetricScope" />

          <MapBuildDetailPanel v-if="selectedDetail" :detail="selectedDetail"
            :comparison-props="comparisonDisplayProps" />
        </div>

        <section class="trend-card card">
          <header class="section-head">
            <div class="section-title">
              <span>数据趋势</span>
              <span class="selection-pill">{{ trendSelectionLabel(trend.selection?.label) }}</span>
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
.map-build-page { position: relative; flex: 1; min-height: 0; overflow: auto; padding: 10px 12px 18px; }
.map-build-shell { width: min(1760px, 100%); margin: 0 auto; display: flex; flex-direction: column; gap: 10px; }
.toolbar {
  padding: 10px 14px; display: flex; flex-wrap: wrap; align-items: center;
  gap: 10px 16px; overflow: visible;
}
.filter-field { min-width: 0; display: flex; align-items: center; gap: 6px; }
.filter-field .label { flex: 0 0 auto; color: var(--color-text-3); font-size: 12px; white-space: nowrap; }
.scene-field { flex: 0 0 auto; }
.batch-field,
.compare-field { flex: 1 1 222px; max-width: 410px; }
.batch-date-field { flex: 0 0 auto; }
.scene-field :deep(.scene-select) { width: clamp(240px, 17vw, 320px); }
.batch-field :deep(.batch-select),
.compare-field :deep(.compare-select) { width: 168px; min-width: 168px; flex: 1 1 168px; }
.batch-date-field :deep(.batch-date-picker) { width: 240px; }
.scene-option { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.scene-option-name.is-data-empty { color: var(--color-text-4); }
.unlisted { color: var(--color-text-3); font-size: 11px; }
.page-state { min-height: 420px; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 8px; color: var(--color-text-3); }
.state-glyph { font-size: 38px; color: var(--color-text-4); }
.state-title { color: var(--color-text-2); font-size: 15px; font-weight: 600; }
.state-sub { color: var(--color-text-4); font-size: 12px; }
.trend-card { overflow: hidden; }
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
.section-head { min-height: 50px; padding: 0 16px; display: flex; align-items: center; justify-content: space-between; border-bottom: 1px solid var(--color-border-1); }
.section-title { display: flex; align-items: center; gap: 10px; font-size: 14px; font-weight: 600; }
.selection-pill { padding: 4px 9px; border-radius: 5px; border: 1px solid var(--color-border-2); color: var(--color-text-3); font-size: 11px; font-weight: 500; }
.trend-body { position: relative; min-height: 300px; padding: 12px 14px 4px 4px; transition: opacity .15s ease; }
.trend-body.loading > :first-child { opacity: .55; }
.loading-veil { position: absolute; inset: 0; display: grid; place-items: center; pointer-events: none; }
@media (max-width: 1050px) {
  .batch-field { flex: 1 1 100%; }
  .atlas-row { grid-template-columns: 1fr; }
}
@media (max-width: 680px) {
  .map-build-page { padding: 8px; }
  .filter-field, .scene-field, .batch-field, .compare-field, .batch-date-field { width: 100%; flex: 1 1 100%; }
  .filter-field :deep(.scene-select), .filter-field :deep(.batch-select), .filter-field :deep(.compare-select),
  .filter-field :deep(.batch-date-picker) {
    min-width: 0; flex: 1 1 auto;
  }
  .section-head { align-items: flex-start; padding: 11px 12px; gap: 8px; }
}
</style>
