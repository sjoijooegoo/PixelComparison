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

    expect(wrapper.findAll('.table-sort')[1].attributes('aria-label')).toBe('按DC降序排列')
    expect(wrapper.findAll('.table-sort')[1].attributes('title')).toBeUndefined()
    await wrapper.findAll('.table-sort')[1].trigger('click')
    expect(dcValues()).toEqual(['30', '10', '2'])
    expect(wrapper.findAll('th')[1].attributes('aria-sort')).toBe('descending')

    await wrapper.findAll('.table-sort')[1].trigger('click')
    expect(dcValues()).toEqual(['2', '10', '30'])
    expect(wrapper.findAll('th')[1].attributes('aria-sort')).toBe('ascending')
    expect(sourceRows).toEqual([['ten', 10], ['two', 2], ['thirty', '30']])
  })

  it('可从表头右缘拖动列宽且不会触发表格排序', async () => {
    const wrapper = mount(GpmDetailNode, {
      props: {
        expanded: true,
        node: {
          name: '模型数据',
          table_data: {
            cols: [{ key: 'name', name: '名称' }, { key: 'dc', name: 'DC' }],
            data: [['tree', 12]],
          },
        },
      },
    })
    const headers = wrapper.findAll('th')
    const sourceWidths = [240, 160]
    headers.forEach((header, index) => {
      header.element.getBoundingClientRect = () => ({ width: sourceWidths[index] })
    })
    const resizer = wrapper.findAll('.column-resizer')[0]
    await resizer.trigger('mousedown', { button: 0, clientX: 240 })
    window.dispatchEvent(new MouseEvent('mousemove', { clientX: 280 }))
    await wrapper.vm.$nextTick()

    expect(wrapper.findAll('col')[0].attributes('style')).toContain('width: 280px')
    expect(wrapper.findAll('col')[1].attributes('style')).toContain('width: 120px')
    expect(wrapper.get('.detail-table').attributes('style')).toContain('width: 400px')
    expect(wrapper.findAll('.column-resizer')).toHaveLength(1)
    expect(headers[0].attributes('aria-sort')).toBe('none')

    window.dispatchEvent(new MouseEvent('mouseup'))
    await resizer.trigger('click')
    expect(headers[0].attributes('aria-sort')).toBe('none')
  })

  it('长文本始终限制在所属单元格并仅在溢出时保留完整悬停内容', async () => {
    const longText = 'VeryLongAssetNameWithoutAnyNaturalBreakPoint_1234567890'
    const longLink = 'https://example.com/a/very/long/path/without/a/short/display/name'
    const wrapper = mount(GpmDetailNode, {
      props: {
        expanded: true,
        node: {
          name: '长文本数据',
          table_data: {
            cols: [{ key: 'asset', name: '资产' }, { key: 'source', name: '源数据' }],
            data: [[longText, longLink]],
          },
        },
      },
    })

    const cells = wrapper.findAll('tbody td')
    const contents = cells.map((cell) => cell.get('.cell-content'))
    expect(cells[0].get('.cell-content').text()).toBe(longText)
    expect(cells[1].get('.cell-content').text()).toBe(longLink)
    expect(cells.every((cell) => cell.attributes('title') === undefined)).toBe(true)

    for (const content of contents) {
      Object.defineProperty(content.element, 'clientWidth', { configurable: true, value: 100 })
      Object.defineProperty(content.element, 'scrollWidth', { configurable: true, value: 240 })
      await content.trigger('mouseenter')
    }
    expect(contents.map((content) => content.attributes('title'))).toEqual([longText, longLink])
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

  it('将完整的 HTTP 和 HTTPS 数据渲染为安全的新窗口链接', () => {
    const wrapper = mount(GpmDetailNode, {
      props: {
        expanded: true,
        node: {
          name: '源数据',
          table_data: {
            cols: [{ key: 'source', name: '源数据' }],
            data: [
              ['http://example.com/report.csv'],
              ['https://example.com/task/1'],
              ['ftp://example.com/file.csv'],
              ['javascript:alert(1)'],
            ],
          },
        },
      },
    })

    const links = wrapper.findAll('.detail-link')
    expect(links.map((link) => link.text())).toEqual([
      'http://example.com/report.csv',
      'https://example.com/task/1',
    ])
    expect(links.every((link) => link.attributes('target') === '_blank')).toBe(true)
    expect(links.every((link) => link.attributes('rel') === 'noopener noreferrer')).toBe(true)
    expect(wrapper.text()).toContain('ftp://example.com/file.csv')
    expect(wrapper.text()).toContain('javascript:alert(1)')
  })
})
