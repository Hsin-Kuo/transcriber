<template>
  <div class="transcript-detail-container">
    <!-- 雙欄佈局 -->
    <div class="transcript-layout">
      <!-- 左側控制面板 -->
      <div class="left-panel card">
        <!-- 返回按鈕 -->
        <button @click="goBack" class="btn-back-icon" title="返回">
          <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M19 12H5M12 19l-7-7 7-7"/>
          </svg>
        </button>

        <!-- 任務名稱 -->
        <div class="task-name-section">
          <label class="section-label">任務名稱</label>
          <input
            v-if="isEditingTitle"
            ref="titleInput"
            v-model="editingTaskName"
            type="text"
            class="title-input"
            @blur="saveTaskName"
            @keyup.enter="saveTaskName"
            @keyup.esc="cancelTitleEdit"
          />
          <h2 v-else @click="startTitleEdit" class="editable-title" title="點擊編輯名稱">
            {{ currentTranscript.custom_name || currentTranscript.filename || '逐字稿' }}
          </h2>
        </div>

        <!-- 元數據 -->
        <div class="metadata-section">
          <div v-if="currentTranscript.created_at" class="meta-item">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <rect x="3" y="4" width="18" height="18" rx="2" ry="2"></rect>
              <line x1="16" y1="2" x2="16" y2="6"></line>
              <line x1="8" y1="2" x2="8" y2="6"></line>
              <line x1="3" y1="10" x2="21" y2="10"></line>
            </svg>
            {{ formatDate(currentTranscript.created_at) }}
          </div>
          <div v-if="currentTranscript.text_length" class="meta-item">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path>
              <polyline points="14 2 14 8 20 8"></polyline>
            </svg>
            {{ currentTranscript.text_length }} 字
          </div>
          <div v-if="currentTranscript.duration_text" class="meta-item">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <circle cx="12" cy="12" r="10"></circle>
              <polyline points="12 6 12 12 16 14"></polyline>
            </svg>
            {{ currentTranscript.duration_text }}
          </div>
        </div>

        <!-- 按鈕組 -->
        <div class="action-buttons">
          <button v-if="!isEditing" @click="startEditing" class="btn btn-action">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"></path>
              <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"></path>
            </svg>
            <span>編輯</span>
          </button>
          <button v-else @click="saveEditing" class="btn btn-action">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <polyline points="20 6 9 17 4 12"></polyline>
            </svg>
            <span>儲存</span>
          </button>
          <button v-if="isEditing" @click="cancelEditing" class="btn btn-action">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <line x1="18" y1="6" x2="6" y2="18"></line>
              <line x1="6" y1="6" x2="18" y2="18"></line>
            </svg>
            <span>取消</span>
          </button>
          <button v-if="!isEditing" @click="downloadTranscript" class="btn btn-action">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path>
              <polyline points="7 10 12 15 17 10"></polyline>
              <line x1="12" y1="15" x2="12" y2="3"></line>
            </svg>
            <span>下載</span>
          </button>
        </div>

      <!-- 音訊播放器 -->
      <div v-if="currentTranscript.hasAudio" class="audio-player-container">
        <audio
          ref="audioElement"
          preload="metadata"
          :src="getAudioUrl(currentTranscript.task_id)"
          @error="handleAudioError"
          @loadedmetadata="handleAudioLoaded"
          @play="isPlaying = true"
          @pause="isPlaying = false"
          @ended="isPlaying = false"
          @timeupdate="updateProgress"
          @durationchange="updateDuration"
          @volumechange="updateVolume"
          @ratechange="updatePlaybackRate"
        >
          您的瀏覽器不支援音訊播放。
        </audio>

        <div v-if="audioError" class="audio-error">
          ⚠️ {{ audioError }}
        </div>

        <div class="custom-audio-player circular-player">
          <!-- 圓形進度條 (1/3 圓弧在上方) -->
          <div class="circular-progress-container">
            <svg
              class="progress-arc"
              viewBox="0 0 200 140"
              @mousedown="startDragArc"
              @mousemove="dragArc"
              @mouseup="stopDragArc"
              @mouseleave="stopDragArc"
            >
              <!-- 背景弧線 -->
              <path
                class="arc-background"
                :d="arcPath"
                fill="none"
                stroke-width="5"
                stroke-linecap="round"
              />
              <!-- 進度弧線 -->
              <path
                class="arc-progress"
                :d="arcPath"
                fill="none"
                stroke-width="5"
                stroke-linecap="round"
                :stroke-dasharray="arcLength"
                :stroke-dashoffset="arcLength - (arcLength * displayProgress / 100)"
              />
              <!-- 進度圓點 -->
              <circle
                class="arc-thumb"
                :cx="thumbPosition.x"
                :cy="thumbPosition.y"
                r="5"
              />
            </svg>
          </div>

          <!-- 中央控制區 -->
          <div class="circular-controls-center">
            <!-- 快退按鈕 -->
            <button class="audio-control-btn audio-skip-btn skip-backward" @click="skipBackward" title="快退10秒">
              <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
                <path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/>
                <path d="M3 3v5h5"/>
              </svg>
              <span class="control-label">10</span>
            </button>

            <!-- 播放/暫停按鈕 -->
            <button class="audio-control-btn audio-play-btn" @click="togglePlayPause" :title="isPlaying ? '暫停' : '播放'">
              <svg v-if="!isPlaying" width="30" height="30" viewBox="0 0 24 24" fill="currentColor">
                <path d="M8 5v14l11-7z"/>
              </svg>
              <svg v-else width="30" height="30" viewBox="0 0 24 24" fill="currentColor">
                <path d="M6 4h4v16H6V4zm8 0h4v16h-4V4z"/>
              </svg>
            </button>

            <!-- 快進按鈕 -->
            <button class="audio-control-btn audio-skip-btn skip-forward" @click="skipForward" title="快進10秒">
              <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
                <path d="M21 12a9 9 0 1 1-9-9c2.52 0 4.93 1 6.74 2.74L21 8"/>
                <path d="M21 3v5h-5"/>
              </svg>
              <span class="control-label">10</span>
            </button>
          </div>

          <!-- 時間顯示 -->
          <div class="time-display-center">
            {{ formatTime(displayTime) }} / {{ formatTime(duration) }}
          </div>

          <!-- 音量和控制區 -->
          <div class="volume-and-controls">
            <!-- 左側：快捷鍵說明 -->
            <div class="keyboard-shortcuts-info">
              <button class="audio-control-btn info-btn" title="鍵盤快捷鍵">
                <svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor">
                  <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm1 15h-2v-6h2v6zm0-8h-2V7h2v2z"/>
                </svg>
              </button>
              <div class="shortcuts-tooltip">
                <div class="shortcuts-title">音檔控制快捷鍵</div>
                <div class="shortcuts-section">
                  <div class="shortcuts-section-title">通用（編輯時可用）</div>
                  <div class="shortcut-item">
                    <kbd>Alt</kbd> + <kbd>K</kbd>
                    <span>播放/暫停</span>
                  </div>
                  <div class="shortcut-item">
                    <kbd>Alt</kbd> + <kbd>J</kbd> / <kbd>←</kbd>
                    <span>快退 10 秒</span>
                  </div>
                  <div class="shortcut-item">
                    <kbd>Alt</kbd> + <kbd>L</kbd> / <kbd>→</kbd>
                    <span>快進 10 秒</span>
                  </div>
                  <div class="shortcut-item">
                    <kbd>Alt</kbd> + <kbd>,</kbd>
                    <span>快退 5 秒</span>
                  </div>
                  <div class="shortcut-item">
                    <kbd>Alt</kbd> + <kbd>.</kbd>
                    <span>快進 5 秒</span>
                  </div>
                  <div class="shortcut-item">
                    <kbd>Alt</kbd> + <kbd>M</kbd>
                    <span>靜音/取消靜音</span>
                  </div>
                </div>
                <div class="shortcuts-section">
                  <div class="shortcuts-section-title">非編輯模式</div>
                  <div class="shortcut-item">
                    <kbd>Space</kbd>
                    <span>播放/暫停</span>
                  </div>
                  <div class="shortcut-item">
                    <kbd>←</kbd>
                    <span>快退 10 秒</span>
                  </div>
                  <div class="shortcut-item">
                    <kbd>→</kbd>
                    <span>快進 10 秒</span>
                  </div>
                </div>
              </div>
            </div>

            <!-- 中間：音量控制 -->
            <div class="volume-control-center">
              <!-- 靜音按鈕（音量條開頭） -->
              <button class="audio-control-btn mute-btn-volume" @click="toggleMute" :title="isMuted ? '取消靜音' : '靜音'">
                <svg v-if="!isMuted && volume > 0.5" width="24" height="24" viewBox="0 0 24 24" fill="currentColor">
                  <path d="M3 9v6h4l5 5V4L7 9H3zm13.5 3c0-1.77-1.02-3.29-2.5-4.03v8.05c1.48-.73 2.5-2.25 2.5-4.02zM14 3.23v2.06c2.89.86 5 3.54 5 6.71s-2.11 5.85-5 6.71v2.06c4.01-.91 7-4.49 7-8.77s-2.99-7.86-7-8.77z"/>
                </svg>
                <svg v-else-if="!isMuted && volume > 0" width="24" height="24" viewBox="0 0 24 24" fill="currentColor">
                  <path d="M3 9v6h4l5 5V4L7 9H3zm13.5 3c0-1.77-1.02-3.29-2.5-4.03v8.05c1.48-.73 2.5-2.25 2.5-4.02z"/>
                </svg>
                <svg v-else width="24" height="24" viewBox="0 0 24 24" fill="currentColor">
                  <path d="M16.5 12c0-1.77-1.02-3.29-2.5-4.03v2.21l2.45 2.45c.03-.2.05-.41.05-.63zm2.5 0c0 .94-.2 1.82-.54 2.64l1.51 1.51C20.63 14.91 21 13.5 21 12c0-4.28-2.99-7.86-7-8.77v2.06c2.89.86 5 3.54 5 6.71zM4.27 3L3 4.27 7.73 9H3v6h4l5 5v-6.73l4.25 4.25c-.67.52-1.42.93-2.25 1.18v2.06c1.38-.31 2.63-.95 3.69-1.81L19.73 21 21 19.73l-9-9L4.27 3zM12 4L9.91 6.09 12 8.18V4z"/>
                </svg>
              </button>

              <input
                type="range"
                class="volume-slider-horizontal"
                min="0"
                max="100"
                :value="volume * 100"
                @input="setVolume"
              />
            </div>

            <!-- 右側：播放速度 -->
            <div class="speed-control">
              <button class="audio-control-btn speed-btn" :title="`播放速度: ${playbackRate}x`">
                <span class="speed-label">{{ playbackRate }}x</span>
              </button>
              <div class="speed-dropdown">
                <button
                  v-for="rate in [0.5, 0.75, 1, 1.25, 1.5, 2]"
                  :key="rate"
                  class="speed-option"
                  :class="{ active: playbackRate === rate }"
                  @click="setPlaybackRate(rate)"
                >
                  {{ rate }}x
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>
      </div>

      <!-- 右側文字區域 -->
      <div class="right-panel card">
        <!-- 逐字稿內容區域 -->
        <div class="transcript-content-wrapper">
          <div class="transcript-content-area">
          <div v-if="loadingTranscript" class="loading-state">
            <div class="spinner"></div>
            <p>載入逐字稿中...</p>
          </div>
          <div v-else-if="transcriptError" class="error-state">
            <p>❌ {{ transcriptError }}</p>
          </div>
          <div
            v-else
            class="textarea-wrapper"
            :class="{ 'show-reference-line': currentTranscript.hasAudio && timecodeMarkers.length > 0 }"
          >
            <textarea
              v-model="currentTranscript.content"
              class="transcript-textarea"
              :readonly="!isEditing"
              :class="{ 'editing': isEditing }"
              ref="textarea"
              @scroll="syncScroll"
            ></textarea>
            <!-- 固定顯示的當前 Timecode -->
            <div
              v-if="activeTimecodeIndex >= 0 && timecodeMarkers.length > 0 && currentTranscript.hasAudio"
              class="timecode-fixed-display"
              @click="seekToTime(timecodeMarkers[activeTimecodeIndex].time)"
              :title="`點擊跳轉到 ${timecodeMarkers[activeTimecodeIndex].label}`"
            >
              <div class="timecode-label">{{ timecodeMarkers[activeTimecodeIndex].label }}</div>
            </div>
          </div>
        </div>
        </div>

        <!-- 取代工具列 -->
        <div v-if="isEditing && !loadingTranscript && !transcriptError" class="replace-toolbar">
          <input
            v-model="findText"
            type="text"
            placeholder="尋找"
            class="replace-input"
            @keydown.enter.prevent="replaceAll"
          />
          <input
            v-model="replaceText"
            type="text"
            placeholder="取代為"
            class="replace-input"
            @keydown.enter.prevent="replaceAll"
          />
          <button
            class="btn btn-primary"
            @click="replaceAll"
            :disabled="!findText"
          >
            取代全部
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted, nextTick, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import api, { API_BASE, TokenManager } from '../utils/api'
import { NEW_ENDPOINTS } from '../api/endpoints'

