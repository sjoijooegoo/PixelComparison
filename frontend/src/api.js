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
    throw new Error(detail || `${res.status} ${url}`)
  }
  return res.json()
}

const post = (url, body) => send('POST', url, body)
const put = (url, body) => send('PUT', url, body)

export const api = {
  meta: () => get('/api/meta'),
  batches: (params) => get('/api/batches', params),
  comparisons: (filters) => get('/api/comparisons', filters),
  createComparison: (body) => post('/api/comparisons', body),
  scenes: (comparisonId, params) => get(`/api/comparisons/${comparisonId}/scenes`, params),
  item: (id) => get(`/api/items/${id}`),
  baselines: () => get('/api/baselines'),
  settings: () => get('/api/settings'),
  saveSettings: (body) => put('/api/settings', body),
}
