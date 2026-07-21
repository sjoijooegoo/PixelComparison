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
      throw new Error(`${res.status} ${url}`)
    }
    return await res.json()
  })
}

async function send(method, url, body) {
  return fetchWithTimeout(url, {
    method,
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  }, API_TIMEOUT_MS, async (res) => {
    if (!res.ok) {
      const detail = (await res.json().catch(() => null))?.detail
      logger.error('接口失败', `${method} ${url}`, res.status, detail || '')
      const err = new Error(detail || `${res.status} ${url}`)
      err.status = res.status
      throw err
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
        const detail = (await res.json().catch(() => null))?.detail
        const ctx = [
          context.batchId != null ? `batch=${context.batchId}` : '',
          context.sceneName ? `scene=${context.sceneName}` : '',
          context.fileName ? `file=${context.fileName}` : '',
        ].filter(Boolean).join(' ')
        logger.error('上传失败', `POST ${url}`, res.status, ctx, detail || '')
        const err = new Error(detail || `${res.status} ${url}`)
        err.status = res.status
        throw err
      }
      return await res.json()
    },
  )
}

// 小尺寸预览用缩略图(/images/x -> /thumb/x);放大/对比/详情仍用原图
export const thumbUrl = (url) => (url ? url.replace('/images/', '/thumb/') : url)
export const isRequestCancelled = (error) => error?.code === 'ABORTED' || error?.cancelled === true

const post = (url, body) => send('POST', url, body)
const put = (url, body) => send('PUT', url, body)
const del = (url) => send('DELETE', url)

export const api = {
  meta: () => get('/api/meta'),
  batches: (params) => get('/api/batches', params),
  createBatch: (body) => post('/api/batches', body),
  deleteBatch: (id) => del(`/api/batches/${encodeURIComponent(id)}`),
  uploadScreenshot: (id, formData, context = {}) =>
    upload(`/api/batches/${id}/screenshots`, formData, { ...context, batchId: id }),
  autoCompare: (id) => post(`/api/batches/${id}/auto-compare`, {}),
  batchScreenshots: (id, options = {}) => get(`/api/batches/${id}/screenshots`, {}, options),
  sceneGrid: (sceneId, params) => get(`/api/scenes/${sceneId}/grid`, params),
  comparisons: (filters) => get('/api/comparisons', filters),
  createComparison: (body) => post('/api/comparisons', body),
  comparisonLookup: (batchId, refBatchId, options = {}) =>
    get('/api/comparisons/lookup', { batch_id: batchId, ref_batch_id: refBatchId }, options),
  comparisonTask: (taskId) => get(`/api/comparisons/tasks/${taskId}`),
  scenes: (comparisonId, params, options = {}) =>
    get(`/api/comparisons/${comparisonId}/scenes`, params, options),
  item: (id, options = {}) => get(`/api/items/${id}`, {}, options),
  baselines: () => get('/api/baselines'),
  settings: () => get('/api/settings'),
  saveSettings: (body) => put('/api/settings', body),
}