const route = useRoute()
const router = useRouter()

// 基本狀態
const currentTranscript = ref({})
const loadingTranscript = ref(false)
const transcriptError = ref(null)
const isEditing = ref(false)
const isEditingTitle = ref(false)
const editingTaskName = ref('')
const findText = ref('')
const replaceText = ref('')
const originalContent = ref('')

// 音訊播放器狀態
const audioElement = ref(null)
const audioError = ref(null)
const isPlaying = ref(false)
const progressBar = ref(null)
const currentTime = ref(0)
const duration = ref(0)
const progressPercent = ref(0)
const volume = ref(1)
const isMuted = ref(false)
const playbackRate = ref(1)
const isDraggingArc = ref(false)
const draggingPercent = ref(0)
let rafId = null

// 時間碼標記
const segments = ref([])
const timecodeMarkers = ref([])
const activeTimecodeIndex = ref(-1)
const textarea = ref(null)
const titleInput = ref(null)

// 圓弧進度條計算
const arcPath = computed(() => {
  // 1/3 圓 = 120 度
  // 從 210 度開始到 330 度（上方居中）
  const centerX = 100
  const centerY = 100
  const radius = 90  // 增大半徑從 80 到 90
  const startAngle = 210 * (Math.PI / 180)
  const endAngle = 330 * (Math.PI / 180)

  const startX = centerX + radius * Math.cos(startAngle)
  const startY = centerY + radius * Math.sin(startAngle)
  const endX = centerX + radius * Math.cos(endAngle)
  const endY = centerY + radius * Math.sin(endAngle)

  return `M ${startX} ${startY} A ${radius} ${radius} 0 0 1 ${endX} ${endY}`
})

