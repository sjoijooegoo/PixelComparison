import { createRouter, createWebHistory } from 'vue-router'

// 视图懒加载,避免 router → view → store → router 的循环依赖
const routes = [
  { path: '/', redirect: '/batches' },
  { path: '/batches/:sceneId?', component: () => import('./views/BatchView.vue') },
  { path: '/comparison', component: () => import('./views/ComparisonView.vue') },
  { path: '/comparison/:id', component: () => import('./views/ComparisonView.vue') },
  { path: '/settings', component: () => import('./components/ProjectSettings.vue') },
  { path: '/:pathMatch(.*)*', redirect: '/batches' },
]

export const router = createRouter({
  history: createWebHistory(),
  routes,
})
