import { describe, expect, it, vi } from 'vitest'

import { createBatchTableSizer, measureBatchPageSize } from './batchTableSizer'

function tableWrap({ height = 796, headerHeight = 36, rowHeight = 40 } = {}) {
  return {
    clientHeight: height,
    querySelector(selector) {
      if (selector === '.arco-table-th') {
        return { getBoundingClientRect: () => ({ height: headerHeight }) }
      }
      if (selector === 'tbody .arco-table-tr') {
        return { getBoundingClientRect: () => ({ height: rowHeight }) }
      }
      return null
    },
  }
}

describe('batch table page sizing', () => {
  it('measures the number of rows that fit in the visible table area', () => {
    expect(measureBatchPageSize(tableWrap())).toBe(19)
    expect(measureBatchPageSize(tableWrap({ height: 120 }))).toBe(3)
    expect(measureBatchPageSize(tableWrap({ height: 0 }))).toBeNull()
    expect(measureBatchPageSize(null)).toBeNull()
  })

  it('observes a table that appears after mount and immediately reloads with its measured size', () => {
    const store = {
      batchPageSize: 10,
      batchPage: 7,
      loadBatches: vi.fn().mockResolvedValue(null),
    }
    let resizeCallback
    const observer = {
      observe: vi.fn(),
      unobserve: vi.fn(),
      disconnect: vi.fn(),
    }
    const sizer = createBatchTableSizer(store, {
      createObserver(callback) {
        resizeCallback = callback
        return observer
      },
    })

    expect(sizer.observe(null)).toBe(false)
    expect(observer.observe).not.toHaveBeenCalled()

    const wrap = tableWrap()
    expect(sizer.observe(wrap)).toBe(true)
    expect(observer.observe).toHaveBeenCalledWith(wrap)
    expect(store.batchPageSize).toBe(19)
    expect(store.batchPage).toBe(7)
    expect(store.loadBatches).toHaveBeenCalledTimes(1)

    expect(sizer.observe(wrap)).toBe(false)
    expect(observer.observe).toHaveBeenCalledTimes(1)
    expect(store.loadBatches).toHaveBeenCalledTimes(1)

    wrap.clientHeight = 636
    resizeCallback()
    expect(store.batchPageSize).toBe(15)
    expect(store.batchPage).toBe(7)
    expect(store.loadBatches).toHaveBeenCalledTimes(2)

    sizer.observe(null)
    expect(observer.unobserve).toHaveBeenCalledWith(wrap)

    const replacement = tableWrap({ height: 556 })
    expect(sizer.observe(replacement)).toBe(true)
    expect(observer.observe).toHaveBeenLastCalledWith(replacement)
    expect(store.batchPageSize).toBe(13)
    expect(store.loadBatches).toHaveBeenCalledTimes(3)

    sizer.disconnect()
    expect(observer.unobserve).toHaveBeenCalledWith(replacement)
    expect(observer.disconnect).toHaveBeenCalledTimes(1)
  })

  it('waits for a hidden table to receive a real height before reloading', () => {
    const store = {
      batchPageSize: 10,
      batchPage: 4,
      loadBatches: vi.fn().mockResolvedValue(null),
    }
    let resizeCallback
    const observer = {
      observe: vi.fn(),
      unobserve: vi.fn(),
      disconnect: vi.fn(),
    }
    const sizer = createBatchTableSizer(store, {
      createObserver(callback) {
        resizeCallback = callback
        return observer
      },
    })

    const wrap = tableWrap({ height: 0 })
    sizer.observe(wrap)
    expect(observer.observe).toHaveBeenCalledWith(wrap)
    expect(store.batchPageSize).toBe(10)
    expect(store.batchPage).toBe(4)
    expect(store.loadBatches).not.toHaveBeenCalled()

    wrap.clientHeight = 796
    resizeCallback()
    expect(store.batchPageSize).toBe(19)
    expect(store.batchPage).toBe(4)
    expect(store.loadBatches).toHaveBeenCalledTimes(1)
  })

  it('页大小变化时保留 URL 恢复的页码', () => {
    const store = {
      batchPageSize: 10,
      batchPage: 3,
      loadBatches: vi.fn().mockResolvedValue(null),
    }
    const observer = { observe: vi.fn(), unobserve: vi.fn(), disconnect: vi.fn() }
    const sizer = createBatchTableSizer(store, {
      createObserver: () => observer,
    })

    sizer.observe(tableWrap())

    expect(store.batchPageSize).toBe(19)
    expect(store.batchPage).toBe(3)
    expect(store.loadBatches).toHaveBeenCalledTimes(1)
  })
})
