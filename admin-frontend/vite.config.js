import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// 從環境變數讀取後端 API URL，預設為 localhost:8000
// Docker 環境會使用 host.docker.internal:8000
const API_TARGET = process.env.VITE_API_TARGET || 'http://100.66.247.23:8000'

export default defineConfig({
  plugins: [vue()],
  server: {
    host: '0.0.0.0',
    port: 3001,  // Admin 後台使用 port 3001
    proxy: {
      '/api': {
        target: API_TARGET,
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, '')
      }
    }
  }
})
