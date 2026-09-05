import { defaultGpmCapturedRange, gpmBatchLocation } from './gpmBatchRoute'

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

function heatmapReturnTo(route, frame, state) {
  // 帧已切换而详情/趋势尚未完成时，地址栏可能仍是上一批次。
  const target = new URL(route.fullPath || WORKSPACE_PATHS.gpm, 'http://localhost')
  if (frame.map?.map_name) target.pathname = `${WORKSPACE_PATHS.gpm}/${encodeURIComponent(frame.map.map_name)}`
  const batch = frame.batch
  const values = {
    branch_tag: batch.branch_tag, platform: batch.platform, quality: batch.shading_quality, batch: batch.batch_id,
    point: state?.point, metric: state?.metric, trend_mode: state?.trendMode, days: state?.days,
  }
  for (const [key, value] of Object.entries(values)) {
    if (value === undefined) continue
    if (value === null || value === '') target.searchParams.delete(key)
    else target.searchParams.set(key, String(value))
  }
  return `${target.pathname}${target.search}${target.hash}`
}

export function batchManagementLocation(route, gpmFrame = null, gpmState = null) {
  const context = workspaceContext(route)
  if (context.batchDomain === 'gpm' && gpmFrame?.batch?.batch_id) {
    const batch = gpmFrame.batch
    const range = defaultGpmCapturedRange()
    const capturedDate = String(batch.captured_at || '').slice(0, 10)
    const outsideRange = capturedDate && (capturedDate < range.capturedFrom || capturedDate > range.capturedTo)
    return gpmBatchLocation({
      returnTo: heatmapReturnTo(route, gpmFrame, gpmState),
      branchTag: batch.branch_tag,
      platform: batch.platform,
      mapName: gpmFrame.map?.map_name,
      shadingQuality: batch.shading_quality,
      focusBatchId: batch.batch_id,
      rangeMode: outsideRange ? 'fixed' : 'rolling',
      capturedFrom: outsideRange && capturedDate < range.capturedFrom ? capturedDate : range.capturedFrom,
      capturedTo: outsideRange && capturedDate > range.capturedTo ? capturedDate : range.capturedTo,
    })
  }
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
