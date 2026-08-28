import { describe, expect, it } from 'vitest'

import {
  compileScaleSegments,
  segmentsFromLegacy,
} from './scaleExpressions'

describe('GPM scale interval expressions', () => {
  it('保留列表顺序并按表达式编译运行时区间', () => {
    const result = compileScaleSegments([
      { color: '#ff0000', expression: '>= 390' },
      { color: '#00ffff', expression: '>=365 & <390' },
      { color: '#00ff00', expression: '<365' },
    ])

    expect(result).toEqual({
      segments: [
        { color: '#ff0000', expression: '>=390' },
        { color: '#00ffff', expression: '>=365 & <390' },
        { color: '#00ff00', expression: '<365' },
      ],
      thresholds: [365, 390],
      colors: ['#00ff00', '#00ffff', '#ff0000'],
    })
  })

  it.each([
    [
      [
        { color: '#00ff00', expression: '<365' },
        { color: '#00ffff', expression: '>365 & <390' },
        { color: '#ff0000', expression: '>=390' },
      ],
      '边界 365 不属于任何颜色段',
    ],
    [
      [
        { color: '#00ff00', expression: '<=365' },
        { color: '#00ffff', expression: '>=365 & <390' },
        { color: '#ff0000', expression: '>=390' },
      ],
      '边界 365 同时属于两个颜色段',
    ],
    [
      [
        { color: '#00ff00', expression: '<365' },
        { color: '#00ffff', expression: '>=360 & <390' },
        { color: '#ff0000', expression: '>=390' },
      ],
      '区间在 360 附近发生重叠',
    ],
  ])('拒绝有断档或重叠的区间：%s', (segments, message) => {
    expect(() => compileScaleSegments(segments)).toThrow(message)
  })

  it('拒绝不受支持的表达式语法', () => {
    expect(() => compileScaleSegments([
      { color: '#00ff00', expression: '<365 | >500' },
      { color: '#ff0000', expression: '>=365' },
    ])).toThrow('仅支持 <、<=、>、>= 和 &')
  })

  it('把高值更优的旧标尺转换成等价的升序颜色区间', () => {
    expect(segmentsFromLegacy(
      [100, 200], ['#ff0000', '#ffff00', '#00ff00'], 'higher_is_better',
    )).toEqual([
      { color: '#00ff00', expression: '<100' },
      { color: '#ffff00', expression: '>=100 & <200' },
      { color: '#ff0000', expression: '>=200' },
    ])
  })
})
