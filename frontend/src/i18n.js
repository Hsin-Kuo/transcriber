import { createI18n } from 'vue-i18n'
import zhTW from './locales/zh-TW.json'
import en from './locales/en.json'

const i18n = createI18n({
  legacy: false, // 使用 Composition API 模式
  locale: localStorage.getItem('locale') || 'zh-TW', // 預設語言，從 localStorage 讀取
  fallbackLocale: 'zh-TW', // 備用語言
  messages: {
    'zh-TW': zhTW,
    'en': en
  }
})

export default i18n
