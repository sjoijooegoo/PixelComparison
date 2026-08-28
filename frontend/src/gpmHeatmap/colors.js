export const HEAT_COLORS = ['#52e817', '#b7f400', '#ffb20a', '#ff4a0a', '#ff1111']
export const HEAT_LABELS = ['优秀', '良好', '可接受', '关注', '超标']
export const LINEAR_HEAT_GRADIENT = 'linear-gradient(90deg, #52e817, #b7f400, #ffb20a, #ff4a0a, #ff1111)'

export function metricRange(points, metricKey) {
  let minimum = Infinity
  let maximum = -Infinity
  for (const point of points || []) {
    const raw = point?.heat_map_data?.[metricKey]
    if (raw === null || raw === undefined || raw === '') continue
    const value = Number(raw)
    if (!Number.isFinite(value)) continue
    minimum = Math.min(minimum, value)
    maximum = Math.max(maximum, value)
  }
  return Number.isFinite(minimum) ? [minimum, maximum] : [0, 0]
}

export function linearHeatColor(value, range) {
  const number = Number(value)
  if (!Number.isFinite(number)) return '#6b7280'
  const [minimum, maximum] = range
  const span = maximum - minimum
  const ratio = span > 0 ? Math.min(1, Math.max(0, (number - minimum) / span)) : 0
  const hue = Number((120 * (1 - ratio)).toFixed(1))
  return `hsl(${hue} 78% 48%)`
}

export function heatColor(
  value,
  thresholds,
  direction = 'lower_is_better',
  colors = HEAT_COLORS,
  boundaryOwners = [],
) {
  const number = Number(value)
  if (!Number.isFinite(number)) return '#6b7280'
  const bandCount = thresholds.length + 1
  let band = thresholds.findIndex((threshold, index) => (
    number < Number(threshold)
      || (number === Number(threshold) && boundaryOwners[index] === 'lower')
  ))
  if (band < 0) band = bandCount - 1
  if (direction === 'higher_is_better') band = bandCount - 1 - band
  return colors[band] || HEAT_COLORS[Math.min(band, HEAT_COLORS.length - 1)]
}

export function resolvedHeatColor(value, scale, fallbackRange = [0, 0]) {
  if (scale?.mode === 'configured') {
    return heatColor(
      value,
      scale.thresholds || [],
      scale.direction,
      scale.palette?.colors || HEAT_COLORS,
      scale.boundary_owners || [],
    )
  }
  return linearHeatColor(value, scale?.range || fallbackRange)
}

export function configuredBands(scale) {
  if (scale?.mode !== 'configured') return []
  const thresholds = scale.thresholds.map(Number)
  const colors = scale.palette?.colors || HEAT_COLORS
  const labels = scale.palette?.labels || HEAT_LABELS
  const boundaryOwners = scale.boundary_owners || []
  if (colors.length < 2 || thresholds.length !== colors.length - 1) return []
  return colors.map((_, index) => {
    const paletteIndex = scale.direction === 'higher_is_better'
      ? colors.length - 1 - index
      : index
    return {
    color: colors[paletteIndex],
    label: labels[paletteIndex] || `等级 ${paletteIndex + 1}`,
    minimum: index === 0 ? null : thresholds[index - 1],
    maximum: index === colors.length - 1 ? null : thresholds[index],
    minimumInclusive: index > 0 && boundaryOwners[index - 1] !== 'lower',
    maximumInclusive: index < colors.length - 1 && boundaryOwners[index] === 'lower',
  }
  })
}

export function formatMetricValue(value) {
  const number = Number(value)
  if (!Number.isFinite(number)) return '—'
  return new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 2 }).format(number)
}
