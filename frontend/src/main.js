import { createApp } from 'vue'
import { createPinia } from 'pinia'
import ArcoVue from '@arco-design/web-vue'
import '@arco-design/web-vue/dist/arco.css'
import App from './App.vue'
import { router } from './router'
import { useStore } from './store'
import { logger } from './logger'
import './style.css'

// 列表图自行决定初始横向位置；禁止浏览器在 F5 后恢复刷新前的滚动位置，
// 否则原生恢复可能晚于组件挂载，并覆盖“默认定位到最新批次”的结果。
if ('scrollRestoration' in window.history) {
  window.history.scrollRestoration = 'manual'
}

logger.install()
logger.info('应用启动')

const app = createApp(App)
const pinia = createPinia()
app.use(pinia).use(router).use(ArcoVue)

async function bootstrap() {
  // 等初始深链解析完成后再初始化 store，避免 App / BatchView / BatchTable
  // 分别用不同筛选并发拉批次，响应乱序后互相覆盖。
  try {
    await router.isReady()
    const store = useStore(pinia)
    await store.init(router.currentRoute.value.params.sceneId)
  } catch (error) {
    // 保持原有容错：初始化失败仍挂载界面，用户可通过刷新按钮重试数据请求。
    logger.error('应用初始化失败', error)
  }

  app.mount('#app')
}

bootstrap()
