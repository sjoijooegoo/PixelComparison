export const PAGE_SIZE = 10
export const MAX_DATE_RANGE_DAYS = 14
export const DATE_RANGE_MODE_ROLLING = 'rolling'
export const DATE_RANGE_MODE_FIXED = 'fixed'

function ymd(date) {
  const month = String(date.getMonth() + 1).padStart(2, '0')
  const day = String(date.getDate()).padStart(2, '0')
  return `${date.getFullYear()}-${month}-${day}`
}

export function normalizeDateRangeDays(days = 7) {
  const value = Number(days)
  if (!Number.isFinite(value)) return 7
  return Math.max(1, Math.min(MAX_DATE_RANGE_DAYS, Math.trunc(value)))
}

export function inclusiveDateRangeDays(from, to) {
  const parse = (value) => {
    const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value || '')
    if (!match) return null
    const [, year, month, day] = match.map(Number)
    const time = Date.UTC(year, month - 1, day)
    const date = new Date(time)
    if (date.getUTCFullYear() !== year
        || date.getUTCMonth() !== month - 1
        || date.getUTCDate() !== day) return null
    return time
  }
  const start = parse(from)
  const end = parse(to)
  if (start === null || end === null || end < start) return null
  return Math.floor((end - start) / 86_400_000) + 1
}

export function isDateRangeAllowed(from, to) {
  const days = inclusiveDateRangeDays(from, to)
  return days !== null && days <= MAX_DATE_RANGE_DAYS
}

export function defaultDateRange(days = 7) {
  const count = normalizeDateRangeDays(days)
  const today = new Date()
  const from = new Date(today)
  from.setDate(today.getDate() - (count - 1))
  return { created_from: ymd(from), created_to: ymd(today) }
}

export function normalizeDateRangeMode(value, from, to, defaultDays = 7) {
  if (value === DATE_RANGE_MODE_ROLLING || value === DATE_RANGE_MODE_FIXED) return value
  // 旧版默认范围只在 URL 中保存了 from/to。无法与同长度的手动范围完全区分，
  // 因此按项目默认天数迁移为滚动范围；新版手动选择会显式写入 fixed。
  return inclusiveDateRangeDays(from, to) === normalizeDateRangeDays(defaultDays)
    ? DATE_RANGE_MODE_ROLLING
    : DATE_RANGE_MODE_FIXED
}

export function refreshRollingDateRange(filters, defaultDays = 7) {
  if (filters?.dateMode !== 'range'
      || filters?.rangeMode !== DATE_RANGE_MODE_ROLLING) return false
  const next = defaultDateRange(defaultDays)
  const changed = filters.created_from !== next.created_from
    || filters.created_to !== next.created_to
  filters.created_from = next.created_from
  filters.created_to = next.created_to
  return changed
}

export const SHADING_QUALITY_OPTIONS = [
  { value: 5, label: '电影' },
  { value: 4, label: '极致' },
  { value: 3, label: '精美' },
  { value: 2, label: '均衡' },
  { value: 1, label: '流畅' },
  { value: 0, label: '节能' },
]

const SHADING_QUALITY_VALUES = new Set(
  SHADING_QUALITY_OPTIONS.map((option) => option.value),
)

export function cloneRequestParams(params) {
  return Object.fromEntries(
    Object.entries(params).map(([key, value]) => [
      key,
      Array.isArray(value) ? [...value] : value,
    ]),
  )
}

export function normalizeShadingQuality(value, fallback = '') {
  if (value === undefined || value === null) return fallback
  if (value === '' || String(value).trim().toLowerCase() === 'all') return ''
  const quality = Number(value)
  return Number.isInteger(quality) && SHADING_QUALITY_VALUES.has(quality) ? quality : fallback
}

export function normalizeSelectedDates(value) {
  const values = Array.isArray(value) ? value : [value]
  return [...new Set(
    values
      .flatMap((item) => String(item ?? '').split(','))
      .map((item) => item.trim())
      .filter((item) => inclusiveDateRangeDays(item, item) === 1),
  )].sort()
}

export function visibleQualityOptions(settings) {
  const configured = new Set(settings?.filter_shading_qualities ?? [5, 4, 3, 2, 1, 0])
  const options = SHADING_QUALITY_OPTIONS.filter((option) => configured.has(option.value))
  return options.length ? options : SHADING_QUALITY_OPTIONS
}

export function p4Label(value) {
  return (value === null || value === undefined || value === '') ? '——' : `P4 ${value}`
}

export const STATUS_META = {
  fail: { label: '失败', color: 'red' },
  warn: { label: '警告', color: 'orange' },
  pass: { label: '通过', color: 'green' },
  added: { label: '新增', color: 'arcoblue' },
  missing: { label: '缺失', color: 'gray' },
}
