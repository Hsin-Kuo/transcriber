import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import router from './router'
import i18n from './i18n'
import './assets/colors.css'      // 色票定義 (palette)
import './assets/theme-light.css' // 淺色主題 (預設)
import './assets/theme-dark.css'  // 深色主題
import './style.css'

const app = createApp(App)
const pinia = createPinia()

app.use(pinia)
app.use(router)
app.use(i18n)
app.mount('#app')
