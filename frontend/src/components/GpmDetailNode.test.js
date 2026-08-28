// @vitest-environment happy-dom
import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import GpmDetailNode from './GpmDetailNode.vue'

describe('GpmDetailNode', () => {
  it('保留原始统计标题并按分层面板展开子项', async () => {
    const wrapper = mount(GpmDetailNode, {
      props: {
        node: {
          name: 'DepthPass 总DC:55 总面数:70786',
          children: [{
            name: '角色 总DC:1 总面数:2990',
            table_data: {
              cols: [{ key: 'asset', name: '资产' }],
              data: [['hero_mesh']],
            },
          }],
        },
      },
    })

    expect(wrapper.get('.node-title').text()).toBe('DepthPass 总DC:55 总面数:70786')
    expect(wrapper.find('.children-stack').exists()).toBe(false)

    await wrapper.get('.detail-summary').trigger('click')
    expect(wrapper.emitted('toggle')).toHaveLength(1)
    await wrapper.setProps({ expanded: true })

    expect(wrapper.find('.children-stack').exists()).toBe(true)
    expect(wrapper.findAll('.node-title').map((item) => item.text())).toEqual([
      'DepthPass 总DC:55 总面数:70786', '角色 总DC:1 总面数:2990',
    ])
  })

  it('没有子项和表格的节点不可展开', () => {
    const wrapper = mount(GpmDetailNode, { props: { node: { name: 'GPUCulled' } } })

    expect(wrapper.get('.detail-summary').attributes('disabled')).toBeDefined()
    expect(wrapper.get('.detail-summary').classes()).toContain('empty')
    expect(wrapper.get('.detail-summary').attributes('aria-expanded')).toBeUndefined()
  })

  it('同一层级只展开一个子节点', async () => {
    const table = (value) => ({
      cols: [{ key: 'value', name: '数据' }],
      data: [[value]],
    })
    const wrapper = mount(GpmDetailNode, {
      props: {
        expanded: true,
        node: {
          name: '场景',
          children: [
            { name: '建筑', table_data: table('building') },
            { name: '植被', children: [{ name: '灌木', table_data: table('foliage') }] },
          ],
        },
      },
    })

    await wrapper.findAll('.detail-summary')[1].trigger('click')
    expect(wrapper.findAll('table')).toHaveLength(1)
    expect(wrapper.text()).toContain('building')

    await wrapper.findAll('.detail-summary')[2].trigger('click')
    expect(wrapper.findAll('table')).toHaveLength(0)
    expect(wrapper.text()).not.toContain('building')

    await wrapper.findAll('.detail-summary')[3].trigger('click')
    expect(wrapper.findAll('table')).toHaveLength(1)
    expect(wrapper.text()).toContain('foliage')

    await wrapper.setProps({ expanded: false })
    expect(wrapper.findAll('table')).toHaveLength(0)
    await wrapper.setProps({ expanded: true })
    expect(wrapper.findAll('table')).toHaveLength(1)
    expect(wrapper.text()).toContain('foliage')
  })

  it('首次点击表头后按当前列降序排列，再次点击切换为升序', async () => {
    const sourceRows = [['ten', 10], ['two', 2], ['thirty', '30']]
    const wrapper = mount(GpmDetailNode, {
      props: {
        expanded: true,
        node: {
          name: '模型数据',
          table_data: {
            cols: [{ key: 'name', name: '名称' }, { key: 'dc', name: 'DC' }],
            data: sourceRows,
          },
        },
      },
    })
    const dcValues = () => wrapper.findAll('tbody tr')
      .map((row) => row.findAll('td')[1].text())

    expect(wrapper.findAll('.table-sort')[1].attributes('title')).toBe('按DC降序排列')
    await wrapper.findAll('.table-sort')[1].trigger('click')
    expect(dcValues()).toEqual(['30', '10', '2'])
    expect(wrapper.findAll('th')[1].attributes('aria-sort')).toBe('descending')

    await wrapper.findAll('.table-sort')[1].trigger('click')
    expect(dcValues()).toEqual(['2', '10', '30'])
    expect(wrapper.findAll('th')[1].attributes('aria-sort')).toBe('ascending')
    expect(sourceRows).toEqual([['ten', 10], ['two', 2], ['thirty', '30']])
  })

  it('大表格完整保留数据并使用上一页、下一页切换', async () => {
    const rows = Array.from({ length: 250 }, (_, index) => [`asset-${index}`, index])
    const wrapper = mount(GpmDetailNode, {
      props: {
        expanded: true,
        node: {
          name: '完整资产列表',
          table_data: {
            cols: [{ key: 'asset', name: '资产' }, { key: 'dc', name: 'DC' }],
            data: rows,
          },
        },
      },
    })

    expect(wrapper.findAll('tbody tr')).toHaveLength(15)
    expect(wrapper.text()).toContain('asset-0')
    expect(wrapper.get('.table-pagination').attributes('aria-label')).toBe('表格分页，共 250 条')
    expect(wrapper.get('.page-number.active').text()).toBe('1')

    expect(wrapper.get('[aria-label="上一页"]').attributes('disabled')).toBeDefined()
    await wrapper.get('[aria-label="第 2 页"]').trigger('click')

    expect(wrapper.text()).toContain('asset-15')
    expect(wrapper.text()).not.toContain('asset-0')
    expect(wrapper.get('.page-number.active').text()).toBe('2')
    expect(wrapper.findAll('.page-number')).toHaveLength(5)
    expect(wrapper.find('.row-limit').exists()).toBe(false)
  })
})
