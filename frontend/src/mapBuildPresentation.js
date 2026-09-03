const MIB = 1024 * 1024

export const MAP_BUILD_DELTA_COLORS = Object.freeze({
  strongDecrease: '#52e817',
  neutral: '#b6abb2',
  mediumIncrease: '#f0789a',
  strongIncrease: '#ff1111',
})

export const MAP_BUILD_DETAIL_METRICS = [
  { key: 'lightmap_all_mips_bytes', label: '光照贴图纹理', color: '#4b91f1' },
  { key: 'shadowmap_all_mips_bytes', label: '阴影贴图纹理', color: '#62aaa6' },
  { key: 'hue_all_mips_bytes', label: '色相纹理', color: '#a77ae6' },
  { key: 'precomputed_light_volume_bytes', label: '预计算光照体积', color: '#5d8cc7' },
  { key: 'precomputed_reflection_volume_bytes', label: '预计算反射体积', color: '#6d83a8' },
  { key: 'volumetric_lightmap_bytes', label: '体积光照贴图', color: '#7d72c7' },
  { key: 'reflection_capture_bytes', label: '反射捕获', color: '#4d9b93' },
  { key: 'mesh_map_build_data_bytes', label: '网格构建数据', color: '#8b785f' },
  { key: 'light_build_data_bytes', label: '光照构建数据', color: '#8a6e9d' },
  { key: 'precomputed_instanced_ilc_bytes', label: '预计算实例 ILC', color: '#728f84' },
  { key: 'precomputed_instanced_pr_bytes', label: '预计算实例 PR', color: '#817b94' },
  { key: 'lightmap_resource_cluster_bytes', label: '光照贴图资源簇', color: '#8b8372' },
]

const DEFAULT_DETAIL_SERIES_KEYS = new Set([
  'lightmap_all_mips_bytes',
  'shadowmap_all_mips_bytes',
  'hue_all_mips_bytes',
])

export const MAP_BUILD_COMPARISON_METRIC_KEYS = [
  'all_mips_bytes',
  'cook_estimate_bytes',
  'texture_count',
  ...MAP_BUILD_DETAIL_METRICS.map((metric) => metric.key),
]

export const MAP_BUILD_SERIES = [
  { key: 'all_mips_bytes', label: '总 Mip', color: '#e8952d', defaultVisible: true },
  { key: 'cook_estimate_bytes', label: 'Cook 估算', color: '#91a4bb', defaultVisible: true },
  ...MAP_BUILD_DETAIL_METRICS.map((metric) => ({
    ...metric,
    defaultVisible: DEFAULT_DETAIL_SERIES_KEYS.has(metric.key),
  })),
]

/** 字节指标才参与排行；纹理数等不同单位由界面单独展示。 */
export function rankMetricDetails(metrics = {}, comparisonMetrics = null) {
  return MAP_BUILD_DETAIL_METRICS
    .map((metric, order) => ({
      ...metric,
      order,
      value: Number(metrics?.[metric.key] || 0),
      previousValue: comparisonMetrics?.[metric.key] ?? null,
    }))
    .sort((left, right) => right.value - left.value || left.order - right.order)
}

/**
 * 变化率只在展示时派生，不写入数据库。按一位小数归零，避免出现 0.0% 仍带箭头。
 */
export function compareMetricValues(currentValue, previousValue, baselineAvailable = true) {
  const current = Number(currentValue)
  if (!baselineAvailable || !Number.isFinite(current)) {
    return { kind: 'unavailable', current, previous: null, delta: null, percent: null }
  }
  if (previousValue === null || previousValue === undefined || !Number.isFinite(Number(previousValue))) {
    return { kind: 'added', current, previous: null, delta: null, percent: null }
  }
  const previous = Number(previousValue)
  const delta = current - previous
  if (previous === 0) {
    if (current === 0) return { kind: 'steady', current, previous, delta, percent: 0 }
    return { kind: 'added', current, previous, delta, percent: null }
  }
  const percent = delta / Math.abs(previous) * 100
  const roundedPercent = Number(percent.toFixed(1))
  return {
    kind: roundedPercent === 0 ? 'steady' : roundedPercent > 0 ? 'increase' : 'decrease',
    current,
    previous,
    delta,
    percent: roundedPercent === 0 ? 0 : roundedPercent,
  }
}

