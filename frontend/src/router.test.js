// @vitest-environment happy-dom
import { beforeEach, describe, expect, it } from 'vitest'

import { router } from './router'

beforeEach(async () => {
  await router.replace('/screenshot')
})

describe('workspace routes', () => {
  it('旧列表图深链重定向到截图对比并保留查询参数', async () => {
    await router.push('/batches/Coral_WP?branch_tag=engine-ue5&current=42')

    expect(router.currentRoute.value.fullPath).toBe(
      '/screenshot/Coral_WP?branch_tag=engine-ue5&current=42',
    )
  })

  it('旧对比页面交给全局兜底返回截图对比', async () => {
    await router.push('/comparison/123')

    expect(router.currentRoute.value.fullPath).toBe('/screenshot')
    expect(router.getRoutes().some((route) => route.path.startsWith('/comparison'))).toBe(false)
  })

  it('提供可选场景的截图对比工作区路由', () => {
    expect(router.getRoutes().some((route) => route.path === '/screenshot/:sceneId?')).toBe(true)
  })

  it('提供可选场景的 GPMHeatmap 工作区路由', () => {
    expect(router.getRoutes().some((route) => route.path === '/gpm-heatmap/:sceneId?')).toBe(true)
  })

  it('旧批次和设置地址重定向到新的上下文页面', async () => {
    await router.push('/batches?branch_tag=engine-ue5')
    expect(router.currentRoute.value.fullPath).toBe(
      '/batch-management/capture?branch_tag=engine-ue5',
    )

    await router.push('/settings?return_to=/screenshot/SceneA')
    expect(router.currentRoute.value.path).toBe('/settings/screenshot-comparison')
    expect(router.currentRoute.value.query.return_to).toBe('/screenshot/SceneA')
  })

  it('提供截图与 GPM 两个独立批次管理路由', () => {
    const paths = router.getRoutes().map((route) => route.path)
    expect(paths).toContain('/batch-management/capture')
    expect(paths).toContain('/batch-management/gpm')
  })

  it('提供截图对比与热力图两个独立设置路由', () => {
    const paths = router.getRoutes().map((route) => route.path)
    expect(paths).toContain('/settings/screenshot-comparison')
    expect(paths).toContain('/settings/gpm-heatmap')
    expect(paths).toContain('/settings/gpm-heatmap/scales')
  })
})
