import { describe, expect, it } from 'vitest'

import {
  SHADING_QUALITY_OPTIONS,
  inclusiveDateRangeDays,
  isDateRangeAllowed,
  p4Label,
  visibleQualityOptions,
} from './store'

describe('display helpers', () => {
  it('按项目设置筛选画质并在空集合时回退全部档位', () => {
    expect(visibleQualityOptions({ filter_shading_qualities: [5, 3] }))
      .toEqual([{ value: 5, label: '电影' }, { value: 3, label: '精美' }])
    expect(visibleQualityOptions({ filter_shading_qualities: [] })).toEqual(SHADING_QUALITY_OPTIONS)
  })

  it('统一格式化缺失和有效的 P4 版本', () => {
    expect(p4Label(null)).toBe('——')
    expect(p4Label(123)).toBe('P4 123')
  })

  it('连续日期范围最多允许14个首尾均计入的自然日', () => {
    expect(inclusiveDateRangeDays('2026-07-01', '2026-07-14')).toBe(14)
    expect(isDateRangeAllowed('2026-07-01', '2026-07-14')).toBe(true)
    expect(isDateRangeAllowed('2026-07-01', '2026-07-15')).toBe(false)
  })
})
