import { logger } from './logger'

export const API_TIMEOUT_MS = 30_000
const UPLOAD_TIMEOUT_MS = 120_000

async function fetchWithTimeout(
  url,
  options = {},
  timeoutMs = API_TIMEOUT_MS,
  consume = (response) => response,
) {
  const { signal: callerSignal, ...fetchOptions } = options
  const controller = new AbortController()
  let timedOut = false
  const abortFromCaller = () => controller.abort(callerSignal?.reason)
  if (callerSignal?.aborted) abortFromCaller()
  else callerSignal?.addEventListener('abort', abortFromCaller, { once: true })
  const timer = setTimeout(() => {
    timedOut = true
    controller.abort()
  }, timeoutMs)
  try {
    const response = await fetch(url, { ...fetchOptions, signal: controller.signal })
    // 保持计时器和调用方 signal 有效，直到响应正文也读取完成。
    return await consume(response)
  } catch (error) {
    if (timedOut) {
      const timeout = new Error(`请求超时（${Math.round(timeoutMs / 1000)} 秒），请重试`)
      timeout.code = 'TIMEOUT'
      timeout.retryable = true
      throw timeout
    }
    if (controller.signal.aborted || error?.name === 'AbortError') {
      const cancelled = new Error('请求已取消')
      cancelled.code = 'ABORTED'
      cancelled.cancelled = true
      throw cancelled
    }
    throw error
  } finally {
    clearTimeout(timer)
    callerSignal?.removeEventListener('abort', abortFromCaller)
  }
}

async function responseError(res, fallback) {
  const payload = await res.json().catch(() => null)
  const nested = payload?.detail
  const message = payload?.message
    || (typeof nested === 'string' ? nested : nested?.message)
    || fallback
  const error = new Error(message)
  error.status = res.status
  error.code = payload?.code || nested?.code
  error.details = payload?.details || nested?.details
  return error
}

async function get(url, params = {}, options = {}) {
  const sp = new URLSearchParams()
  for (const [k, v] of Object.entries(params)) {
    if (v === null || v === undefined || v === '') continue
    if (Array.isArray(v)) {
      v.forEach((x) => { if (x !== null && x !== undefined && x !== '') sp.append(k, x) })
    } else {
      sp.append(k, v)
    }
  }
  const qs = sp.toString()
  return fetchWithTimeout(qs ? `${url}?${qs}` : url, options, API_TIMEOUT_MS, async (res) => {
    if (!res.ok) {
      logger.error('接口失败', `GET ${url}`, res.status)
      throw await responseError(res, `${res.status} ${url}`)
    }
    return await res.json()
  })
}

async function send(method, url, body, options = {}) {
  return fetchWithTimeout(url, {
    ...options,
    method,
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  }, API_TIMEOUT_MS, async (res) => {
    if (!res.ok) {
      const error = await responseError(res, `${res.status} ${url}`)
      logger.error('接口失败', `${method} ${url}`, res.status, error.message || '')
      throw error
    }
    return await res.json()
  })
}

// multipart 上传:不要手动设 Content-Type,让浏览器带 boundary
async function upload(url, formData, context = {}) {
  return fetchWithTimeout(
    url,
    { method: 'POST', body: formData },
    UPLOAD_TIMEOUT_MS,
    async (res) => {
      if (!res.ok) {
        const error = await responseError(res, `${res.status} ${url}`)
        const ctx = [
          context.batchId != null ? `batch=${context.batchId}` : '',
          context.sceneName ? `scene=${context.sceneName}` : '',
          context.fileName ? `file=${context.fileName}` : '',
        ].filter(Boolean).join(' ')
        logger.error('上传失败', `POST ${url}`, res.status, ctx, error.message || '')
        throw error
      }
      return await res.json()
    },
  )
}

// 小尺寸预览用缩略图(/images/x -> /thumb/x);放大/对比/详情仍用原图
export const thumbUrl = (url) => (url ? url.replace('/images/', '/thumb/') : url)
export const isRequestCancelled = (error) => error?.code === 'ABORTED' || error?.cancelled === true

const post = (url, body, options = {}) => send('POST', url, body, options)
const put = (url, body) => send('PUT', url, body)
const del = (url) => send('DELETE', url)

