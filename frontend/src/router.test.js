// @vitest-environment happy-dom
import { beforeEach, describe, expect, it } from 'vitest'

import { router } from './router'

beforeEach(async () => {
  await router.replace('/batches')
})

describe('workspace routes', () => {
  it('旧列表图深链重定向到截图对比并保留查询参数', async () => {
    await router.push('/batches/Coral_WP?branch_tag=engine-ue5&current=42')

    expect(router.currentRoute.value.fullPath).toBe(
      '/screenshot/Coral_WP?branch_tag=engine-ue5&current=42',
    )
  })

  it('旧对比页面交给全局兜底返回批次管理', async () => {
    await router.push('/comparison/123')

    expect(router.currentRoute.value.fullPath).toBe('/batches')
    expect(router.getRoutes().some((route) => route.path.startsWith('/comparison'))).toBe(false)
  })

  it('提供可选场景的截图对比工作区路由', () => {
    expect(router.getRoutes().some((route) => route.path === '/screenshot/:sceneId?')).toBe(true)
  })

  it('提供可选场景的 GPMHeatmap 工作区路由', () => {
    expect(router.getRoutes().some((route) => route.path === '/gpm-heatmap/:sceneId?')).toBe(true)
  })
})