const arcLength = computed(() => {
  // 1/3 圓的弧長 = 2πr × (120/360) = 2πr / 3
  const radius = 90  // 增大半徑從 80 到 90
  return (2 * Math.PI * radius) / 3
})

const thumbPosition = computed(() => {
  // 根據進度百分比計算拇指位置
  const centerX = 100
  const centerY = 100
  const radius = 90  // 增大半徑從 80 到 90
  const startAngle = 210 * (Math.PI / 180)
  const totalAngle = 120 * (Math.PI / 180) // 120度的弧
  // 拖曳時使用 draggingPercent，否則使用實際進度
  const percent = isDraggingArc.value ? draggingPercent.value : progressPercent.value
  const currentAngle = startAngle + (totalAngle * percent / 100)

  return {
    x: centerX + radius * Math.cos(currentAngle),
    y: centerY + radius * Math.sin(currentAngle)
  }
})

// 顯示的進度（拖曳時使用拖曳進度，否則使用實際進度）
const displayProgress = computed(() => {
  return isDraggingArc.value ? draggingPercent.value : progressPercent.value
})

// 顯示的時間（拖曳時即時計算，否則使用實際時間）
const displayTime = computed(() => {
  if (isDraggingArc.value) {
    // 拖曳時根據 draggingPercent 計算時間
    return (draggingPercent.value / 100) * duration.value
  }
  return currentTime.value
})

// 載入逐字稿的可重用函數
async function loadTranscript(taskId) {
  if (!taskId) {
    transcriptError.value = '無效的任務 ID'
    return
  }

  loadingTranscript.value = true
  transcriptError.value = null
  isEditing.value = false  // 重置編輯狀態

  try {
    const taskResponse = await api.get(NEW_ENDPOINTS.tasks.list)
    const task = taskResponse.data.tasks?.find(t => (t._id || t.task_id) === taskId)

    if (!task) {
      transcriptError.value = '找不到該任務'
      return
    }

    currentTranscript.value = {
      task_id: task.task_id,
      filename: task.file?.filename || task.filename,
      custom_name: task.custom_name,
      created_at: task.timestamps?.completed_at || task.timestamps?.created_at,
      text_length: task.result?.text_length || task.text_length,
      duration_text: task.duration_text,
      hasAudio: !!(task.result?.audio_file || task.audio_file),
      content: ''
    }

    // 並行獲取逐字稿和 segments
    const [transcriptResponse, segmentsResponse] = await Promise.all([
      api.get(NEW_ENDPOINTS.transcriptions.download(taskId), {
        responseType: 'text'
      }),
      api.get(NEW_ENDPOINTS.transcriptions.segments(taskId)).catch(err => {
        console.log('無法獲取 segments:', err)
        return null
      })
    ])

    currentTranscript.value.content = transcriptResponse.data
    originalContent.value = transcriptResponse.data

    // 如果有 segments 數據，生成 timecode markers
    if (segmentsResponse && segmentsResponse.data.segments) {
      segments.value = segmentsResponse.data.segments
      timecodeMarkers.value = generateTimecodeMarkers(segments.value)
      // 初始化 activeTimecodeIndex
      if (timecodeMarkers.value.length > 0) {
        activeTimecodeIndex.value = 0
      }
    }

    loadingTranscript.value = false

    // 不需要初始化 scrollHeight，保持 textarea 固定高度可滾動
    nextTick(() => {
      // 確保 textarea 可以滾動
      if (textarea.value && timecodeMarkers.value.length > 0) {
        activeTimecodeIndex.value = 0
      }
    })
  } catch (error) {
    console.error('載入逐字稿失敗:', error)
    transcriptError.value = '載入逐字稿失敗'
    loadingTranscript.value = false
  }
}

// 初始載入
onMounted(() => {
  loadTranscript(route.params.taskId)
})

// 監聽路由參數變化
watch(() => route.params.taskId, (newTaskId) => {
  if (newTaskId) {
    loadTranscript(newTaskId)
  }
})

// 鍵盤快捷鍵
onMounted(() => {
  window.addEventListener('keydown', handleKeyboardShortcuts)
})

