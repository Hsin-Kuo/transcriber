import { createI18n } from 'vue-i18n'
import zhTW from './locales/zh-TW.json'
import en from './locales/en.json'
import { detectLanguage } from './utils/defaults'

const i18n = createI18n({
  legacy: false, // 使用 Composition API 模式
  locale: localStorage.getItem('locale') || detectLanguage(), // 優先 localStorage，fallback 偵測瀏覽器語言
  fallbackLocale: 'zh-TW', // 備用語言
  messages: {
    'zh-TW': zhTW,
    'en': en
  }
})

export default i18n
