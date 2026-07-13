import { createApp } from 'vue'
import { createPinia } from 'pinia'
import ArcoVue from '@arco-design/web-vue'
import '@arco-design/web-vue/dist/arco.css'
import App from './App.vue'
import { router } from './router'
import { useStore } from './store'
import { logger } from './logger'
import './style.css'

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
