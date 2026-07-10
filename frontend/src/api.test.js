import { afterEach, describe, expect, it, vi } from 'vitest'

import { api, thumbUrl } from './api'

afterEach(() => {
  vi.unstubAllGlobals()
})

function jsonResponse(body) {
  return {
    ok: true,
    json: vi.fn().mockResolvedValue(body),
  }
}

describe('thumbUrl', () => {
  it('只替换图片路由并保留缓存版本参数', () => {
    expect(thumbUrl('/images/batches/7/a.png?v=123')).toBe('/thumb/batches/7/a.png?v=123')
    expect(thumbUrl(null)).toBeNull()
  })
})

describe('api request encoding', () => {
  it('把数组筛选编码为重复查询参数并忽略空值', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ items: [], total: 0 }))
    vi.stubGlobal('fetch', fetchMock)

    await api.batches({
      created_dates: ['2026-07-01', '2026-07-03'],
      page: 2,
      q: '',
      platform: null,
    })

    const requestUrl = new URL(fetchMock.mock.calls[0][0], 'http://pixelcomparison.local')
    expect(requestUrl.pathname).toBe('/api/batches')
    expect(requestUrl.searchParams.getAll('created_dates')).toEqual(['2026-07-01', '2026-07-03'])
    expect(requestUrl.searchParams.get('page')).toBe('2')
    expect(requestUrl.searchParams.has('q')).toBe(false)
    expect(requestUrl.searchParams.has('platform')).toBe(false)
  })

  it('按 JSON 提交完整热力图设置', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ heatmap_method: 'legacy' }))
    vi.stubGlobal('fetch', fetchMock)
    const patch = { heatmap_method: 'legacy', heatmap_gamma: 1.8 }

    await api.saveSettings(patch)

    expect(fetchMock).toHaveBeenCalledWith('/api/settings', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(patch),
    })
  })
})