onUnmounted(() => {
  window.removeEventListener('keydown', handleKeyboardShortcuts)
})

// 格式化日期
function formatDate(dateString) {
  if (!dateString) return ''
  try {
    const date = new Date(dateString)
    return date.toLocaleString('zh-TW', {
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit'
    })
  } catch {
    return dateString
  }
}

// 標題編輯
function startTitleEdit() {
  isEditingTitle.value = true
  editingTaskName.value = currentTranscript.value.custom_name || currentTranscript.value.filename || ''
  nextTick(() => {
    if (titleInput.value) {
      titleInput.value.focus()
      titleInput.value.select()
    }
  })
}

async function saveTaskName() {
  const newName = editingTaskName.value.trim()
  if (newName && newName !== currentTranscript.value.custom_name) {
    try {
      await api.put(NEW_ENDPOINTS.transcriptions.updateMetadata(currentTranscript.value.task_id), {
        title: newName
      })
      currentTranscript.value.custom_name = newName
    } catch (error) {
      console.error('更新任務名稱失敗:', error)
      alert('更新任務名稱失敗')
    }
  }
  isEditingTitle.value = false
}

function cancelTitleEdit() {
  isEditingTitle.value = false
  editingTaskName.value = ''
}

// 編輯功能
function startEditing() {
  isEditing.value = true
  originalContent.value = currentTranscript.value.content
}

async function saveEditing() {
  if (currentTranscript.value.content === originalContent.value) {
    isEditing.value = false
    return
  }

  try {
    await api.put(NEW_ENDPOINTS.transcriptions.updateContent(currentTranscript.value.task_id), {
      text: currentTranscript.value.content
    })
    originalContent.value = currentTranscript.value.content
    isEditing.value = false
    alert('儲存成功')
  } catch (error) {
    console.error('儲存失敗:', error)
    alert('儲存失敗')
  }
}

function cancelEditing() {
  currentTranscript.value.content = originalContent.value
  isEditing.value = false
  findText.value = ''
  replaceText.value = ''
}

function replaceAll() {
  if (!findText.value) return
  const regex = new RegExp(findText.value, 'g')
  currentTranscript.value.content = currentTranscript.value.content.replace(regex, replaceText.value)
}

// 下載
function downloadTranscript() {
  const blob = new Blob([currentTranscript.value.content], { type: 'text/plain' })
  const url = window.URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = `${currentTranscript.value.custom_name || currentTranscript.value.filename || 'transcript'}.txt`
  document.body.appendChild(link)
  link.click()
  link.remove()
  window.URL.revokeObjectURL(url)
}

// 返回
function goBack() {
  router.back()
}

// 音訊播放器功能
function getAudioUrl(taskId) {
  const token = TokenManager.getAccessToken()
  if (!token) return ''
  return `${API_BASE}${NEW_ENDPOINTS.transcriptions.audio(taskId)}?token=${encodeURIComponent(token)}`
}

function handleAudioLoaded() {
  audioError.value = null
}

function handleAudioError(event) {
  const audio = event.target
  if (audio.error) {
    switch (audio.error.code) {
      case audio.error.MEDIA_ERR_NETWORK:
        audioError.value = '網路錯誤，無法載入音檔'
        break
      case audio.error.MEDIA_ERR_DECODE:
        audioError.value = '音檔格式錯誤或損壞'
        break
      case audio.error.MEDIA_ERR_SRC_NOT_SUPPORTED:
        audioError.value = '不支援的音檔格式或音檔不存在'
        break
      default:
        audioError.value = '音檔載入失敗'
    }
  }
}

function togglePlayPause() {
  if (!audioElement.value) return
  if (audioElement.value.paused) {
    audioElement.value.play().catch(err => {
      console.error('播放失敗:', err)
      audioError.value = '播放失敗'
    })
  } else {
    audioElement.value.pause()
  }
}

function skipBackward() {
  if (audioElement.value) {
    audioElement.value.currentTime = Math.max(0, audioElement.value.currentTime - 10)
  }
}

function skipForward() {
  if (audioElement.value) {
    audioElement.value.currentTime = Math.min(
      audioElement.value.duration || 0,
      audioElement.value.currentTime + 10
    )
  }
}

function updateProgress() {
  if (!audioElement.value) return
  currentTime.value = audioElement.value.currentTime
  if (duration.value > 0) {
    progressPercent.value = (currentTime.value / duration.value) * 100
  }

  // 時間碼顯示應該由文本滾動位置決定，不是由音檔播放時間決定
  // 音檔播放時間已經顯示在播放器的時間顯示中了
}

function updateDuration() {
  if (!audioElement.value) return
  duration.value = audioElement.value.duration || 0
}

function updateVolume() {
  if (!audioElement.value) return
  volume.value = audioElement.value.volume
  isMuted.value = audioElement.value.muted
}

function updatePlaybackRate() {
  if (!audioElement.value) return
  playbackRate.value = audioElement.value.playbackRate
}

function seekTo(event) {
  if (!audioElement.value || !progressBar.value || duration.value === 0) return
  const rect = progressBar.value.getBoundingClientRect()
  const clickX = event.clientX - rect.left
  const percent = Math.max(0, Math.min(100, (clickX / rect.width) * 100))
  const newTime = (percent / 100) * duration.value
  audioElement.value.currentTime = newTime
}

function calculateArcProgress(event, svg) {
  if (!svg) return null

  const rect = svg.getBoundingClientRect()
  const clickX = event.clientX - rect.left
  const clickY = event.clientY - rect.top

  // 將 SVG 座標轉換為相對於圓心的座標
  const svgWidth = rect.width
  const svgHeight = rect.height
  const scaleX = 200 / svgWidth  // viewBox 是 0 0 200 140
  const scaleY = 140 / svgHeight

  const svgX = clickX * scaleX
  const svgY = clickY * scaleY

  const centerX = 100
  const centerY = 100

  // 計算點擊位置相對於圓心的角度
  const dx = svgX - centerX
  const dy = svgY - centerY
  let angle = Math.atan2(dy, dx) * (180 / Math.PI)

  // 將角度標準化到 0-360 範圍
  if (angle < 0) angle += 360

  // 檢查點擊是否在 210-330 度範圍內（我們的弧線範圍）
  // 如果不在範圍內，調整到最近的邊界
  let normalizedAngle = angle
  if (angle >= 0 && angle < 210) {
    // 如果在右側，判斷靠近哪一端
    if (angle < 90) {
      normalizedAngle = 330 // 靠近結束端
    } else {
      normalizedAngle = 210 // 靠近開始端
    }
  } else if (angle > 330) {
    normalizedAngle = 330
  }

  // 計算在弧線上的進度百分比
  // 210度是0%，330度是100%
  let percent = ((normalizedAngle - 210) / 120) * 100
  percent = Math.max(0, Math.min(100, percent))

  return percent
}

