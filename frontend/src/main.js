import { createApp } from 'vue'
import { createPinia } from 'pinia'
import ArcoVue from '@arco-design/web-vue'
import '@arco-design/web-vue/dist/arco.css'
import App from './App.vue'
import { router } from './router'
import { useStore } from './store'
import { logger } from './logger'
import { bootstrapApp } from './bootstrap'
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

const store = useStore(pinia)
bootstrapApp({ app, router, store, logger })
