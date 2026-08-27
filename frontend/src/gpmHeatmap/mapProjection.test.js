import { describe, expect, it } from 'vitest'

import { containedImageRect, createMapProjection } from './mapProjection'

describe('GPM map projection', () => {
  it('在 contain 后的真实图片矩形内映射坐标', () => {
    expect(containedImageRect(1000, 500, 800, 800)).toEqual({
      left: 250, top: 0, width: 500, height: 500,
    })
    const projection = createMapProjection(
      { origin: [-100, 200], range: [400, 200], x_reverse: false, y_reverse: true },
      { left: 250, top: 0, width: 500, height: 500 },
    )
    expect(projection.project([100, 300])).toEqual({ x: 500, y: 250, inBounds: true })
    expect(projection.unproject({ x: 500, y: 250 })).toEqual([100, 300])
  })

  it('同时支持坐标反转与越界标记', () => {
    const projection = createMapProjection(
      { origin: [0, 0], range: [100, 100], x_reverse: true, y_reverse: false },
      { left: 0, top: 0, width: 100, height: 100 },
    )
    expect(projection.project([25, 75])).toEqual({ x: 75, y: 25, inBounds: true })
    expect(projection.project([120, 50]).inBounds).toBe(false)
    const direction = projection.projectDirection([1, 1])
    expect(direction.x).toBeCloseTo(-Math.SQRT1_2)
    expect(direction.y).toBeCloseTo(-Math.SQRT1_2)
  })
})
