<template>
  <div class="shared-view">
    <!-- 頂部標題列 -->
    <header class="shared-header">
      <div class="header-content">
        <h1 class="brand">Sound Lite</h1>
        <span class="shared-badge">{{ $t('shared.publicLink') }}</span>
      </div>
    </header>

    <!-- 載入中 -->
    <div v-if="loading" class="loading-state">
      <div class="spinner"></div>
      <p>{{ $t('shared.loading') }}</p>
    </div>

    <!-- 錯誤 -->
    <div v-else-if="error" class="error-state">
      <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
        <circle cx="12" cy="12" r="10"></circle>
        <line x1="15" y1="9" x2="9" y2="15"></line>
        <line x1="9" y1="9" x2="15" y2="15"></line>
      </svg>
      <p>{{ error }}</p>
    </div>

    <!-- 內容 -->
    <div v-else class="shared-content">
      <!-- 任務資訊 -->
      <div class="task-info">
        <h2 class="task-title">{{ taskData.display_name }}</h2>
        <div class="task-meta">
          <span v-if="taskData.created_at" class="meta-item">
            {{ formatDate(taskData.created_at) }}
          </span>
          <span v-if="taskData.duration_text" class="meta-item">
            {{ taskData.duration_text }}
          </span>
          <span v-if="taskData.text_length" class="meta-item">
            {{ taskData.text_length.toLocaleString() }} {{ $t('shared.chars') }}
          </span>
        </div>
      </div>

      <!-- 音檔播放器 -->
      <div v-if="taskData.has_audio" class="audio-section">
        <audio
          ref="audioEl"
          :src="audioUrl"
          controls
          preload="metadata"
          class="audio-player"
          @error="audioError = $t('shared.audioLoadError')"
        ></audio>
        <p v-if="audioError" class="audio-error">{{ audioError }}</p>
      </div>

      <!-- 逐字稿 -->
      <div class="transcript-section">
        <!-- 段落模式 -->
        <div v-if="taskData.task_type === 'paragraph'" class="transcript-text">
          {{ taskData.content }}
        </div>

        <!-- 字幕模式 -->
        <div v-else class="subtitle-list">
          <div
            v-for="(segment, index) in taskData.segments"
            :key="index"
            class="subtitle-row"
            @click="seekTo(segment.start)"
          >
            <span class="subtitle-time">{{ formatTime(segment.start) }}</span>
            <span v-if="segment.speaker" class="subtitle-speaker">
              {{ taskData.speaker_names?.[segment.speaker] || segment.speaker }}
            </span>
            <span class="subtitle-text">{{ segment.text }}</span>
          </div>
        </div>
      </div>
    </div>

    <!-- 底部 -->
    <footer class="shared-footer">
      <p>{{ $t('shared.poweredBy') }}</p>
    </footer>
  </div>
</template>

<script setup>
import { ref, onMounted, computed } from 'vue'
import { useRoute } from 'vue-router'
import { useI18n } from 'vue-i18n'
import axios from 'axios'
import { NEW_ENDPOINTS } from '../api/endpoints'

const { t } = useI18n()
const route = useRoute()

const loading = ref(true)
const error = ref(null)
const taskData = ref({})
const audioError = ref(null)
const audioEl = ref(null)

const API_BASE = import.meta.env.VITE_API_URL ?? ''

const audioUrl = computed(() => {
  if (!taskData.value.has_audio) return ''
  return `${API_BASE}${NEW_ENDPOINTS.shared.audio(route.params.token)}`
})

onMounted(async () => {
  try {
    const response = await axios.get(`${API_BASE}${NEW_ENDPOINTS.shared.get(route.params.token)}`)
    taskData.value = response.data
  } catch (err) {
    if (err.response?.status === 404) {
      error.value = t('shared.notFound')
    } else {
      error.value = t('shared.loadError')
    }
  } finally {
    loading.value = false
  }
})

