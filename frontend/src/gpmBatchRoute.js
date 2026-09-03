import { calendarDate, inclusiveDateRangeDays } from './dateRange'

function firstValue(value) {
  return Array.isArray(value) ? value[0] : value
}

export function defaultGpmCapturedRange(days = 30, now = new Date()) {
  const from = new Date(now)
  from.setDate(from.getDate() - Math.max(1, days) + 1)
  return { capturedFrom: calendarDate(from), capturedTo: calendarDate(now) }
}

function validDate(value) {
  const normalized = String(value || '')
  return inclusiveDateRangeDays(normalized, normalized) === 1 ? normalized : ''
}

export function parseGpmBatchRoute(route) {
  const defaults = defaultGpmCapturedRange()
  const requestedFrom = validDate(firstValue(route.query.from))
  const requestedTo = validDate(firstValue(route.query.to))
  const requestedRangeMode = firstValue(route.query.range_mode)
  const rangeMode = requestedRangeMode === 'rolling' || requestedRangeMode === 'fixed'
    ? requestedRangeMode
    : !requestedFrom && !requestedTo
      ? 'rolling'
      : inclusiveDateRangeDays(requestedFrom, requestedTo) === 30 ? 'rolling' : 'fixed'
  const quality = Number(firstValue(route.query.quality))
  const page = Number(firstValue(route.query.page))
  return {
    returnTo: firstValue(route.query.return_to) || '',
    branchTag: firstValue(route.query.branch_tag) || 'main',
    platform: firstValue(route.query.platform) || '',
    mapName: firstValue(route.query.map_name) || '',
    shadingQuality: Number.isInteger(quality) && quality >= 0 && quality <= 5 ? quality : '',
    rangeMode,
    capturedFrom: rangeMode === 'rolling' ? defaults.capturedFrom : requestedFrom || defaults.capturedFrom,
    capturedTo: rangeMode === 'rolling' ? defaults.capturedTo : requestedTo || defaults.capturedTo,
    page: Number.isInteger(page) && page > 0 ? page : 1,
  }
}

export function gpmBatchRouteKey(state) {
  return JSON.stringify({
    returnTo: state.returnTo || '', branchTag: state.branchTag || 'main',
    platform: state.platform || '', mapName: state.mapName || '',
    shadingQuality: state.shadingQuality === '' ? '' : Number(state.shadingQuality),
    rangeMode: state.rangeMode === 'fixed' ? 'fixed' : 'rolling',
    capturedFrom: state.capturedFrom || '', capturedTo: state.capturedTo || '',
    page: Number(state.page) || 1,
  })
}

export function gpmBatchLocation(state) {
  const rangeMode = state.rangeMode === 'fixed' ? 'fixed' : 'rolling'
  const query = { branch_tag: state.branchTag || 'main', range_mode: rangeMode }
  if (state.returnTo) query.return_to = state.returnTo
  if (state.platform) query.platform = state.platform
  if (state.mapName) query.map_name = state.mapName
  if (state.shadingQuality !== '' && state.shadingQuality != null) {
    query.quality = String(state.shadingQuality)
  }
  if (rangeMode === 'fixed' && state.capturedFrom) query.from = state.capturedFrom
  if (rangeMode === 'fixed' && state.capturedTo) query.to = state.capturedTo
  if (Number(state.page) > 1) query.page = String(state.page)
  return { path: '/batch-management/gpm', query }
}
