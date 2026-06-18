async function get(url, params = {}) {
  const qs = new URLSearchParams(
    Object.entries(params).filter(([, v]) => v !== null && v !== undefined && v !== '')
  ).toString()
  const res = await fetch(qs ? `${url}?${qs}` : url)
  if (!res.ok) throw new Error(`${res.status} ${url}`)
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
    const err = new Error(detail || `${res.status} ${url}`)
    err.status = res.status
    throw err
  }
  return res.json()
}

// multipart 上传:不要手动设 Content-Type,让浏览器带 boundary
async function upload(url, formData) {
  const res = await fetch(url, { method: 'POST', body: formData })
  if (!res.ok) {
    const detail = (await res.json().catch(() => null))?.detail
    const err = new Error(detail || `${res.status} ${url}`)
    err.status = res.status
    throw err
  }
  return res.json()
}

const post = (url, body) => send('POST', url, body)
const put = (url, body) => send('PUT', url, body)

export const api = {
  meta: () => get('/api/meta'),
  batches: (params) => get('/api/batches', params),
  createBatch: (body) => post('/api/batches', body),
  uploadScreenshot: (id, formData) => upload(`/api/batches/${id}/screenshots`, formData),
  autoCompare: (id) => post(`/api/batches/${id}/auto-compare`, {}),
  batchScreenshots: (id) => get(`/api/batches/${id}/screenshots`),
  comparisons: (filters) => get('/api/comparisons', filters),
  createComparison: (body) => post('/api/comparisons', body),
  comparisonTask: (taskId) => get(`/api/comparisons/tasks/${taskId}`),
  scenes: (comparisonId, params) => get(`/api/comparisons/${comparisonId}/scenes`, params),
  item: (id) => get(`/api/items/${id}`),
  baselines: () => get('/api/baselines'),
  settings: () => get('/api/settings'),
  saveSettings: (body) => put('/api/settings', body),
}
