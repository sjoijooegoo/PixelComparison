/**
 * 为同一页面的多个请求通道提供“后发请求获胜”语义，并集中管理取消操作。
 * 页面只接触 begin/invalidate/abortAll，不需要维护序号和 AbortController。
 */
export function createLatestRequestChannels(channelNames) {
  const channels = new Map(
    channelNames.map((name) => [name, { sequence: 0, controller: null }]),
  )

  function channel(name) {
    const runtime = channels.get(name)
    if (!runtime) throw new Error(`未知请求通道：${name}`)
    return runtime
  }

  function invalidate(name) {
    const runtime = channel(name)
    runtime.controller?.abort()
    runtime.controller = null
    runtime.sequence += 1
  }

  return {
    begin(name) {
      const runtime = channel(name)
      runtime.controller?.abort()
      runtime.controller = new AbortController()
      const sequence = ++runtime.sequence
      return {
        signal: runtime.controller.signal,
        isLatest: () => runtime.sequence === sequence,
      }
    },

    invalidate,

    abortAll() {
      for (const name of channels.keys()) invalidate(name)
    },
  }
}
