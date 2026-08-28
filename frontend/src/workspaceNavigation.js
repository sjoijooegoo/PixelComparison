const WORKSPACE_PATHS = {
  screenshot: '/screenshot',
  mapBuild: '/map-build',
  gpm: '/gpm-heatmap',
}

function firstValue(value) {
  return Array.isArray(value) ? value[0] : value
}

export function safeReturnTo(value, fallback = '/screenshot') {
  const candidate = String(firstValue(value) || '').trim()
  if (!candidate.startsWith('/') || candidate.startsWith('//')) return fallback
  const isWorkspace = Object.values(WORKSPACE_PATHS).some(
    (prefix) => candidate === prefix || candidate.startsWith(`${prefix}/`) || candidate.startsWith(`${prefix}?`),
  )
  if (!isWorkspace) return fallback
  return candidate
}

export function workspaceFromPath(path) {
  const normalized = String(path || '')
  if (normalized.startsWith(WORKSPACE_PATHS.mapBuild)) return 'mapBuild'
  if (normalized.startsWith(WORKSPACE_PATHS.gpm)) return 'gpm'
  return 'screenshot'
}

export function workspaceContext(route) {
  const path = String(route?.path || '')
  const providedReturnTo = safeReturnTo(route?.query?.return_to, '')
  const isCaptureBatches = path.startsWith('/batch-management/capture')
  const isGpmBatches = path.startsWith('/batch-management/gpm')
  const isScreenshotSettings = path.startsWith('/settings/screenshot-comparison')
  const isGpmSettings = path.startsWith('/settings/gpm-heatmap')
  let workspace = workspaceFromPath(path)
  if (isGpmBatches || isGpmSettings) workspace = 'gpm'
  else if (isScreenshotSettings) workspace = 'screenshot'
  else if (isCaptureBatches) workspace = workspaceFromPath(providedReturnTo)
  const returnTo = providedReturnTo || WORKSPACE_PATHS[workspace]

  return {
    workspace,
    isManagement: isCaptureBatches || isGpmBatches,
    isSettings: isScreenshotSettings || isGpmSettings,
    isDataPage: Object.values(WORKSPACE_PATHS).some(
      (prefix) => path === prefix || path.startsWith(`${prefix}/`),
    ),
    batchDomain: workspace === 'gpm' ? 'gpm' : 'capture',
    returnTo,
  }
}

export function batchManagementLocation(route) {
  const context = workspaceContext(route)
  return {
    path: context.batchDomain === 'gpm'
      ? '/batch-management/gpm'
      : '/batch-management/capture',
    query: { return_to: route.fullPath || WORKSPACE_PATHS[context.workspace] },
  }
}

export function screenshotSettingsLocation(route) {
  return {
    path: '/settings/screenshot-comparison',
    query: { return_to: route.fullPath || WORKSPACE_PATHS.screenshot },
  }
}

export function gpmSettingsLocation(route) {
  return {
    path: '/settings/gpm-heatmap',
    query: { return_to: route.fullPath || WORKSPACE_PATHS.gpm },
  }
}

export const primaryWorkspaces = [
  { id: 'screenshot', path: WORKSPACE_PATHS.screenshot, label: '截图对比' },
  { id: 'mapBuild', path: WORKSPACE_PATHS.mapBuild, label: '烘培数据' },
  { id: 'gpm', path: WORKSPACE_PATHS.gpm, label: '热力图' },
]
