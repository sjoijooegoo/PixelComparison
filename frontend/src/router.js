import { createRouter, createWebHistory } from 'vue-router'

// 视图懒加载,避免 router → view → store → router 的循环依赖
const routes = [
  { path: '/', redirect: '/screenshot' },
  {
    path: '/batch-management/capture',
    component: () => import('./views/BatchView.vue'),
  },
  {
    path: '/batch-management/gpm',
    component: () => import('./views/GpmBatchView.vue'),
  },
  {
    path: '/batches',
    redirect: (to) => ({ path: '/batch-management/capture', query: to.query }),
  },
  {
    path: '/batches/:sceneId',
    redirect: (to) => ({
      path: `/screenshot/${encodeURIComponent(String(to.params.sceneId))}`,
      query: to.query,
    }),
  },
  { path: '/screenshot/:sceneId?', component: () => import('./views/ScreenshotComparisonView.vue') },
  { path: '/map-build/:sceneId?', component: () => import('./views/MapBuildView.vue') },
  { path: '/gpm-heatmap/:mapName?', component: () => import('./views/GpmHeatmapView.vue') },
  {
    path: '/settings/screenshot-comparison',
    component: () => import('./components/ProjectSettings.vue'),
  },
  {
    path: '/settings/gpm-heatmap',
    component: () => import('./views/GpmScaleSettingsView.vue'),
  },
  {
    path: '/settings',
    redirect: (to) => ({ path: '/settings/screenshot-comparison', query: to.query }),
  },
  { path: '/:pathMatch(.*)*', redirect: '/screenshot' },
]

export const router = createRouter({
  history: createWebHistory(),
  routes,
})
