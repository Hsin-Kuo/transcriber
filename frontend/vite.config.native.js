import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// 配置用於連接原生後端（運行在 100.66.247.23:8000）
export default defineConfig({
  plugins: [vue()],
  server: {
    host: '0.0.0.0',
    port: 3000,
    proxy: {
      '/api': {
        // 連接到本地原生運行的後端
        target: 'http://192.168.0.59:8000',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, '')
      }
    }
  }
})
