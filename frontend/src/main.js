import { createApp } from 'vue'
import { createPinia } from 'pinia'
import ArcoVue from '@arco-design/web-vue'
import '@arco-design/web-vue/dist/arco.css'
import App from './App.vue'
import { router } from './router'
import { logger } from './logger'
import './style.css'

logger.install()
logger.info('应用启动')

createApp(App).use(createPinia()).use(router).use(ArcoVue).mount('#app')
