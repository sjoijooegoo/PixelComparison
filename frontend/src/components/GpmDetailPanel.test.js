// @vitest-environment happy-dom
import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import GpmDetailPanel from './GpmDetailPanel.vue'

const table = {
  cols: [{ key: 'value', name: '数据' }],
  data: [['value']],
}

describe('GpmDetailPanel', () => {
  it('默认全部折叠且顶层保持单项展开', async () => {
    const wrapper = mount(GpmDetailPanel, {
      props: {
        point: {
          id: 8,
          index: 8,
          detail_data: [
            { name: 'Total:当前画面总的DC和面数', table_data: table },
            { name: 'ModelUsage:每个模块的DC和面数分布', table_data: table },
          ],
        },
      },
    })
    const summaries = wrapper.findAll('.detail-node.root > .detail-summary')

    expect(summaries.map((item) => item.attributes('aria-expanded'))).toEqual(['false', 'false'])
    await summaries[0].trigger('click')
    expect(summaries.map((item) => item.attributes('aria-expanded'))).toEqual(['true', 'false'])
    await summaries[1].trigger('click')
    expect(summaries.map((item) => item.attributes('aria-expanded'))).toEqual(['false', 'true'])
  })

  it('同一点位重新加载时清空临时展开状态', async () => {
    const point = {
      id: 8,
      detail_data: [{ name: 'ModelUsage', table_data: table }],
    }
    const wrapper = mount(GpmDetailPanel, { props: { point } })

    await wrapper.get('.detail-summary').trigger('click')
    expect(wrapper.get('.detail-summary').attributes('aria-expanded')).toBe('true')

    await wrapper.setProps({ point: { ...point, detail_data: [...point.detail_data] } })
    expect(wrapper.get('.detail-summary').attributes('aria-expanded')).toBe('false')
  })
})
