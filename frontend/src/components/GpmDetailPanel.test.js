// @vitest-environment happy-dom
import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import GpmDetailPanel from './GpmDetailPanel.vue'

const table = {
  cols: [{ key: 'value', name: '数据' }],
  data: [['value']],
}

describe('GpmDetailPanel', () => {
  it('在标题行展示当前点位序号、坐标和指标值', () => {
    const wrapper = mount(GpmDetailPanel, {
      props: {
        point: { id: 8, detail_data: [] },
        summaryPoint: {
          id: 8,
          index: 8,
          position: [-192711, 240138, 0],
          heat_map_data: { Scene_DC: 421 },
        },
        metricKey: 'Scene_DC',
        metricName: '场景DC',
      },
    })

    expect(wrapper.get('.point-meta').text()).toContain('序号08')
    expect(wrapper.get('.coordinates').text()).toContain('X: -192711, Y: 240138')
    expect(wrapper.get('.metric-value').text()).toContain('场景DC421')
  })

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

  it('切换点位时按数据结构路径保留根节点和子节点展开状态', async () => {
    const point = {
      id: 8,
      detail_data: [{
        name: 'ModelUsage',
        children: [
          { name: 'Scene', table_data: table },
          { name: 'Effect', table_data: table },
        ],
      }],
    }
    const wrapper = mount(GpmDetailPanel, { props: { point } })

    await wrapper.findAll('.detail-summary')[0].trigger('click')
    await wrapper.findAll('.detail-summary')[2].trigger('click')
    await wrapper.get('.table-sort').trigger('click')
    await wrapper.get('.table-sort').trigger('click')
    expect(wrapper.findAll('.detail-summary').map((item) => item.attributes('aria-expanded')))
      .toEqual(['true', 'false', 'true'])
    expect(wrapper.get('th').attributes('aria-sort')).toBe('ascending')

    await wrapper.setProps({
      point: {
        id: 9,
        detail_data: [{
          name: 'ModelUsage',
          children: [
            { name: 'Scene', table_data: { ...table, data: [['new-scene']] } },
            { name: 'Effect', table_data: { ...table, data: [['new-effect']] } },
          ],
        }],
      },
    })

    expect(wrapper.findAll('.detail-summary').map((item) => item.attributes('aria-expanded')))
      .toEqual(['true', 'false', 'true'])
    expect(wrapper.get('th').attributes('aria-sort')).toBe('ascending')
    expect(wrapper.text()).toContain('new-effect')
  })
})
