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

export function parseScreenshotRoute(route) {
  return {
    branchTag: firstValue(route.query.branch_tag) || 'main',
    sceneId: firstValue(route.params.sceneId) || '',
    baselineId: firstValue(route.query.baseline) || '',
    baselineQuality: firstValue(route.query.baseline_quality),
    currentId: firstValue(route.query.current) || '',
    currentQuality: firstValue(route.query.current_quality),
    shadingQuality: firstValue(route.query.quality),
    dateMode: firstValue(route.query.date_mode),
    rangeMode: firstValue(route.query.range_mode),
    createdFrom: firstValue(route.query.from),
    createdTo: firstValue(route.query.to),
    createdDates: dateValues(route.query.dates),
  }
}

export function screenshotStateFromFilters(filters, roles = {}) {
  return {
    branchTag: filters.branch_tag || 'main',
    sceneId: filters.scene_id || '',
    baselineId: roles.baselineId || '',
    baselineQuality: roles.baselineQuality ?? '',
    currentId: roles.currentId || '',
    currentQuality: roles.currentQuality ?? '',
    shadingQuality: filters.shading_quality == null ? '' : filters.shading_quality,
    dateMode: filters.dateMode,
    rangeMode: filters.rangeMode,
    createdFrom: filters.created_from,
    createdTo: filters.created_to,
    createdDates: [...(filters.created_dates || [])],
  }
}

export function screenshotRouteKey(state) {
  return JSON.stringify({
    branchTag: state.branchTag || 'main',
    sceneId: state.sceneId || '',
    baselineId: state.baselineId || '',
    baselineQuality: state.baselineQuality ?? '',
    currentId: state.currentId || '',
    currentQuality: state.currentQuality ?? '',
    shadingQuality: state.shadingQuality,
    dateMode: state.dateMode,
    rangeMode: state.rangeMode,
    createdFrom: state.createdFrom,
    createdTo: state.createdTo,
    createdDates: [...(state.createdDates || [])],
  })
}

export function screenshotLocation(state) {
  const query = {
    branch_tag: state.branchTag || 'main',
  }
  if (state.shadingQuality !== undefined) {
    query.quality = state.shadingQuality === '' ? 'all' : String(state.shadingQuality)
  }
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
  if (state.baselineId) {
    query.baseline = String(state.baselineId)
    if (state.baselineQuality !== '' && state.baselineQuality != null) {
      query.baseline_quality = String(state.baselineQuality)
    }
  }
  if (state.currentId) {
    query.current = String(state.currentId)
    if (state.currentQuality !== '' && state.currentQuality != null) {
      query.current_quality = String(state.currentQuality)
    }
  }
  return {
    path: state.sceneId ? `/screenshot/${encodeURIComponent(state.sceneId)}` : '/screenshot',
    query,
  }
}
