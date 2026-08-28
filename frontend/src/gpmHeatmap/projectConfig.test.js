import { describe, expect, it } from 'vitest'
import { projectedPointStyle } from './projectConfig'

describe('GPM project config preview math', () => {
  it('按地图反转配置投影预览点位', () => {
    expect(projectedPointStyle(
      { origin: [10, 20], range: [100, 200], x_reverse: false, y_reverse: true },
      [60, 120],
    )).toEqual({ left: '50%', top: '50%', inBounds: true })
    expect(projectedPointStyle(
      { origin: [10, 20], range: [100, 200], x_reverse: true, y_reverse: false },
      [60, 120],
    )).toEqual({ left: '50%', top: '50%', inBounds: true })
  })
})
