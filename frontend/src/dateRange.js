const DAY_MS = 86_400_000

export function calendarDate(date) {
  const month = String(date.getMonth() + 1).padStart(2, '0')
  const day = String(date.getDate()).padStart(2, '0')
  return `${date.getFullYear()}-${month}-${day}`
}

function dateStamp(value) {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value || '')
  if (!match) return null
  const year = Number(match[1])
  const month = Number(match[2])
  const day = Number(match[3])
  const stamp = Date.UTC(year, month - 1, day)
  const date = new Date(stamp)
  if (date.getUTCFullYear() !== year
      || date.getUTCMonth() !== month - 1
      || date.getUTCDate() !== day) return null
  return stamp
}

export function inclusiveDateRangeDays(from, to) {
  const start = dateStamp(from)
  const end = dateStamp(to)
  if (start === null || end === null || end < start) return null
  return Math.floor((end - start) / DAY_MS) + 1
}

export function rollingDateRange(days, now = new Date()) {
  const count = Math.max(1, Math.trunc(Number(days) || 1))
  const end = new Date(now.getFullYear(), now.getMonth(), now.getDate())
  const start = new Date(end)
  start.setDate(start.getDate() - count + 1)
  return [calendarDate(start), calendarDate(end)]
}
