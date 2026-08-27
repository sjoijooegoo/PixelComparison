import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

const backendTarget = process.env.PIXELCOMP_BACKEND_URL || 'http://127.0.0.1:8020'

export default defineConfig({
  plugins: [vue()],
  server: {
    host: '0.0.0.0',   // 监听所有网卡,局域网内可访问
    port: 5173,
    proxy: {
      '/api': backendTarget,
      '/images': backendTarget,
      '/thumb': backendTarget,
      '/gpm-assets': backendTarget,
    },
  },
})
