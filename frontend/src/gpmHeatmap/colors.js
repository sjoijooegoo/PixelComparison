import { compileScaleSegments } from './scaleExpressions'

export const HEAT_COLORS = ['#52e817', '#b7f400', '#ffb20a', '#ff4a0a', '#ff1111']
export const HEAT_LABELS = ['优秀', '良好', '可接受', '关注', '超标']
export const LINEAR_HEAT_GRADIENT = 'linear-gradient(90deg, #52e817, #b7f400, #ffb20a, #ff4a0a, #ff1111)'
const COMPILED_BANDS = new WeakMap()

function metricNumber(value) {
  if (value === null || value === undefined || typeof value === 'boolean') return null
  if (typeof value === 'string' && !value.trim()) return null
  const number = Number(value)
  return Number.isFinite(number) ? number : null
}

export function metricRange(points, metricKey) {
  let minimum = Infinity
  let maximum = -Infinity
  for (const point of points || []) {
    const raw = point?.heat_map_data?.[metricKey]
    const value = metricNumber(raw)
    if (value === null) continue
    minimum = Math.min(minimum, value)
    maximum = Math.max(maximum, value)
  }
  return Number.isFinite(minimum) ? [minimum, maximum] : [0, 0]
}

export function linearHeatColor(value, range) {
  const number = metricNumber(value)
  if (number === null) return '#6b7280'
  const [minimum, maximum] = range
  const span = maximum - minimum
  const ratio = span > 0 ? Math.min(1, Math.max(0, (number - minimum) / span)) : 0
  const hue = Number((120 * (1 - ratio)).toFixed(1))
  return `hsl(${hue} 78% 48%)`
}

function compiledBands(scale) {
  const segments = scale?.mode === 'configured' ? scale.segments : null
  if (!Array.isArray(segments)) return []
  const cached = COMPILED_BANDS.get(segments)
  if (cached) return cached
  const bands = compileScaleSegments(segments).bands
  COMPILED_BANDS.set(segments, bands)
  return bands
}

function bandContains(band, number) {
  return (band.minimum == null
    || number > band.minimum
    || (number === band.minimum && band.minimumInclusive))
    && (band.maximum == null
      || number < band.maximum
      || (number === band.maximum && band.maximumInclusive))
}

export function configuredBandIndex(value, scale) {
  const number = metricNumber(value)
  if (number === null) return -1
  try {
    return compiledBands(scale).findIndex((band) => bandContains(band, number))
  } catch {
    return -1
  }
}

export function resolvedHeatColor(value, scale, fallbackRange = [0, 0]) {
  if (scale?.mode === 'configured') {
    const number = metricNumber(value)
    if (number === null) return '#6b7280'
    try {
      return compiledBands(scale).find((band) => bandContains(band, number))?.color || '#6b7280'
    } catch {
      return '#6b7280'
    }
  }
  return linearHeatColor(value, scale?.range || fallbackRange)
}

export function configuredBands(scale) {
  try {
    const labels = scale.palette?.labels || HEAT_LABELS
    return compiledBands(scale).map((band, index) => ({
      ...band,
      label: labels[index] || `等级 ${index + 1}`,
    }))
  } catch {
    return []
  }
}

export function formatMetricValue(value) {
  const number = Number(value)
  if (!Number.isFinite(number)) return '—'
  return new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 2 }).format(number)
}

export function formatCoordinateValue(value) {
  const number = Number(value)
  if (!Number.isFinite(number)) return value ?? '—'
  return new Intl.NumberFormat('zh-CN', {
    maximumFractionDigits: 2,
    useGrouping: false,
  }).format(number)
}

export function formatConfiguredBandRange(band, domainMinimum = 0) {
  if (!band) return '—'
  const formatBoundary = (value) => {
    const number = Number(value)
    if (!Number.isFinite(number)) return '—'
    return new Intl.NumberFormat('zh-CN', {
      maximumFractionDigits: 2,
      useGrouping: false,
    }).format(number)
  }
  const lowerValue = band.minimum == null ? domainMinimum : band.minimum
  const lowerBracket = band.minimum == null || band.minimumInclusive ? '[' : '('
  const upperValue = band.maximum == null ? '+∞' : formatBoundary(band.maximum)
  const upperBracket = band.maximum == null || !band.maximumInclusive ? ')' : ']'
  return `${lowerBracket}${formatBoundary(lowerValue)},${upperValue}${upperBracket}`
}
