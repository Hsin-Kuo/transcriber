<template>
  <div class="shared-view">
    <!-- 頂部標題列 -->
    <header class="shared-header">
      <div class="header-content">
        <a href="https://soundlite.app" class="brand">Sound Lite</a>
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

      <!-- AI 摘要 -->
      <div v-if="taskData.summary" class="summary-section">
        <div class="summary-header" @click="summaryExpanded = !summaryExpanded">
          <div class="summary-header-left">
            <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <path d="M12 3c.132 0 .263 0 .393 0a7.5 7.5 0 0 0 7.92 12.446a9 9 0 1 1 -8.313 -12.454z" />
              <path d="M17 4a2 2 0 0 0 2 2a2 2 0 0 0 -2 2a2 2 0 0 0 -2 -2a2 2 0 0 0 2 -2" />
              <path d="M19 11h2m-1 -1v2" />
            </svg>
            <span>{{ $t('shared.aiSummary') }}</span>
          </div>
          <svg
            class="expand-icon"
            :class="{ expanded: summaryExpanded }"
            width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <polyline points="6 9 12 15 18 9"></polyline>
          </svg>
        </div>

        <div v-show="summaryExpanded" class="summary-body">
          <!-- Meta -->
          <div v-if="taskData.summary.content.meta" class="summary-meta">
            <span class="summary-type-badge">{{ taskData.summary.content.meta.type }}</span>
            <span v-if="taskData.summary.content.meta.detected_topic" class="summary-topic">
              {{ taskData.summary.content.meta.detected_topic }}
            </span>
          </div>

          <!-- 摘要 -->
          <div v-if="taskData.summary.content.summary" class="summary-block">
            <h4>{{ $t('shared.summaryTitle') }}</h4>
            <p>{{ taskData.summary.content.summary }}</p>
          </div>

          <!-- 重點 -->
          <div v-if="taskData.summary.content.key_points?.length" class="summary-block">
            <h4>{{ $t('shared.keyPoints') }}</h4>
            <ul>
              <li v-for="(point, i) in taskData.summary.content.key_points" :key="i">{{ point }}</li>
            </ul>
          </div>

          <!-- 段落 -->
          <div v-if="taskData.summary.content.segments?.length" class="summary-block">
            <h4>{{ $t('shared.contentSegments') }}</h4>
            <div v-for="(seg, i) in taskData.summary.content.segments" :key="i" class="summary-segment">
              <h5>{{ seg.topic }}</h5>
              <p>{{ seg.content }}</p>
              <div v-if="seg.keywords?.length" class="summary-keywords">
                <span v-for="(kw, j) in seg.keywords" :key="j" class="keyword-tag">{{ kw }}</span>
              </div>
            </div>
          </div>

          <!-- 待辦事項 -->
          <div v-if="taskData.summary.content.action_items?.length" class="summary-block">
            <h4>{{ $t('shared.actionItems') }}</h4>
            <div v-for="(item, i) in taskData.summary.content.action_items" :key="i" class="action-item">
              <span class="action-task">{{ item.task }}</span>
              <span v-if="item.owner" class="action-owner">{{ item.owner }}</span>
              <span v-if="item.deadline" class="action-deadline">{{ item.deadline }}</span>
            </div>
          </div>
        </div>
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
const summaryExpanded = ref(false)

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
  text-decoration: none;
  transition: color 0.15s;
}

.brand:hover {
  color: #44403c;
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

/* AI 摘要 */
.summary-section {
  background: white;
  border: 1px solid #e7e5e4;
  border-radius: 12px;
  margin-bottom: 16px;
  overflow: hidden;
}

.summary-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 20px;
  cursor: pointer;
  user-select: none;
  transition: background 0.15s;
}

.summary-header:hover {
  background: #fafaf9;
}

.summary-header-left {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 14px;
  font-weight: 600;
  color: #44403c;
}

.summary-header-left svg {
  color: #a78bfa;
}

.expand-icon {
  color: #a8a29e;
  transition: transform 0.2s;
}

.expand-icon.expanded {
  transform: rotate(180deg);
}

.summary-body {
  padding: 0 20px 20px;
  border-top: 1px solid #f5f5f4;
}

.summary-meta {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 16px;
  margin-bottom: 12px;
}

.summary-type-badge {
  font-size: 11px;
  font-weight: 500;
  padding: 2px 10px;
  border-radius: 10px;
  background: #f3e8ff;
  color: #7c3aed;
}

.summary-topic {
  font-size: 15px;
  font-weight: 600;
  color: #1c1917;
}

.summary-block {
  margin-top: 16px;
}

.summary-block h4 {
  font-size: 13px;
  font-weight: 600;
  color: #78716c;
  text-transform: uppercase;
  letter-spacing: 0.3px;
  margin: 0 0 8px 0;
}

.summary-block p {
  font-size: 14px;
  line-height: 1.7;
  color: #292524;
  margin: 0;
}

.summary-block ul {
  margin: 0;
  padding-left: 20px;
}

.summary-block li {
  font-size: 14px;
  line-height: 1.7;
  color: #292524;
  margin-bottom: 4px;
}

.summary-segment {
  padding: 12px;
  background: #fafaf9;
  border-radius: 8px;
  margin-bottom: 8px;
}

.summary-segment h5 {
  font-size: 14px;
  font-weight: 600;
  color: #1c1917;
  margin: 0 0 6px 0;
}

.summary-segment p {
  font-size: 13px;
  line-height: 1.6;
  color: #44403c;
  margin: 0;
}

.summary-keywords {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 8px;
}

.keyword-tag {
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 6px;
  background: #f5f5f4;
  color: #78716c;
}

.action-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 8px 0;
  border-bottom: 1px solid #f5f5f4;
  font-size: 14px;
}

.action-item:last-child {
  border-bottom: none;
}

.action-task {
  flex: 1;
  color: #292524;
}

.action-owner,
.action-deadline {
  font-size: 12px;
  color: #78716c;
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
