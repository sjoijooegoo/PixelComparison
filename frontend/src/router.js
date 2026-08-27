import { createRouter, createWebHistory } from 'vue-router'

// 视图懒加载,避免 router → view → store → router 的循环依赖
const routes = [
  { path: '/', redirect: '/batches' },
  { path: '/batches', component: () => import('./views/BatchView.vue') },
  {
    path: '/batches/:sceneId',
    redirect: (to) => ({
      path: `/screenshot/${encodeURIComponent(String(to.params.sceneId))}`,
      query: to.query,
    }),
  },
  { path: '/screenshot/:sceneId?', component: () => import('./views/ScreenshotComparisonView.vue') },
  { path: '/map-build/:sceneId?', component: () => import('./views/MapBuildView.vue') },
  { path: '/gpm-heatmap/:sceneId?', component: () => import('./views/GpmHeatmapView.vue') },
  { path: '/settings', component: () => import('./components/ProjectSettings.vue') },
  { path: '/:pathMatch(.*)*', redirect: '/batches' },
]

export const router = createRouter({
  history: createWebHistory(),
  routes,
})
