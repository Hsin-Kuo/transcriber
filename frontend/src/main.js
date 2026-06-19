import { createApp } from 'vue'
import { createPinia } from 'pinia'
import * as Sentry from '@sentry/vue'
import App from './App.vue'
import router from './router'
import i18n from './i18n'
import './assets/colors.css'      // 色票定義 (palette)
import './assets/theme-light.css' // 淺色主題 (預設)
import './assets/theme-dark.css'  // 深色主題
import './style.css'

// Staging 用灰色 favicon，方便一眼和 prod 區分。
// 以 build-time 的 VITE_SENTRY_ENVIRONMENT 為主、hostname 為 fallback。
const isStaging =
  import.meta.env.VITE_SENTRY_ENVIRONMENT === 'staging' ||
  window.location.hostname.startsWith('staging.')
if (isStaging) {
  document
    .querySelectorAll('link[rel~="icon"], link[rel="apple-touch-icon"]')
    .forEach((el) => el.remove())
  const link = document.createElement('link')
  link.rel = 'icon'
  link.type = 'image/svg+xml'
  link.href = '/favicon-staging.svg'
  document.head.appendChild(link)
}

const app = createApp(App)
const pinia = createPinia()

app.use(pinia)
app.use(router)
app.use(i18n)

// Sentry 必須在 router 註冊後、mount 前初始化
// 未設定 VITE_SENTRY_DSN 時 no-op，本地開發不會送資料
if (import.meta.env.VITE_SENTRY_DSN) {
  Sentry.init({
    app,
    dsn: import.meta.env.VITE_SENTRY_DSN,
    environment: import.meta.env.VITE_SENTRY_ENVIRONMENT || import.meta.env.MODE,
    release: import.meta.env.VITE_SENTRY_RELEASE || undefined,
    integrations: [Sentry.browserTracingIntegration({ router })],
    tracesSampleRate: parseFloat(import.meta.env.VITE_SENTRY_TRACES_SAMPLE_RATE || '0.1'),
    sendDefaultPii: false,
  })
  // 跟後端 set_tag('component', ...) 對齊，方便 Sentry 跨服務篩選
  Sentry.setTag('component', 'frontend-user')
}

app.mount('#app')