function formatDate(dateStr) {
  if (!dateStr) return ''
  const d = new Date(dateStr)
  return d.toLocaleDateString(undefined, {
    year: 'numeric', month: 'short', day: 'numeric',
    hour: '2-digit', minute: '2-digit'
  })
}

function formatTime(seconds) {
  if (seconds == null) return ''
  const m = Math.floor(seconds / 60)
  const s = Math.floor(seconds % 60)
  return `${m}:${s.toString().padStart(2, '0')}`
}

function seekTo(time) {
  if (audioEl.value) {
    audioEl.value.currentTime = time
    audioEl.value.play()
  }
}
</script>

<style scoped>
.shared-view {
  min-height: 100vh;
  background: #fafaf9;
  color: #1c1917;
  display: flex;
  flex-direction: column;
}

.shared-header {
  background: white;
  border-bottom: 1px solid #e7e5e4;
  padding: 12px 24px;
  position: sticky;
  top: 0;
  z-index: 10;
}

.header-content {
  max-width: 800px;
  margin: 0 auto;
  display: flex;
  align-items: center;
  gap: 12px;
}

.brand {
  font-size: 18px;
  font-weight: 600;
  color: #78716c;
  margin: 0;
}

.shared-badge {
  font-size: 11px;
  background: #f5f5f4;
  color: #78716c;
  padding: 2px 8px;
  border-radius: 10px;
  border: 1px solid #e7e5e4;
}

.loading-state,
.error-state {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 16px;
  color: #78716c;
}

.error-state svg {
  color: #a8a29e;
}

.spinner {
  width: 32px;
  height: 32px;
  border: 3px solid #e7e5e4;
  border-top-color: #78716c;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

.shared-content {
  max-width: 800px;
  margin: 0 auto;
  padding: 32px 24px;
  width: 100%;
  flex: 1;
}

.task-info {
  margin-bottom: 24px;
}

.task-title {
  font-size: 24px;
  font-weight: 600;
  margin: 0 0 8px 0;
  color: #1c1917;
}

.task-meta {
  display: flex;
  gap: 16px;
  flex-wrap: wrap;
  color: #78716c;
  font-size: 13px;
}

.meta-item {
  display: flex;
  align-items: center;
}

.audio-section {
  margin-bottom: 24px;
}

.audio-player {
  width: 100%;
  border-radius: 8px;
}

.audio-error {
  color: #dc2626;
  font-size: 13px;
  margin-top: 8px;
}

.transcript-section {
  background: white;
  border: 1px solid #e7e5e4;
  border-radius: 12px;
  padding: 24px;
}

.transcript-text {
  white-space: pre-wrap;
  line-height: 1.8;
  font-size: 15px;
  color: #292524;
}

.subtitle-list {
  display: flex;
  flex-direction: column;
}

.subtitle-row {
  display: flex;
  gap: 12px;
  padding: 8px 4px;
  border-bottom: 1px solid #f5f5f4;
  cursor: pointer;
  transition: background 0.15s;
}

.subtitle-row:hover {
  background: #fafaf9;
}

.subtitle-row:last-child {
  border-bottom: none;
}

.subtitle-time {
  font-size: 12px;
  color: #a8a29e;
  font-family: monospace;
  min-width: 48px;
  flex-shrink: 0;
  padding-top: 2px;
}

.subtitle-speaker {
  font-size: 13px;
  font-weight: 500;
  color: #78716c;
  min-width: 60px;
  flex-shrink: 0;
}

.subtitle-text {
  font-size: 15px;
  color: #292524;
  line-height: 1.6;
}

.shared-footer {
  text-align: center;
  padding: 24px;
  color: #a8a29e;
  font-size: 12px;
  border-top: 1px solid #e7e5e4;
}

.shared-footer p {
  margin: 0;
}

@media (max-width: 768px) {
  .shared-content {
    padding: 16px;
  }

  .task-title {
    font-size: 20px;
  }

  .transcript-section {
    padding: 16px;
  }

  .subtitle-row {
    flex-wrap: wrap;
    gap: 4px;
  }

  .subtitle-time {
    min-width: auto;
  }
}
</style>
