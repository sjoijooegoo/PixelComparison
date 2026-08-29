import { describe, expect, it } from 'vitest'

import { createPointHitIndex } from './pointHitIndex'

describe('GPM map point hit index', () => {
  it('finds points whose hit area crosses a spatial cell boundary', () => {
    const point = { source: { id: 1 }, x: 31, y: 31, hit: 5 }
    const index = createPointHitIndex([point], 32)

    expect(index.find(34, 34)).toBe(point)
    expect(index.find(40, 40)).toBeNull()
  })

  it('returns the nearest overlapping point', () => {
    const left = { source: { id: 1 }, x: 10, y: 10, hit: 12 }
    const right = { source: { id: 2 }, x: 15, y: 10, hit: 12 }
    const index = createPointHitIndex([left, right])

    expect(index.find(14, 10)).toBe(right)
  })
})