export const api = {
  meta: () => get('/api/meta'),
  sceneAvailability: (params, options = {}) => get('/api/scene-availability', params, options),
  batches: (params) => get('/api/batches', params),
  batch: (id, options = {}) => get(`/api/batches/${encodeURIComponent(id)}`, {}, options),
  createBatch: (body) => post('/api/batches', body),
  deleteBatch: (id) => del(`/api/batches/${encodeURIComponent(id)}`),
  uploadScreenshot: (id, formData, context = {}, branchTag = 'main') =>
    upload(
      `/api/batches/${encodeURIComponent(id)}/screenshots?branch_tag=${encodeURIComponent(branchTag)}`,
      formData,
      { ...context, batchId: id },
    ),
  uploadQualityScreenshot: (id, quality, formData, context = {}, branchTag = 'main') =>
    upload(
      `/api/batches/${encodeURIComponent(id)}/quality-runs/${encodeURIComponent(quality)}/screenshots?branch_tag=${encodeURIComponent(branchTag)}`,
      formData,
      { ...context, batchId: id },
    ),
  uploadMapBuildData: (id, body, format = 'map-build-data/v2', branchTag = 'main') =>
    post(
      `/api/batches/${encodeURIComponent(id)}/map-build-data?format=${encodeURIComponent(format)}&branch_tag=${encodeURIComponent(branchTag)}`,
      body,
    ),
  autoCompare: (id) => post(`/api/batches/${id}/auto-compare`, {}),
  batchScreenshots: (id, options = {}) => get(`/api/batches/${id}/screenshots`, {}, options),
  qualityRunScreenshots: (id, quality, options = {}) => get(
    `/api/batches/${encodeURIComponent(id)}/quality-runs/${encodeURIComponent(quality)}/screenshots`,
    {},
    options,
  ),
  sceneGrid: (sceneId, params, options = {}) => get(`/api/scenes/${sceneId}/grid`, params, options),
  createComparison: (body, options = {}) => post('/api/comparisons', body, options),
  comparisonLookup: (batchId, refBatchId, quality, options = {}) =>
    get('/api/comparisons/lookup', {
      batch_id: batchId,
      ref_batch_id: refBatchId,
      shading_quality: quality,
    }, options),
  comparisonTask: (taskId, options = {}) => get(`/api/comparisons/tasks/${taskId}`, {}, options),
  mapBuildMeta: (params = {}, options = {}) => get('/api/map-build/meta', params, options),
  mapBuildOverview: (sceneId, params = {}, options = {}) =>
    get(`/api/map-build/scenes/${encodeURIComponent(sceneId)}/overview`, params, options),
  mapBuildTrend: (sceneId, params = {}, options = {}) =>
    get(`/api/map-build/scenes/${encodeURIComponent(sceneId)}/trend`, params, options),
  gpmHeatmapMeta: (params = {}, options = {}) =>
    get('/api/gpm-heatmaps/meta', params, options),
  gpmHeatmapFrame: (sceneId, params = {}, options = {}) =>
    get(`/api/gpm-heatmaps/scenes/${encodeURIComponent(sceneId)}/frame`, params, options),
  gpmHeatmapSceneTrends: (sceneId, params = {}, options = {}) =>
    get(`/api/gpm-heatmaps/scenes/${encodeURIComponent(sceneId)}/trends`, params, options),
  gpmHeatmapPoint: (pointId, options = {}) =>
    get(`/api/gpm-heatmaps/points/${encodeURIComponent(pointId)}`, {}, options),
  gpmHeatmapTrends: (pointId, params = {}, options = {}) =>
    get(`/api/gpm-heatmaps/points/${encodeURIComponent(pointId)}/trends`, params, options),
  deleteGpmHeatmapUpload: (batchId, branchTag = 'main') =>
    del(`/api/gpm-heatmaps/uploads/${encodeURIComponent(batchId)}?branch_tag=${encodeURIComponent(branchTag)}`),
  baselines: (filters = {}) => get('/api/baselines', filters),
  settings: () => get('/api/settings'),
  saveSettings: (body) => put('/api/settings', body),
}