function startDragArc(event) {
  if (!audioElement.value || duration.value === 0) return
  isDraggingArc.value = true

  const percent = calculateArcProgress(event, event.currentTarget)
  if (percent !== null) {
    draggingPercent.value = percent
  }
}

function dragArc(event) {
  if (!isDraggingArc.value || !audioElement.value || duration.value === 0) return

  // 先計算進度（在事件失效前）
  const percent = calculateArcProgress(event, event.currentTarget)
  if (percent === null) return

  // 取消之前的 RAF
  if (rafId !== null) {
    cancelAnimationFrame(rafId)
  }

  // 使用 RAF 來優化更新
  rafId = requestAnimationFrame(() => {
    draggingPercent.value = percent
  })
}

function stopDragArc() {
  if (!isDraggingArc.value) return

  isDraggingArc.value = false

  // 取消任何待處理的 RAF
  if (rafId !== null) {
    cancelAnimationFrame(rafId)
    rafId = null
  }

  // 釋放時才真正 seek 到目標位置
  if (audioElement.value && duration.value > 0) {
    const newTime = (draggingPercent.value / 100) * duration.value
    audioElement.value.currentTime = newTime
  }
}

function setVolume(event) {
  if (!audioElement.value) return
  const newVolume = parseInt(event.target.value) / 100
  audioElement.value.volume = newVolume
  if (newVolume > 0 && isMuted.value) {
    audioElement.value.muted = false
  }
}

function toggleMute() {
  if (!audioElement.value) return
  audioElement.value.muted = !audioElement.value.muted
}

function setPlaybackRate(rate) {
  if (!audioElement.value) return
  audioElement.value.playbackRate = rate
}

function formatTime(seconds) {
  if (!seconds || isNaN(seconds)) return '0:00'
  const hours = Math.floor(seconds / 3600)
  const mins = Math.floor((seconds % 3600) / 60)
  const secs = Math.floor(seconds % 60)
  if (hours > 0) {
    return `${hours}:${mins.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`
  }
  return `${mins}:${secs.toString().padStart(2, '0')}`
}

// 時間碼標記
function formatTimecode(seconds) {
  const hours = Math.floor(seconds / 3600)
  const minutes = Math.floor((seconds % 3600) / 60)
  const secs = Math.floor(seconds % 60)
  if (hours > 0) {
    return `${hours}:${minutes.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`
  }
  return `${minutes}:${secs.toString().padStart(2, '0')}`
}

function generateTimecodeMarkers(segmentList) {
  if (!segmentList || segmentList.length === 0) return []
  const markers = []
  const INTERVAL = 15
  const sortedSegments = [...segmentList].sort((a, b) => a.start - b.start)
  const transcriptContent = currentTranscript.value.content
  const segmentPositions = []
  let cumulativeChars = 0

  for (const segment of sortedSegments) {
    const segmentText = segment.text.trim().replace(/\s+/g, ' ')
    let charStart = transcriptContent.indexOf(segment.text.trim(), cumulativeChars)
    if (charStart === -1) {
      charStart = transcriptContent.indexOf(segmentText, cumulativeChars)
    }
    if (charStart !== -1) {
      segmentPositions.push({
        start: segment.start,
        end: segment.end,
        charStart: charStart,
        charEnd: charStart + segmentText.length,
        text: segmentText
      })
      cumulativeChars = charStart + segmentText.length
    }
  }

  const totalChars = transcriptContent.length
  const maxTime = sortedSegments[sortedSegments.length - 1].end
  const usedSegments = new Set()
  const targetTimes = []

  for (let t = 0; t <= maxTime; t += INTERVAL) {
    targetTimes.push(t)
  }

  for (const targetTime of targetTimes) {
    let closestSegment = null
    let minDistance = Infinity
    for (const seg of segmentPositions) {
      if (usedSegments.has(seg)) continue
      const distance = Math.abs(seg.start - targetTime)
      if (distance < minDistance && distance < INTERVAL * 2) {
        minDistance = distance
        closestSegment = seg
      }
    }
    if (closestSegment) {
      usedSegments.add(closestSegment)
      markers.push({
        time: closestSegment.start,
        label: formatTimecode(closestSegment.start),
        charPosition: closestSegment.charStart
      })
    }
  }

  markers.sort((a, b) => a.time - b.time)
  for (let i = 0; i < markers.length; i++) {
    markers[i].positionPercent = totalChars > 0 ? (markers[i].charPosition / totalChars) * 100 : 0
  }

  return markers
}

function seekToTime(time) {
  if (audioElement.value) {
    audioElement.value.currentTime = time
    audioElement.value.play().catch(err => console.log('播放失敗:', err))
  }
}

function syncScroll() {
  if (!textarea.value || timecodeMarkers.value.length === 0) return

  const scrollTop = textarea.value.scrollTop
  const scrollHeight = textarea.value.scrollHeight
  const clientHeight = textarea.value.clientHeight

  if (scrollHeight <= clientHeight) {
    activeTimecodeIndex.value = 0
    return
  }

  const scrollPercent = scrollTop / (scrollHeight - clientHeight)
  const contentLength = currentTranscript.value.content.length
  const estimatedCharPos = Math.floor(scrollPercent * contentLength)

  let closestIndex = 0
  let minDistance = Infinity

  for (let i = 0; i < timecodeMarkers.value.length; i++) {
    const distance = Math.abs(timecodeMarkers.value[i].charPosition - estimatedCharPos)
    if (distance < minDistance) {
      minDistance = distance
      closestIndex = i
    }
  }

  if (closestIndex !== activeTimecodeIndex.value) {
    activeTimecodeIndex.value = closestIndex
  }
}

