import { afterEach, describe, expect, it, vi } from 'vitest'

import { API_TIMEOUT_MS, api, thumbUrl } from './api'

afterEach(() => {
  vi.unstubAllGlobals()
  vi.useRealTimers()
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

    expect(fetchMock).toHaveBeenCalledWith('/api/settings', expect.objectContaining({
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(patch),
      signal: expect.any(AbortSignal),
    }))
  })

  it('编码烘培数据场景路径、筛选参数和上报格式', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ points: [] }))
    vi.stubGlobal('fetch', fetchMock)

    await api.mapBuildTrend('Scene / 测试', {
      platform: 'Windows',
      shading_quality: 5,
      block_index: 3,
      sub_block_index: 1,
      days: 14,
    })
    const trendUrl = new URL(fetchMock.mock.calls[0][0], 'http://pixelcomparison.local')
    expect(trendUrl.pathname).toBe('/api/map-build/scenes/Scene%20%2F%20%E6%B5%8B%E8%AF%95/trend')
    expect(trendUrl.searchParams.get('block_index')).toBe('3')
    expect(trendUrl.searchParams.get('sub_block_index')).toBe('1')
    expect(trendUrl.searchParams.get('days')).toBe('14')

    await api.uploadMapBuildData(
      'batch 7', { worldAggregate: {} }, 'map-build-data/v2', 'engine-ue5',
    )
    expect(fetchMock.mock.calls[1][0]).toBe(
      '/api/batches/batch%207/map-build-data?format=map-build-data%2Fv2&branch_tag=engine-ue5',
    )
    expect(fetchMock.mock.calls[1][1]).toEqual(expect.objectContaining({
      method: 'POST',
      body: JSON.stringify({ worldAggregate: {} }),
    }))
  })

  it('接口超过统一时限后中止请求并返回可重试的中文错误', async () => {
    vi.useFakeTimers()
    const fetchMock = vi.fn((_url, options) => new Promise((_resolve, reject) => {
      options.signal.addEventListener('abort', () => {
        reject(Object.assign(new Error('aborted'), { name: 'AbortError' }))
      })
    }))
    vi.stubGlobal('fetch', fetchMock)

    const pending = api.meta().catch((error) => error)
    await vi.advanceTimersByTimeAsync(API_TIMEOUT_MS)

    const error = await pending
    expect(error).toMatchObject({ code: 'TIMEOUT', retryable: true })
    expect(error.message).toContain('请求超时')
  })

  it('收到响应头后正文读取卡住仍受统一超时控制', async () => {
    vi.useFakeTimers()
    const fetchMock = vi.fn((_url, options) => Promise.resolve({
      ok: true,
      json: () => new Promise((_resolve, reject) => {
        options.signal.addEventListener('abort', () => {
          reject(Object.assign(new Error('body aborted'), { name: 'AbortError' }))
        })
      }),
    }))
    vi.stubGlobal('fetch', fetchMock)

    const pending = api.meta().catch((error) => error)
    await vi.advanceTimersByTimeAsync(API_TIMEOUT_MS)

    await expect(pending).resolves.toMatchObject({ code: 'TIMEOUT', retryable: true })
  })

  it('调用方取消请求时返回取消标记而不是超时错误', async () => {
    const fetchMock = vi.fn((_url, options) => new Promise((_resolve, reject) => {
      options.signal.addEventListener('abort', () => {
        reject(Object.assign(new Error('aborted'), { name: 'AbortError' }))
      })
    }))
    vi.stubGlobal('fetch', fetchMock)
    const controller = new AbortController()

    const pending = api.item(7, { signal: controller.signal }).catch((error) => error)
    controller.abort()

    await expect(pending).resolves.toMatchObject({ code: 'ABORTED', cancelled: true })
  })
})