function interpolateHexColor(start, end, ratio) {
  const progress = Math.min(1, Math.max(0, Number(ratio) || 0))
  const startValue = Number.parseInt(start.slice(1), 16)
  const endValue = Number.parseInt(end.slice(1), 16)
  const channel = (shift) => Math.round(
    ((startValue >> shift) & 0xff) * (1 - progress)
      + ((endValue >> shift) & 0xff) * progress,
  )
  return `#${[16, 8, 0]
    .map((shift) => channel(shift).toString(16).padStart(2, '0'))
    .join('')}`
}

/**
 * 以 0 为中性色分别归一化上升和下降区间，得到连续的语义色阶。
 * 上升侧增加粉色控制点，避免灰色直接过渡到红色时显得浑浊。
 */
export function mapBuildDeltaColor(comparison, percentRange = [0, 0]) {
  const { kind, percent } = comparison || {}
  if (kind === 'added') return MAP_BUILD_DELTA_COLORS.strongIncrease

  const [minimum = 0, maximum = 0] = percentRange.map(Number)
  if (kind === 'decrease') {
    const range = Math.abs(Math.min(0, minimum))
    const ratio = range > 0 ? Math.abs(percent) / range : 1
    return interpolateHexColor(
      MAP_BUILD_DELTA_COLORS.neutral,
      MAP_BUILD_DELTA_COLORS.strongDecrease,
      ratio,
    )
  }

  if (kind === 'increase') {
    const range = Math.max(0, maximum)
    const ratio = Math.min(1, Math.max(0, range > 0 ? percent / range : 1))
    const pinkPosition = 0.55
    if (ratio <= pinkPosition) {
      return interpolateHexColor(
        MAP_BUILD_DELTA_COLORS.neutral,
        MAP_BUILD_DELTA_COLORS.mediumIncrease,
        ratio / pinkPosition,
      )
    }
    return interpolateHexColor(
      MAP_BUILD_DELTA_COLORS.mediumIncrease,
      MAP_BUILD_DELTA_COLORS.strongIncrease,
      (ratio - pinkPosition) / (1 - pinkPosition),
    )
  }

  return undefined
}

function robustPercentEndpoint(values) {
  if (!values.length) return 0
  const sorted = [...values].sort((left, right) => left - right)
  if (sorted.length < 10) return sorted.at(-1)
  return sorted[Math.floor((sorted.length - 1) * 0.9)]
}

/**
 * 根据指定指标计算动态变化率范围，并以 0 作为语义中点。
 * 样本充足时分别取正负 P90，避免单个极端指标压缩其余颜色差异。
 */
export function metricComparisonPercentRange(
  metricPairs,
  metricKeys = MAP_BUILD_COMPARISON_METRIC_KEYS,
) {
  const decreases = []
  const increases = []
  for (const pair of metricPairs || []) {
    const currentMetrics = pair?.current
    if (!currentMetrics) continue
    for (const key of metricKeys) {
      if (!(key in currentMetrics)) continue
      const comparison = compareMetricValues(currentMetrics[key], pair.previous?.[key])
      if (!Number.isFinite(comparison.percent)) continue
      if (comparison.percent < 0) decreases.push(Math.abs(comparison.percent))
      if (comparison.percent > 0) increases.push(comparison.percent)
    }
  }
  const decreaseEndpoint = robustPercentEndpoint(decreases)
  return [
    decreaseEndpoint ? -decreaseEndpoint : 0,
    robustPercentEndpoint(increases),
  ]
}

export function formatMetricDelta(comparison) {
  if (!comparison || comparison.kind === 'unavailable') return '—'
  if (comparison.kind === 'added') return '新增'
  if (comparison.kind === 'steady') return '0.0%'
  const arrow = comparison.kind === 'increase' ? '↑' : '↓'
  return `${arrow}${Math.abs(comparison.percent).toFixed(1)}%`
}

export function bytesToMiB(value) {
  return Number(value || 0) / MIB
}

