const MIB = 1024 * 1024

export const MAP_BUILD_SERIES = [
  { key: 'all_mips_bytes', label: '总 Mip', color: '#e8952d' },
  { key: 'cook_estimate_bytes', label: 'Cook 估算', color: '#91a4bb' },
  { key: 'lightmap_all_mips_bytes', label: '光照贴图纹理', color: '#4b91f1' },
  { key: 'shadowmap_all_mips_bytes', label: '阴影贴图纹理', color: '#62aaa6' },
  { key: 'hue_all_mips_bytes', label: '色相纹理', color: '#a77ae6' },
]

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

/** 字节指标才参与排行；纹理数等不同单位由界面单独展示。 */
export function rankMetricDetails(metrics = {}) {
  return MAP_BUILD_DETAIL_METRICS
    .map((metric, order) => ({
      ...metric,
      order,
      value: Number(metrics?.[metric.key] || 0),
    }))
    .sort((left, right) => right.value - left.value || left.order - right.order)
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
  { at: 0, color: '#122433' },
  { at: 0.018071, color: '#122433' },
  { at: 0.0475, color: '#112332' },
  { at: 0.051571, color: '#162838' },
  { at: 0.071, color: '#1d3040' },
  { at: 0.154286, color: '#263947' },
  { at: 0.249286, color: '#30424e' },
  { at: 0.328571, color: '#5c594c' },
  { at: 0.485714, color: '#6a5e47' },
  { at: 0.592857, color: '#976d3d' },
  { at: 0.682143, color: '#b4672e' },
  { at: 0.898571, color: '#cd4818' },
  { at: 1, color: '#ce4a19' },
]

/**
 * 色标取自最终预览中避开文字、阴影和边框后的单元格底色中位数。
 * 使用全局 value / maximum 线性插值，保证不同分块共享同一统计口径。
 */
export function atlasColor(value, maximum) {
  const max = Number(maximum)
  const numericValue = Number(value)
  if (!Number.isFinite(max) || max <= 0 || value === null || value === undefined
    || !Number.isFinite(numericValue)) {
    return 'rgb(18, 36, 51)'
  }
  const ratio = Math.max(0, Math.min(1, Math.max(0, numericValue) / max))
  const upperIndex = ATLAS_COLOR_STOPS.findIndex((stop) => ratio <= stop.at)
  if (upperIndex <= 0) return 'rgb(18, 36, 51)'
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
