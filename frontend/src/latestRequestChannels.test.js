import { describe, expect, it } from 'vitest'
import { createLatestRequestChannels } from './latestRequestChannels'

describe('createLatestRequestChannels', () => {
  it('同一通道后发请求获胜并取消前一个请求', () => {
    const channels = createLatestRequestChannels(['overview'])
    const first = channels.begin('overview')
    const second = channels.begin('overview')

    expect(first.signal.aborted).toBe(true)
    expect(first.isLatest()).toBe(false)
    expect(second.signal.aborted).toBe(false)
    expect(second.isLatest()).toBe(true)
  })

  it('可统一取消全部通道且拒绝拼错的通道名', () => {
    const channels = createLatestRequestChannels(['overview', 'trend'])
    const overview = channels.begin('overview')
    const trend = channels.begin('trend')

    channels.abortAll()

    expect(overview.signal.aborted).toBe(true)
    expect(trend.signal.aborted).toBe(true)
    expect(() => channels.begin('missing')).toThrow('未知请求通道')
  })
})