export function formatBytes(value) {
  if (value === null || value === undefined || !Number.isFinite(Number(value))) return '—'
  const bytes = Number(value)
  if (Math.abs(bytes) < 1024) return `${Math.round(bytes)} B`
  if (Math.abs(bytes) < MIB) return `${(bytes / 1024).toFixed(2)} KiB`
  return `${(bytes / MIB).toFixed(2)} MiB`
}

/** 烘培网格固定使用 MiB；极小值使用阈值文案，避免无意义的长小数。 */
export function formatMiB(value) {
  if (value === null || value === undefined || !Number.isFinite(Number(value))) return '—'
  const mib = Number(value) / MIB
  const absolute = Math.abs(mib)
  if (absolute === 0) return '0.00 MiB'
  if (absolute < 0.001) return '<0.001 MiB'
  const digits = absolute < 1 ? 3 : 2
  return `${mib.toFixed(digits)} MiB`
}

/** 悬停提示保留原始字节数，不让紧凑显示损失精确信息。 */
export function formatExactBytes(value) {
  if (value === null || value === undefined || !Number.isFinite(Number(value))) return '—'
  return `${Number(value).toLocaleString('zh-CN', { maximumFractionDigits: 0 })} B`
}

export function trendDayKey(point) {
  return point?.batch?.created_at?.slice(0, 10) || ''
}

/** 同一天有多批时把时刻带到横轴，悬浮提示还会继续展示唯一批次号。 */
export function trendAxisLabel(point, duplicateDay = false) {
  const createdAt = point?.batch?.created_at || ''
  const day = createdAt.slice(5, 10) || '—'
  const time = createdAt.slice(11, 16)
  return duplicateDay && time ? `${day} ${time}` : day
}

function mix(from, to, amount) {
  const a = from.match(/[a-f\d]{2}/gi).map((part) => parseInt(part, 16))
  const b = to.match(/[a-f\d]{2}/gi).map((part) => parseInt(part, 16))
  const rgb = a.map((value, index) => Math.round(value + (b[index] - value) * amount))
  return `rgb(${rgb.join(', ')})`
}

const ATLAS_COLOR_STOPS = [
  { at: 0, color: '#214876' },
  { at: 0.2, color: '#475d70' },
  { at: 0.34, color: '#756959' },
  { at: 0.65, color: '#b37939' },
  { at: 1, color: '#de8423' },
]

/**
 * 色标取自参考图中避开文字和边框后的单元格底色。
 * 使用全局 value / maximum 归一化，并在蓝、灰蓝、暖灰、琥珀和橙色之间线性插值。
 */
export function atlasColor(value, maximum) {
  const max = Number(maximum)
  const numericValue = Number(value)
  if (!Number.isFinite(max) || max <= 0 || value === null || value === undefined
    || !Number.isFinite(numericValue)) {
    return 'rgb(33, 72, 118)'
  }
  const ratio = Math.max(0, Math.min(1, Math.max(0, numericValue) / max))
  const upperIndex = ATLAS_COLOR_STOPS.findIndex((stop) => ratio <= stop.at)
  if (upperIndex <= 0) return 'rgb(33, 72, 118)'
  const lower = ATLAS_COLOR_STOPS[upperIndex - 1]
  const upper = ATLAS_COLOR_STOPS[upperIndex]
  return mix(lower.color, upper.color, (ratio - lower.at) / (upper.at - lower.at))
}

export function niceChartMaximum(values) {
  const maximum = Math.max(0, ...values.filter(Number.isFinite))
  if (!maximum) return 1
  const rough = maximum / 4
  const magnitude = 10 ** Math.floor(Math.log10(rough))
  const normalized = rough / magnitude
  const steps = [1, 1.25, 2, 2.5, 5, 7.5, 10]
  const step = steps.find((candidate) => normalized <= candidate) || 10
  return step * magnitude * 4
}

/** null 值会断开折线，准确表达某批次不存在所选分块，而不是伪造为 0。 */
export function linePath(values, xAt, yAt) {
  let path = ''
  let drawing = false
  values.forEach((value, index) => {
    if (value === null || value === undefined || !Number.isFinite(value)) {
      drawing = false
      return
    }
    path += `${drawing ? ' L' : 'M'} ${xAt(index).toFixed(2)} ${yAt(value).toFixed(2)}`
    drawing = true
  })
  return path
}