// 鍵盤快捷鍵
function handleKeyboardShortcuts(event) {
  if (!currentTranscript.value.hasAudio || !audioElement.value) return
  if (event.altKey && !event.ctrlKey && !event.metaKey) {
    switch(event.key) {
      case 'k':
      case 'K':
        event.preventDefault()
        togglePlayPause()
        break
      case 'j':
      case 'J':
      case 'ArrowLeft':
        event.preventDefault()
        skipBackward()
        break
      case 'l':
      case 'L':
      case 'ArrowRight':
        event.preventDefault()
        skipForward()
        break
      case 'm':
      case 'M':
        event.preventDefault()
        toggleMute()
        break
    }
  }
}
</script>

<style scoped>
.transcript-detail-container {
  max-width: 1400px;
  margin: 0 auto;
  padding: 20px;
  height: 100%;
  box-sizing: border-box;
  overflow: hidden;
}

/* 雙欄佈局 */
.transcript-layout {
  display: grid;
  grid-template-columns: 320px 1fr;
  gap: 20px;
  height: 100%;
  align-items: start;
}

/* 左側控制面板 */
.left-panel {
  padding: 24px;
  position: sticky;
  top: 20px;
  display: flex;
  flex-direction: column;
  gap: 20px;
  height: fit-content;
  max-height: calc(100vh - 40px);
  overflow-y: auto;
}

/* 右側文字區域 */
.right-panel {
  padding: 24px;
  height: 100%;
  display: flex;
  flex-direction: column;
  box-sizing: border-box;
}

/* 返回按鈕 */
.btn-back-icon {
  width: 44px;
  height: 44px;
  border: none;
  background: var(--neu-bg);
  border-radius: 12px;
  box-shadow: var(--neu-shadow-btn);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.3s ease;
  color: var(--neu-primary);
}

.btn-back-icon:hover {
  box-shadow: var(--neu-shadow-btn-hover);
  transform: translateY(-2px);
}

.btn-back-icon:active {
  box-shadow: var(--neu-shadow-btn-active);
  transform: translateY(0);
}

