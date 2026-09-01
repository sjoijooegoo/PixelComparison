// @vitest-environment happy-dom
import { mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it } from 'vitest'

import MapBuildTrendChart from './MapBuildTrendChart.vue'

function metrics(total) {
  return {
    total_bytes: total,
    all_mips_bytes: total * 1.2,
    cook_estimate_bytes: total * 0.9,
    lightmap_all_mips_bytes: total / 2,
    hue_all_mips_bytes: total / 10,
    shadowmap_all_mips_bytes: total / 4,
    precomputed_light_volume_bytes: total / 5,
    precomputed_reflection_volume_bytes: total / 6,
    volumetric_lightmap_bytes: total / 7,
    reflection_capture_bytes: total / 8,
    mesh_map_build_data_bytes: total / 9,
    light_build_data_bytes: total / 10,
    precomputed_instanced_ilc_bytes: total / 11,
    precomputed_instanced_pr_bytes: total / 12,
    lightmap_resource_cluster_bytes: total / 13,
  }
}

describe('MapBuildTrendChart', () => {
  beforeEach(() => window.localStorage.clear())

  it('同一天的多个批次保留为独立点并在横轴和提示中区分', async () => {
    const wrapper = mount(MapBuildTrendChart, {
      props: {
        points: [
          {
            batch: { id: '802', created_at: '2026-08-01T09:00', p4_version: 6514223 },
            metrics: metrics(100),
          },
          {
            batch: { id: '803', created_at: '2026-08-01T17:00', p4_version: 6514224 },
            metrics: metrics(120),
          },
        ],
      },
    })

    expect(wrapper.findAll('.x-label').map((label) => label.text())).toEqual([
      '08-01 09:00',
      '08-01 17:00',
    ])
    expect(wrapper.findAll('.series-dot')).toHaveLength(10)

    await wrapper.findAll('.point-hit-area')[1].trigger('mouseenter')
    expect(wrapper.get('.tooltip-time').text()).toBe('2026-08-01 17:00')
    expect(wrapper.get('.tooltip-heading > span').text()).toBe('P4 6514224')
    expect(wrapper.get('.tooltip-heading').text()).not.toContain('批次')
  })

  it('点击趋势点会选择对应网格批次且命中区不会产生焦点框', async () => {
    const points = [
      {
        batch: { id: '802', created_at: '2026-08-01T09:00', p4_version: 6514223 },
        metrics: metrics(100),
      },
      {
        batch: { id: '803', created_at: '2026-08-01T17:00', p4_version: 6514224 },
        metrics: metrics(120),
      },
    ]
    const wrapper = mount(MapBuildTrendChart, {
      props: { points, currentBatchId: '803' },
    })
    const hitAreas = wrapper.findAll('.point-hit-area')

    expect(hitAreas[1].attributes('role')).toBeUndefined()
    expect(hitAreas[1].attributes('tabindex')).toBeUndefined()
    expect(hitAreas[1].attributes('focusable')).toBe('false')
    expect(hitAreas[1].attributes('aria-label')).toContain('P4 6514224')
    expect(hitAreas[1].element.tagName.toLowerCase()).toBe('circle')
    expect(hitAreas[1].attributes('r')).toBe('20')
    expect(wrapper.find('rect.point-hit-area').exists()).toBe(false)
    expect(wrapper.find('.selected-batch-line').exists()).toBe(false)
    expect(wrapper.findAll('.current-batch-dot')).toHaveLength(5)

    await hitAreas[0].trigger('mouseenter')
    expect(wrapper.find('.tooltip').exists()).toBe(true)
    await hitAreas[0].trigger('click')
    expect(wrapper.find('.tooltip').exists()).toBe(true)
    await wrapper.setProps({ currentBatchId: '802' })
    expect(wrapper.get('.tooltip-heading').text()).not.toContain('当前网格批次')

    expect(wrapper.emitted('selectBatch')).toEqual([
      [points[0].batch],
    ])

    await hitAreas[0].trigger('mouseleave')
    expect(wrapper.find('.tooltip').exists()).toBe(false)
  })

  it('旧批次缺少 P4 版本时使用统一占位符', async () => {
    const wrapper = mount(MapBuildTrendChart, {
      props: {
        points: [
          { batch: { id: 'legacy', created_at: '2026-08-01T09:00' }, metrics: metrics(100) },
        ],
      },
    })

    await wrapper.get('.point-hit-area').trigger('mouseenter')

    expect(wrapper.get('.tooltip-time').text()).toBe('2026-08-01 09:00')
    expect(wrapper.get('.tooltip-heading > span').text()).toBe('——')
    expect(wrapper.get('.tooltip-heading').text()).not.toContain('批次')
  })

  it('图例可以筛选曲线并同步纵轴、提示框和本地偏好', async () => {
    const points = [
      { batch: { id: '802', created_at: '2026-08-01T09:00' }, metrics: metrics(100 * 1024 * 1024) },
      { batch: { id: '803', created_at: '2026-08-02T09:00' }, metrics: metrics(120 * 1024 * 1024) },
    ]
    const wrapper = mount(MapBuildTrendChart, { props: { points } })
    const toggles = wrapper.findAll('.legend-primary .legend-item')
    const initialMaximum = Math.max(...wrapper.findAll('.axis-label').map((label) => Number(label.text())))

    expect(toggles).toHaveLength(5)
    expect(toggles.every((toggle) => toggle.attributes('aria-pressed') === 'true')).toBe(true)
    expect(wrapper.findAll('.series-dot')).toHaveLength(10)

    await toggles[0].trigger('click')
    await toggles[1].trigger('click')

    expect(toggles[0].attributes('aria-pressed')).toBe('false')
    expect(toggles[1].attributes('aria-pressed')).toBe('false')
    expect(wrapper.findAll('.series-dot')).toHaveLength(6)
    const filteredMaximum = Math.max(...wrapper.findAll('.axis-label').map((label) => Number(label.text())))
    expect(filteredMaximum).toBeLessThan(initialMaximum)
    const stored = JSON.parse(window.localStorage.getItem('pixelcomp.mapBuildTrend.visibleSeries.v1'))
    expect(stored).not.toContain('all_mips_bytes')
    expect(stored).not.toContain('cook_estimate_bytes')

    await wrapper.findAll('.point-hit-area')[1].trigger('mouseenter')
    expect(wrapper.findAll('.tooltip-row')).toHaveLength(3)
    expect(wrapper.get('.tooltip').text()).not.toContain('总 Mip')
    expect(wrapper.get('.tooltip').text()).not.toContain('Cook 估算')

    wrapper.unmount()
    const restored = mount(MapBuildTrendChart, { props: { points } })
    expect(restored.findAll('.legend-item')[0].attributes('aria-pressed')).toBe('false')
    expect(restored.findAll('.series-dot')).toHaveLength(6)
  })

  it('静态指标始终展开、默认关闭并在开启后持久化', async () => {
    const points = [
      { batch: { id: '802', created_at: '2026-08-01T09:00' }, metrics: metrics(100 * 1024 * 1024) },
      { batch: { id: '803', created_at: '2026-08-02T09:00' }, metrics: metrics(120 * 1024 * 1024) },
    ]
    const wrapper = mount(MapBuildTrendChart, { props: { points } })

    expect(wrapper.find('.legend-extra').exists()).toBe(true)
    expect(wrapper.find('.legend-more').exists()).toBe(false)
    expect(wrapper.findAll('svg path')).toHaveLength(5)

    const optionalToggles = wrapper.findAll('.legend-extra .legend-item')
    expect(optionalToggles).toHaveLength(9)
    expect(optionalToggles.every((toggle) => toggle.attributes('aria-pressed') === 'false')).toBe(true)

    await optionalToggles[0].trigger('click')
    expect(wrapper.findAll('svg path')).toHaveLength(6)
    expect(wrapper.findAll('.series-dot')).toHaveLength(12)
    expect(JSON.parse(window.localStorage.getItem('pixelcomp.mapBuildTrend.visibleSeries.v1')))
      .toContain('precomputed_light_volume_bytes')

    await wrapper.findAll('.point-hit-area')[1].trigger('mouseenter')
    expect(wrapper.get('.tooltip').text()).toContain('预计算光照体积')

    wrapper.unmount()
    const restored = mount(MapBuildTrendChart, { props: { points } })
    expect(restored.get('.legend-extra .legend-item[aria-pressed="true"]').text())
      .toBe('预计算光照体积')
    expect(restored.findAll('svg path')).toHaveLength(6)
  })

  it('至少保留一条可见曲线', async () => {
    const wrapper = mount(MapBuildTrendChart, {
      props: {
        points: [{ batch: { id: '802', created_at: '2026-08-01T09:00' }, metrics: metrics(100) }],
      },
    })
    const toggles = wrapper.findAll('.legend-item[aria-pressed="true"]')

    for (let index = 0; index < toggles.length - 1; index += 1) {
      await toggles[index].trigger('click')
    }

    expect(wrapper.findAll('.series-dot')).toHaveLength(1)
    expect(toggles.at(-1).attributes('disabled')).toBeUndefined()
    expect(toggles.at(-1).attributes('title')).toBe('至少保留一项趋势指标')

    await toggles.at(-1).trigger('click')
    expect(wrapper.findAll('.series-dot')).toHaveLength(1)
    expect(toggles.at(-1).get('.legend-limit').text()).toBe('至少保留一项')
  })

  it('365 个批次点仍在基础性能预算内并限制横轴标签数量', () => {
    const start = new Date('2025-08-07T09:00:00')
    const points = Array.from({ length: 365 }, (_, index) => {
      const createdAt = new Date(start)
      createdAt.setDate(start.getDate() + index)
      return {
        batch: {
          id: String(10_000 + index),
          created_at: createdAt.toISOString().slice(0, 16),
        },
        metrics: metrics((index + 1) * 1024 * 1024),
      }
    })

    const started = performance.now()
    const wrapper = mount(MapBuildTrendChart, { props: { points } })
    const renderMilliseconds = performance.now() - started

    expect(wrapper.findAll('rect.point-hit-area')).toHaveLength(0)
    expect(wrapper.findAll('circle.point-hit-area')).toHaveLength(365 * 5)
    expect(wrapper.findAll('svg path')).toHaveLength(5)
    expect(wrapper.findAll('.series-dot')).toHaveLength(365 * 5)
    expect(wrapper.findAll('.x-label').length).toBeLessThanOrEqual(9)
    expect(renderMilliseconds).toBeLessThan(2000)
  })
})
