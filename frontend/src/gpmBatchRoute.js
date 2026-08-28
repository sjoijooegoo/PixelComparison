function firstValue(value) {
  return Array.isArray(value) ? value[0] : value
}

function ymd(date) {
  const month = String(date.getMonth() + 1).padStart(2, '0')
  const day = String(date.getDate()).padStart(2, '0')
  return `${date.getFullYear()}-${month}-${day}`
}

export function defaultGpmCapturedRange(days = 30, now = new Date()) {
  const from = new Date(now)
  from.setDate(from.getDate() - Math.max(1, days) + 1)
  return { capturedFrom: ymd(from), capturedTo: ymd(now) }
}

function validDate(value) {
  const normalized = String(value || '')
  return /^\d{4}-\d{2}-\d{2}$/.test(normalized) ? normalized : ''
}

export function parseGpmBatchRoute(route) {
  const defaults = defaultGpmCapturedRange()
  const quality = Number(firstValue(route.query.quality))
  const page = Number(firstValue(route.query.page))
  return {
    returnTo: firstValue(route.query.return_to) || '',
    branchTag: firstValue(route.query.branch_tag) || 'main',
    platform: firstValue(route.query.platform) || '',
    sceneId: firstValue(route.query.scene_id) || '',
    shadingQuality: Number.isInteger(quality) && quality >= 0 && quality <= 5 ? quality : '',
    capturedFrom: validDate(firstValue(route.query.from)) || defaults.capturedFrom,
    capturedTo: validDate(firstValue(route.query.to)) || defaults.capturedTo,
    page: Number.isInteger(page) && page > 0 ? page : 1,
  }
}

export function gpmBatchRouteKey(state) {
  return JSON.stringify({
    returnTo: state.returnTo || '', branchTag: state.branchTag || 'main',
    platform: state.platform || '', sceneId: state.sceneId || '',
    shadingQuality: state.shadingQuality === '' ? '' : Number(state.shadingQuality),
    capturedFrom: state.capturedFrom || '', capturedTo: state.capturedTo || '',
    page: Number(state.page) || 1,
  })
}

export function gpmBatchLocation(state) {
  const query = { branch_tag: state.branchTag || 'main' }
  if (state.returnTo) query.return_to = state.returnTo
  if (state.platform) query.platform = state.platform
  if (state.sceneId) query.scene_id = state.sceneId
  if (state.shadingQuality !== '' && state.shadingQuality != null) {
    query.quality = String(state.shadingQuality)
  }
  if (state.capturedFrom) query.from = state.capturedFrom
  if (state.capturedTo) query.to = state.capturedTo
  if (Number(state.page) > 1) query.page = String(state.page)
  return { path: '/batch-management/gpm', query }
}
