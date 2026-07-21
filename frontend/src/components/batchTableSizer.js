export function measureBatchPageSize(wrap) {
  if (!wrap) return null
  if (!wrap.clientHeight) return null
  const thH = wrap.querySelector('.arco-table-th')?.getBoundingClientRect().height || 36
  const rowH = wrap.querySelector('tbody .arco-table-tr')?.getBoundingClientRect().height || 40
  return Math.max(3, Math.floor((wrap.clientHeight - thH) / rowH))
}

export function createBatchTableSizer(store, {
  createObserver = (callback) => new ResizeObserver(callback),
} = {}) {
  let observer = null
  let observedWrap = null

  function recalc() {
    const fit = measureBatchPageSize(observedWrap)
    if (fit == null || fit === store.batchPageSize) return false
    store.batchPageSize = fit
    store.batchPage = 1
    void store.loadBatches().catch(() => {})
    return true
  }

  function observe(wrap) {
    if (wrap === observedWrap) return false
    if (observedWrap && observer) observer.unobserve(observedWrap)
    observedWrap = wrap || null
    if (!observedWrap) return false

    if (!observer) observer = createObserver(recalc)
    observer.observe(observedWrap)
    recalc()
    return true
  }

  function disconnect() {
    if (observedWrap && observer) observer.unobserve(observedWrap)
    observedWrap = null
    observer?.disconnect()
    observer = null
  }

  return { observe, recalc, disconnect }
}
