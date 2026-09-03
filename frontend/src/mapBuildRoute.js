import { inclusiveDateRangeDays, rollingDateRange } from './dateRange'

const COMPARISON_BATCH_PREFIX = 'batch:'
const ROLLING_MODE = 'rolling'
const FIXED_MODE = 'fixed'
const DEFAULT_WINDOW_DAYS = 30
const MAXIMUM_WINDOW_DAYS = 60

function firstValue(value) {
  return Array.isArray(value) ? value[0] : value
}

function parseNonNegativeInteger(value) {
  if (value === undefined || value === null || value === '') return null
  const parsed = Number(value)
  return Number.isInteger(parsed) && parsed >= 0 ? parsed : null
}

function normalizeQuery(query) {
  return Object.fromEntries(
    Object.entries(query || {})
      .filter(([, value]) => value !== undefined && value !== null && value !== '')
      .map(([key, value]) => [key, String(firstValue(value))])
      .sort(([left], [right]) => left.localeCompare(right)),
  )
}

function batchWindowDays(range) {
  if (!Array.isArray(range) || range.length !== 2) return 0
  return inclusiveDateRangeDays(range[0], range[1]) || 0
}

function rollingBatchRange(now = new Date()) {
  return rollingDateRange(DEFAULT_WINDOW_DAYS, now)
}

function batchWindowFromRoute(range, requestedMode, now = new Date()) {
  const days = batchWindowDays(range)
  if (requestedMode === FIXED_MODE && days >= 1 && days <= MAXIMUM_WINDOW_DAYS) {
    return { mode: FIXED_MODE, range: [...range] }
  }
  return { mode: ROLLING_MODE, range: rollingBatchRange(now) }
}

function batchWindowFromPicker(range, now = new Date()) {
  const days = batchWindowDays(range)
  if (!days) {
    return { valid: true, mode: ROLLING_MODE, range: rollingBatchRange(now) }
  }
  if (days > MAXIMUM_WINDOW_DAYS) {
    return {
      valid: false,
      message: `创建时间范围最多选择 ${MAXIMUM_WINDOW_DAYS} 天`,
    }
  }
  return { valid: true, mode: FIXED_MODE, range: [...range] }
}

/**
 * 烘培批次日期策略的唯一入口。调用方只需要区分滚动窗口和用户固定窗口，
 * 日期合法性、默认 30 天和最大 60 天都封装在这里。
 */
export const mapBuildBatchWindow = Object.freeze({
  rollingMode: ROLLING_MODE,
  fixedMode: FIXED_MODE,
  defaultDays: DEFAULT_WINDOW_DAYS,
  maximumDays: MAXIMUM_WINDOW_DAYS,
  days: batchWindowDays,
  rollingRange: rollingBatchRange,
  fromRoute: batchWindowFromRoute,
  fromPicker: batchWindowFromPicker,
})

function comparisonBatchValue(batchOrId) {
  const id = typeof batchOrId === 'object' ? batchOrId?.id : batchOrId
  return `${COMPARISON_BATCH_PREFIX}${id}`
}

function explicitComparisonBatchId(selection) {
  const value = String(selection || '')
  if (!value.startsWith(COMPARISON_BATCH_PREFIX)) return ''
  return value.slice(COMPARISON_BATCH_PREFIX.length).trim()
}

function comparisonRequestParams(selection) {
  const batchId = explicitComparisonBatchId(selection)
  if (batchId) return { comparison_mode: 'batch', comparison_batch_id: batchId }
  if (!selection) return { comparison_mode: 'off' }
  return { comparison_mode: 'previous' }
}

function comparisonFromResponse(comparison) {
  if (comparison?.selection === 'off') return ''
  if (comparison?.selection && comparison.selection !== 'previous') {
    return comparisonBatchValue(comparison.selection)
  }
  return 'previous'
}

/** 对比批次在 URL、选择框和后端参数之间的稳定编码。 */
export const mapBuildComparison = Object.freeze({
  batchValue: comparisonBatchValue,
  explicitBatchId: explicitComparisonBatchId,
  requestParams: comparisonRequestParams,
  fromResponse: comparisonFromResponse,
})

function routeQueryValue(route, name) {
  return firstValue(route.query?.[name])
}

function routeSceneId(route) {
  return firstValue(route.params?.sceneId) || ''
}

/**
 * 路由模块负责解析和生成完整工作区地址，页面不再散落 URL 兼容规则。
 */
export const mapBuildRoute = Object.freeze({
  queryValue: routeQueryValue,
  sceneId: routeSceneId,

  parse(route, { routeReady = false, now = new Date() } = {}) {
    const queryValue = (name) => routeQueryValue(route, name)
    const window = mapBuildBatchWindow.fromRoute(
      [queryValue('from'), queryValue('to')],
      queryValue('range_mode'),
      now,
    )
    const comparisonMode = String(queryValue('compare') || 'previous').trim()
    const comparisonBatchId = String(queryValue('compare_batch') || '').trim()
    const requestedBatchId = queryValue('batch') || ''
    // 页面内清空对比后保持关闭；浏览器重新进入旧 compare=off 地址时恢复默认对比。
    const comparisonSelection = comparisonMode === 'off' && requestedBatchId && routeReady
      ? ''
      : comparisonMode === 'batch' && comparisonBatchId
        ? mapBuildComparison.batchValue(comparisonBatchId)
        : 'previous'
    const blockIndex = parseNonNegativeInteger(queryValue('block'))
    return {
      batchId: requestedBatchId,
      comparisonSelection,
      batchDateRange: window.range,
      batchDateRangeMode: window.mode,
      metricScope: queryValue('scope') === 'subtree' ? 'subtree' : 'self',
      blockIndex,
      subBlockIndex: blockIndex === null
        ? null
        : parseNonNegativeInteger(queryValue('sub')),
      registryPath: queryValue('registry') || null,
    }
  },

  location({
    sceneId,
    branchTag,
    rangeMode,
    batchDateRange,
    hasOverview,
    batchId,
    comparisonSelection,
    metricScope,
    selection,
  }) {
    const path = sceneId ? `/map-build/${encodeURIComponent(sceneId)}` : '/map-build'
    const query = {
      branch_tag: branchTag,
      range_mode: rangeMode,
    }
    if (
      rangeMode === mapBuildBatchWindow.fixedMode
      && mapBuildBatchWindow.days(batchDateRange) >= 1
    ) {
      query.from = batchDateRange[0]
      query.to = batchDateRange[1]
    }
    if (!hasOverview) return { path, query }

    const comparisonBatchId = mapBuildComparison.explicitBatchId(comparisonSelection)
    Object.assign(query, {
      batch: String(batchId),
      compare: !comparisonSelection ? 'off' : comparisonBatchId ? 'batch' : 'previous',
      scope: metricScope,
    })
    if (comparisonBatchId) query.compare_batch = comparisonBatchId
    if (selection.registryPath !== null) query.registry = selection.registryPath
    else if (selection.blockIndex !== null) {
      query.block = String(selection.blockIndex)
      if (selection.subBlockIndex !== null) query.sub = String(selection.subBlockIndex)
    }
    return { path, query }
  },

  matches(route, location) {
    return route.path === location.path
      && JSON.stringify(normalizeQuery(route.query)) === JSON.stringify(normalizeQuery(location.query))
  },
})
