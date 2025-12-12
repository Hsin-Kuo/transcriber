import { createRouter, createWebHistory } from 'vue-router'
import TranscriptionView from '../views/TranscriptionView.vue'
import AudioEditorView from '../views/AudioEditorView.vue'

const routes = [
  {
    path: '/',
    name: 'transcription',
    component: TranscriptionView,
    meta: { title: '轉錄服務' }
  },
  {
    path: '/editor',
    name: 'audioEditor',
    component: AudioEditorView,
    meta: { title: '音訊編輯' }
  }
]

const router = createRouter({
  history: createWebHistory(),
  routes
})

router.afterEach((to) => {
  document.title = to.meta.title || 'Whisper 逐字稿工具'
})

export default router