/* 任務名稱區域 */
.task-name-section {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.section-label {
  font-size: 11px;
  font-weight: 600;
  color: var(--neu-text-light);
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.editable-title {
  font-size: 1.25rem;
  font-weight: 700;
  color: var(--neu-text);
  margin: 0;
  cursor: pointer;
  padding: 8px 12px;
  border-radius: 8px;
  transition: all 0.2s ease;
  word-break: break-word;
}

.editable-title:hover {
  background: rgba(163, 177, 198, 0.1);
}

.title-input {
  width: 100%;
  padding: 8px 12px;
  font-size: 1.25rem;
  font-weight: 700;
  border: 2px solid var(--neu-primary);
  border-radius: 8px;
  background: var(--neu-bg);
  color: var(--neu-text);
  box-shadow: var(--neu-shadow-inset);
}

/* 元數據區域 */
.metadata-section {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 12px;
  background: var(--neu-bg);
  border-radius: 12px;
  box-shadow: var(--neu-shadow-inset);
}

.meta-item {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  color: var(--neu-text);
}

.meta-item svg {
  stroke: var(--neu-primary);
  flex-shrink: 0;
}

/* 按鈕組 */
.action-buttons {
  display: flex;
  flex-direction: row;
  flex-wrap: wrap;
  gap: 10px;
  justify-content: center;
}

/* 操作按鈕 - Neumorphism 風格 */
.btn-action {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 10px 20px;
  border: none;
  border-radius: 12px;
  background: var(--neu-bg);
  color: var(--neu-primary);
  box-shadow: var(--neu-shadow-btn);
  cursor: pointer;
  font-size: 14px;
  font-weight: 600;
  transition: all 0.3s ease;
  width: fit-content;
  align-self: center;
}

.btn-action:hover {
  box-shadow: var(--neu-shadow-btn-hover);
  color: var(--neu-primary-dark);
  transform: translateY(-2px);
}

.btn-action:active {
  box-shadow: var(--neu-shadow-btn-active);
  transform: translateY(0);
}

.btn-action svg {
  stroke: currentColor;
  flex-shrink: 0;
}

.transcript-main {
  padding: 32px;
}

.transcript-header {
  margin-bottom: 24px;
  padding-bottom: 20px;
  border-bottom: 2px solid rgba(163, 177, 198, 0.2);
}

.header-top {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 20px;
  margin-bottom: 16px;
}

.header-left {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  flex: 1;
  min-width: 0;
}

.header-actions {
  display: flex;
  gap: 12px;
  flex-shrink: 0;
}

.btn-back-icon {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 40px;
  height: 40px;
  flex-shrink: 0;
  background: var(--neu-bg);
  box-shadow: var(--neu-shadow-btn);
  border: none;
  border-radius: 12px;
  color: var(--neu-text);
  cursor: pointer;
  transition: all 0.2s ease;
  margin-top: 4px;
}

.btn-back-icon:hover {
  box-shadow: var(--neu-shadow-btn-hover);
  transform: translateY(-2px);
  color: var(--neu-primary);
}

.title-section {
  flex: 1;
  min-width: 0;
}

.editable-title {
  font-size: 1.75rem;
  font-weight: 700;
  color: var(--neu-primary);
  margin: 0;
  cursor: pointer;
  padding: 4px 8px;
  border-radius: 8px;
  transition: background 0.2s ease;
}

.editable-title:hover {
  background: rgba(163, 177, 198, 0.1);
}

.title-input {
  width: 100%;
  font-size: 1.75rem;
  font-weight: 700;
  color: var(--neu-primary);
  padding: 8px 12px;
  border: 2px solid var(--neu-primary);
  border-radius: 8px;
  background: var(--neu-bg);
  outline: none;
}

.transcript-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 16px;
  margin-top: 12px;
}

.meta-item {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 0.9rem;
  color: var(--neu-text-light);
}

/* 音訊播放器樣式 */
.audio-player-container {
  margin-bottom: 24px;
}

.audio-error {
  padding: 12px;
  background: #ffebee;
  color: #c62828;
  border-radius: 8px;
  margin-bottom: 12px;
}

/* 圓形播放器 */
.custom-audio-player.circular-player {
  background: var(--neu-bg);
  padding: 10px 5px 20px;
  border-radius: 20px;
  box-shadow: var(--neu-shadow-raised);
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 10px;
  max-width: 280px;
  margin: 0 auto;
}

/* 圓形進度條容器 */
.circular-progress-container {
  width: 100%;
  max-width: 280px;
  margin: 0 auto;
}

.progress-arc {
  width: 100%;
  height: auto;
  cursor: pointer;
  filter: drop-shadow(0 1px 2px rgba(0, 0, 0, 0.1));
  user-select: none;
  -webkit-user-select: none;
  -moz-user-select: none;
  -ms-user-select: none;
}

/* 進度條弧線樣式 */
.arc-background {
  stroke: #d1d9e6;
  stroke-opacity: 0.5;
}

.arc-progress {
  stroke: var(--neu-primary);
  stroke-linecap: round;
  transition: stroke-dashoffset 0.1s linear;
}

.arc-thumb {
  fill: var(--neu-primary);
  filter: drop-shadow(0 2px 4px rgba(0, 0, 0, 0.2));
  transition: cx 0.1s linear, cy 0.1s linear;
  pointer-events: none;
}

/* 中央控制區 - 播放、快進、快退 */
.circular-controls-center {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 16px;
  margin-top: -90px;
}

/* 時間顯示 */
.time-display-center {
  font-size: 0.8rem;
  color: var(--neu-text);
  font-weight: 500;
  text-align: center;
  margin-top: 6px;
}

/* 音量和控制區（包含 info、音量、速度） */
.volume-and-controls {
  width: 100%;
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  margin-top: 6px;
  padding: 0 10px;
}

/* 音量控制區 */
.volume-control-center {
  display: flex;
  justify-content: center;
  align-items: center;
  gap: 10px;
  flex: 1;
}

/* 靜音按鈕（音量條開頭） */
.mute-btn-volume {
  width: 20px !important;
  height: 20px !important;
  min-width: 10px !important;
  min-height: 10px !important;
  padding: 0px !important;
  margin: 0;
  flex-shrink: 0;
  background: transparent !important;
  box-shadow: none !important;
  transition: all 0.2s ease;
  display: flex;
  align-items: center;
  justify-content: center;
  overflow: visible;
  border-radius: 4px !important;
}

.mute-btn-volume svg {
  display: block;
}

.mute-btn-volume:hover {
  background: var(--neu-bg);
  box-shadow: var(--neu-shadow-btn);
  transform: translateY(-1px);
}

.mute-btn-volume:active {
  box-shadow: var(--neu-shadow-btn-active);
  transform: translateY(0);
}

.volume-slider-horizontal {
  width: 70px;
  height: 3px;
  -webkit-appearance: none;
  appearance: none;
  background: var(--neu-bg);
  /* box-shadow: var(--neu-shadow-inset); */
  border: var(--neu-primary) 1px solid;
  border-radius: 2px;
  outline: none;
  cursor: pointer;
  /* transform: translateY(-50%); */
}

.volume-slider-horizontal::-webkit-slider-thumb {
  -webkit-appearance: none;
  appearance: none;
  width: 5px;
  height: 14px;
  background: var(--neu-primary);
  border-radius: 30%;
  cursor: pointer;
  box-shadow: 0 2px 4px rgba(0, 0, 0, 0.2);
}

.volume-slider-horizontal::-moz-range-thumb {
  width: 10px;
  height: 10px;
  background: var(--neu-primary);
  border-radius: 50%;
  cursor: pointer;
  border: none;
  box-shadow: 0 2px 4px rgba(0, 0, 0, 0.2);
}

/* 底部控制區 - 快捷鍵說明和速度 */
.circular-controls-bottom {
  width: 100%;
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-top: 12px;
  padding: 0 20px;
}

/* 快捷鍵說明 */
.keyboard-shortcuts-info {
  position: relative;
}

.info-btn {
  width: 40px;
  height: 40px;
  background: transparent !important;
  box-shadow: none !important;
}

.info-btn:hover {
  background: var(--neu-bg) !important;
  box-shadow: var(--neu-shadow-btn) !important;
}

.shortcuts-tooltip {
  position: absolute;
  bottom: 100%;
  left: 0;
  margin-bottom: 8px;
  background: var(--neu-bg);
  box-shadow: var(--neu-shadow-raised);
  border-radius: 12px;
  padding: 12px;
  display: none;
  flex-direction: column;
  gap: 8px;
  z-index: 100;
  min-width: 220px;
  white-space: nowrap;
}

.shortcuts-tooltip::after {
  content: '';
  position: absolute;
  top: 100%;
  left: 0;
  right: 0;
  height: 12px;
}

.keyboard-shortcuts-info:hover .shortcuts-tooltip,
.shortcuts-tooltip:hover {
  display: flex;
}

.shortcuts-title {
  font-size: 0.8rem;
  font-weight: 600;
  color: var(--neu-text);
  margin-bottom: 4px;
}

.shortcuts-section {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.shortcuts-section-title {
  font-size: 0.7rem;
  font-weight: 600;
  color: var(--neu-text-light);
  margin-top: 4px;
  margin-bottom: 2px;
}

.shortcut-item {
  display: flex;
  align-items: center;
  gap: 12px;
  font-size: 0.75rem;
  color: var(--neu-text);
}

.shortcut-item kbd {
  background: var(--neu-bg);
  box-shadow: var(--neu-shadow-btn);
  padding: 3px 6px;
  border-radius: 6px;
  font-size: 0.7rem;
  font-weight: 600;
  font-family: monospace;
  color: var(--neu-primary);
  min-width: 28px;
  text-align: center;
}

.shortcut-item span {
  flex: 1;
  color: var(--neu-text);
  font-size: 0.75rem;
}

/* 控制按鈕 */
.audio-control-btn {
  background: var(--neu-bg);
  box-shadow: var(--neu-shadow-btn);
  border: none;
  border-radius: 50%;
  width: 40px;
  height: 40px;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  color: var(--neu-text);
  transition: all 0.2s ease;
  position: relative;
  flex-shrink: 0;
}

.audio-control-btn:hover {
  box-shadow: var(--neu-shadow-btn-hover);
  transform: translateY(-2px);
  color: var(--neu-primary);
}

.audio-control-btn:active {
  box-shadow: var(--neu-shadow-btn-active);
  transform: translateY(0);
}

.audio-play-btn {
  width: 60px;
  height: 60px;
}

.audio-skip-btn {
  width: 46px;
  height: 46px;
}

.control-label {
  position: absolute;
  font-size: 9px;
  font-weight: 700;
  bottom: 7px;
  color: var(--neu-primary);
}

/* 快退按鈕的數字在左下角 */
.skip-backward .control-label {
  left: 9px;
}

/* 快進按鈕的數字在右下角 */
.skip-forward .control-label {
  right: 9px;
}

/* 速度控制 */
.speed-control {
  position: relative;
}

.speed-btn {
  width: 54px;
  height: 40px;
  border-radius: 12px;
  background: transparent !important;
  box-shadow: none !important;
}

.speed-btn:hover {
  background: var(--neu-bg) !important;
  box-shadow: var(--neu-shadow-btn) !important;
}

.speed-label {
  font-size: 0.85rem;
  font-weight: 600;
  color: var(--neu-text);
}

.speed-dropdown {
  position: absolute;
  bottom: 100%;
  right: 0;
  margin-bottom: 8px;
  background: rgba(236, 240, 243, 0.75) !important;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1),
              0 0 0 1px rgba(255, 255, 255, 0.2) inset !important;
  border-radius: 12px;
  padding: 4px;
  display: none;
  flex-direction: column;
  gap: 4px;
  z-index: 1000;
  min-width: 70px;
}

.speed-dropdown::after {
  content: '';
  position: absolute;
  top: 100%;
  left: 0;
  right: 0;
  height: 12px;
}

.speed-control:hover .speed-dropdown,
.speed-dropdown:hover {
  display: flex;
}

.speed-option {
  background: transparent;
  box-shadow: none;
  border: none;
  padding: 6px 0px;
  border-radius: 8px;
  cursor: pointer;
  font-size: 0.85rem;
  font-weight: 600;
  color: var(--neu-text);
  transition: all 0.2s ease;
  text-align: center;
}

.speed-option:hover {
  background: rgba(163, 177, 198, 0.15);
  color: var(--neu-primary);
}

.speed-option.active {
  background: rgba(163, 177, 198, 0.2);
  color: var(--neu-primary);
  font-weight: 700;
}

/* 取代工具列 */
.replace-toolbar {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  margin-top: 20px;
  padding: 16px;
  background: rgba(163, 177, 198, 0.1);
  border-radius: 12px;
  align-items: stretch;
}

.replace-input {
  flex: 1;
  min-width: 150px;
  padding: 10px 14px;
  border: none;
  border-radius: 8px;
  background: var(--neu-bg);
  box-shadow: var(--neu-shadow-inset);
  color: var(--neu-text);
  font-size: 0.95rem;
}

.replace-input:focus {
  outline: 2px solid var(--neu-primary);
}

/* 逐字稿內容 */
.transcript-content-wrapper {
  position: relative;
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.timecode-fixed-display {
  position: absolute;
  top: calc(25% - 33px); /* 基準線上方，留出按鈕高度 */
  right: 20px; /* 往左偏移，避開滾動條 */
  display: flex;
  align-items: center;
  gap: 8px;
  background: rgba(255, 219, 184, 0.15); /* 更低透明度，增強玻璃感 */
  border-radius: 8px;
  padding: 8px 12px;
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.08),
              0 0 0 1px rgba(255, 255, 255, 0.15) inset; /* 內陰影增加深度 */
  cursor: pointer;
  transition: all 0.3s ease;
  z-index: 100;
  backdrop-filter: blur(5px) saturate(10%); /* 更強的毛玻璃效果 */
  -webkit-backdrop-filter: blur(16px) saturate(200%);
}

.timecode-fixed-display:hover {
  box-shadow: var(--neu-shadow-btn-hover);
  transform: translateY(0%) translateX(-2px);
}

.timecode-label {
  font-size: 0.9rem;
  font-weight: 600;
  color: var(--neu-primary);
  /* color: #f56a38; */
}

.transcript-content-area {
  position: relative;
  flex: 1;
  display: flex;
  flex-direction: column;
}

.textarea-wrapper {
  position: relative;
  width: 100%;
  flex: 1;
  display: flex;
  flex-direction: column;
}

.textarea-wrapper.show-reference-line::before {
  content: '';
  position: absolute;
  top: 25%;
  left: 0;
  right: 0;
  height: 2px;
  background: linear-gradient(90deg, transparent, #ff6b35, transparent);
  z-index: 5;
  pointer-events: none;
}

.loading-state,
.error-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  flex: 1;
  color: var(--neu-text-light);
}

.spinner {
  width: 40px;
  height: 40px;
  border: 3px solid rgba(163, 177, 198, 0.2);
  border-top-color: var(--neu-primary);
  border-radius: 50%;
  animation: spin 1s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

.transcript-textarea {
  width: 100%;
  height: 100%;
  padding: 20px;
  border: none;
  border-radius: 12px;
  background: var(--neu-bg);
  box-shadow: var(--neu-shadow-inset);
  color: var(--neu-text);
  font-size: 1rem;
  line-height: 1.8;
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
  resize: none;
  overflow-y: auto;
  transition: box-shadow 0.3s ease;
}

.transcript-textarea:focus {
  outline: none;
  box-shadow: var(--neu-shadow-inset-hover);
}

.transcript-textarea.editing {
  background: #fff;
  box-shadow: 0 0 0 2px var(--neu-primary);
}

.transcript-textarea[readonly] {
  cursor: default;
}

@media (max-width: 768px) {
  .transcript-detail-container {
    padding: 16px;
  }

  .transcript-layout {
    grid-template-columns: 1fr;
  }

  .left-panel {
    position: relative;
    top: 0;
    max-height: none;
  }

  .transcript-main {
    padding: 20px;
  }

  .header-top {
    flex-direction: column;
    gap: 16px;
  }

  .header-left {
    width: 100%;
  }

  .header-actions {
    width: 100%;
    justify-content: flex-start;
  }

  .btn-back-icon {
    width: 36px;
    height: 36px;
  }

  .editable-title,
  .title-input {
    font-size: 1.5rem;
  }

  .replace-toolbar {
    flex-direction: column;
  }

  /* 圓形播放器在小螢幕上的調整 */
  .custom-audio-player.circular-player {
    max-width: 100%;
    padding: 20px 15px 15px;
  }

  .circular-progress-container {
    max-width: 200px;
  }

  .circular-controls-center {
    margin-top: -30px;
  }

  .audio-play-btn {
    width: 54px;
    height: 54px;
  }

  .audio-skip-btn {
    width: 42px;
    height: 42px;
  }

  .time-display-center {
    font-size: 0.75rem;
  }

  .volume-slider-horizontal {
    width: 100px;
  }

  .circular-controls-bottom {
    padding: 0 10px;
  }
}
</style>
