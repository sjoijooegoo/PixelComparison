export const HEAT_COLORS = ['#2f80ed', '#b7babd', '#f2b315', '#fa541c']

export function metricThresholds(points, metricKey, configured) {
  if (Array.isArray(configured) && configured.length === 3
    && configured.every((value) => Number.isFinite(Number(value)))) {
    return configured.map(Number)
  }
  const values = (points || [])
    .map((point) => Number(point?.heat_map_data?.[metricKey]))
    .filter(Number.isFinite)
    .sort((a, b) => a - b)
  if (!values.length) return [0, 0, 0]
  const at = (ratio) => values[Math.min(values.length - 1, Math.floor((values.length - 1) * ratio))]
  return [at(0.35), at(0.65), at(0.85)]
}

export function heatColor(value, thresholds) {
  const number = Number(value)
  if (!Number.isFinite(number)) return '#6b7280'
  if (number < thresholds[0]) return HEAT_COLORS[0]
  if (number < thresholds[1]) return HEAT_COLORS[1]
  if (number < thresholds[2]) return HEAT_COLORS[2]
  return HEAT_COLORS[3]
}

export function formatMetricValue(value) {
  const number = Number(value)
  if (!Number.isFinite(number)) return '—'
  return new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 2 }).format(number)
}
