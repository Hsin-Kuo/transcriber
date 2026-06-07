import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// 從環境變數讀取後端 API URL，預設為 localhost:8000
const API_TARGET = process.env.VITE_API_TARGET || 'http://localhost:8000'

export default defineConfig(({ command }) => ({
  plugins: [vue()],
  // 僅 production build 清掉 console / debugger，避免洩漏內部邏輯與註解；
  // dev（command==='serve'）保留 console 方便除錯
  esbuild: command === 'build' ? { drop: ['console', 'debugger'] } : {},
  server: {
    host: '0.0.0.0',
    port: 3000,
    allowedHosts: 'all',
    proxy: {
      '/api': {
        target: API_TARGET,
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, '')
      }
    }
  }
}))
