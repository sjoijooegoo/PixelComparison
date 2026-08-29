function firstValue(value) {
  return Array.isArray(value) ? value[0] : value
}

function dateValues(value) {
  const values = Array.isArray(value) ? value : [value]
  return values
    .flatMap((item) => String(item ?? '').split(','))
    .map((item) => item.trim())
    .filter(Boolean)
}

export function parseBatchRoute(route) {
  return {
    returnTo: firstValue(route.query.return_to) || '',
    branchTag: firstValue(route.query.branch_tag) || 'main',
    sceneId: firstValue(route.query.scene_id) || '',
    dateMode: firstValue(route.query.date_mode),
    rangeMode: firstValue(route.query.range_mode),
    createdFrom: firstValue(route.query.from),
    createdTo: firstValue(route.query.to),
    createdDates: dateValues(route.query.dates),
    page: firstValue(route.query.page),
  }
}

export function batchStateFromFilters(filters, page = 1, returnTo = '') {
  return {
    returnTo,
    branchTag: filters.branch_tag || 'main',
    sceneId: filters.scene_id || '',
    dateMode: filters.dateMode,
    rangeMode: filters.rangeMode,
    createdFrom: filters.created_from,
    createdTo: filters.created_to,
    createdDates: [...(filters.created_dates || [])],
    page,
  }
}

export function batchRouteKey(state) {
  return JSON.stringify({
    returnTo: state.returnTo || '',
    branchTag: state.branchTag || 'main',
    sceneId: state.sceneId || '',
    dateMode: state.dateMode,
    rangeMode: state.rangeMode,
    createdFrom: state.createdFrom,
    createdTo: state.createdTo,
    createdDates: [...(state.createdDates || [])],
    page: state.page == null ? state.page : String(state.page),
  })
}

export function batchLocation(state) {
  const query = { branch_tag: state.branchTag || 'main' }
  if (state.returnTo) query.return_to = state.returnTo
  if (state.sceneId) query.scene_id = state.sceneId
  if (state.dateMode) {
    query.date_mode = state.dateMode
    if (state.dateMode === 'days') query.dates = (state.createdDates || []).join(',')
    else {
      const rangeMode = state.rangeMode
        || (state.createdFrom && state.createdTo ? 'fixed' : 'rolling')
      query.range_mode = rangeMode
      if (rangeMode === 'fixed') {
        query.from = state.createdFrom || ''
        query.to = state.createdTo || ''
      }
    }
  }
  const page = Number(state.page)
  if (Number.isInteger(page) && page > 1) query.page = String(page)
  return { path: '/batch-management/capture', query }
}
