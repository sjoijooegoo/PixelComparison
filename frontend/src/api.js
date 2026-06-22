import { logger } from './logger'

async function get(url, params = {}) {
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
  const res = await fetch(qs ? `${url}?${qs}` : url)
  if (!res.ok) {
    logger.error('接口失败', `GET ${url}`, res.status)
    throw new Error(`${res.status} ${url}`)
  }
  return res.json()
}

async function send(method, url, body) {
  const res = await fetch(url, {
    method,
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) {
    const detail = (await res.json().catch(() => null))?.detail
    logger.error('接口失败', `${method} ${url}`, res.status, detail || '')
    const err = new Error(detail || `${res.status} ${url}`)
    err.status = res.status
    throw err
  }
  return res.json()
}

// multipart 上传:不要手动设 Content-Type,让浏览器带 boundary
async function upload(url, formData, context = {}) {
  const res = await fetch(url, { method: 'POST', body: formData })
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
  return res.json()
}

// 小尺寸预览用缩略图(/images/x -> /thumb/x);放大/对比/详情仍用原图
export const thumbUrl = (url) => (url ? url.replace('/images/', '/thumb/') : url)

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
  batchScreenshots: (id) => get(`/api/batches/${id}/screenshots`),
  sceneGrid: (sceneId, params) => get(`/api/scenes/${sceneId}/grid`, params),
  comparisons: (filters) => get('/api/comparisons', filters),
  createComparison: (body) => post('/api/comparisons', body),
  comparisonLookup: (batchId, refBatchId) =>
    get('/api/comparisons/lookup', { batch_id: batchId, ref_batch_id: refBatchId }),
  comparisonTask: (taskId) => get(`/api/comparisons/tasks/${taskId}`),
  scenes: (comparisonId, params) => get(`/api/comparisons/${comparisonId}/scenes`, params),
  item: (id) => get(`/api/items/${id}`),
  baselines: () => get('/api/baselines'),
  settings: () => get('/api/settings'),
  saveSettings: (body) => put('/api/settings', body),
}
