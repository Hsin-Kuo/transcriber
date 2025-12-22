<template>
  <div class="container">
    <!-- SVG 濾鏡定義 -->
    <ElectricBorder />

    <!-- <header class="header">
      <h1>🎙️ Whisper Transcription Service</h1>
      <p>Upload audio files for automatic transcription with punctuation</p>
    </header> -->

    <!-- 上傳區域 -->
    <UploadZone @file-selected="handleFileUpload" :uploading="uploading" />

    <!-- 確認對話框 -->
    <div v-if="showConfirmDialog" class="modal-overlay" @click.self="cancelUpload">
      <div class="modal-content electric-card">
        <div class="electric-inner">
          <div class="electric-border-outer">
            <div class="electric-main modal-body">
              <!-- 檔案資訊 -->
              <div class="modal-section">
                <div class="file-info">
                  <span class="label">檔案名稱</span>
                  <span class="value">{{ pendingFile?.name }}</span>
                </div>
                <div class="file-info" v-if="pendingFile">
                  <span class="label">檔案大小</span>
                  <span class="value">{{ (pendingFile.size / 1024 / 1024).toFixed(2) }} MB</span>
                </div>
              </div>

              <!-- 說話者辨識 -->
              <div class="modal-section">
                <label class="section-label">說話者辨識</label>

                <div class="checkbox-item">
                  <input type="checkbox" id="modal-diarize" v-model="enableDiarization" />
                  <label for="modal-diarize">啟用</label>
                </div>

                <div class="sub-setting" v-if="enableDiarization">
                  <label for="modal-maxSpeakers" class="sub-label">
                    最大講者人數
                    <span class="hint">可提高精確度，避免過度分析；留空則自動偵測。</span>
                  </label>
                  <input
                    type="number"
                    id="modal-maxSpeakers"
                    v-model.number="maxSpeakers"
                    min="2"
                    max="10"
                    placeholder="自動偵測"
                    class="number-input"
                  />
                </div>
              </div>

              <!-- 標籤 -->
              <div class="modal-section">
                <label class="section-label">標籤</label>
                <div class="tag-input-container">
                  <div class="tag-input-wrapper">
                    <input
                      type="text"
                      v-model="tagInput"
                      @keydown.enter.prevent="addTag"
                      @keydown.comma.prevent="addTag"
                      placeholder="輸入標籤後按 Enter 或逗號"
                      class="text-input"
                    />
                    <button
                      type="button"
                      class="btn-add-tag"
                      @click="addTag"
                      :disabled="!tagInput.trim()"
                    >
                      新增
                    </button>
                  </div>

                  <!-- 快速選擇現有標籤 -->
                  <div v-if="availableQuickTags.length > 0" class="quick-tags-section">
                    <div class="quick-tags">
                      <button
                        v-for="tag in availableQuickTags"
                        :key="tag"
                        type="button"
                        class="quick-tag-btn"
                        @click="addQuickTag(tag)"
                        :title="`加入標籤：${tag}`"
                      >
                        + {{ tag }}
                      </button>
                    </div>
                  </div>

                  <div v-if="selectedTags.length > 0" class="selected-tags">
                    <span
                      v-for="(tag, index) in selectedTags"
                      :key="index"
                      class="selected-tag"
                    >
                      {{ tag }}
                      <button
                        type="button"
                        class="remove-tag"
                        @click="removeTag(index)"
                        title="移除標籤"
                      >
                        ×
                      </button>
                    </span>
                  </div>
                </div>
              </div>

              <!-- 音檔保留說明 -->
              <div class="modal-section info-section">
                <div class="info-box">
                  <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="info-icon">
                    <circle cx="12" cy="12" r="10"></circle>
                    <line x1="12" y1="16" x2="12" y2="12"></line>
                    <line x1="12" y1="8" x2="12.01" y2="8"></line>
                  </svg>
                  <div class="info-text">
                    <strong>音檔保留規則：</strong>
                    <span>最新的音檔會自動保留；列表中可另勾選保留3個音檔（總共最多保留4個）。</span>
                  </div>
                </div>
              </div>

              <!-- 動作按鈕 -->
              <div class="modal-actions">
                <button class="btn btn-secondary" @click="cancelUpload">取消</button>
                <button class="btn btn-primary" @click="confirmAndUpload">開始轉錄</button>
              </div>
            </div>
          </div>
          <div class="electric-glow-1"></div>
          <div class="electric-glow-2"></div>
        </div>
        <div class="electric-overlay"></div>
        <div class="electric-bg-glow"></div>
      </div>
    </div>

    <!-- 瀏覽逐字稿對話框 -->
    <div v-if="showTranscriptDialog" class="modal-overlay">
      <div class="modal-content transcript-modal electric-card">
        <div class="electric-inner">
          <div class="electric-border-outer">
            <div class="electric-main modal-body">
              <!-- 對話框標題 -->
              <div class="transcript-header">
                <div class="transcript-title-section">
                  <div class="title-with-edit">
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
                  <div class="transcript-meta">
                    <span v-if="currentTranscript.created_at">
                      📅 {{ currentTranscript.created_at }}
                    </span>
                    <span v-if="currentTranscript.text_length">
                      📝 {{ currentTranscript.text_length }} 字
                    </span>
                  </div>
                </div>
              </div>

              <!-- 音檔播放器（僅在有音檔時顯示） -->
              <div v-if="currentTranscript.hasAudio" class="audio-player-container">
                <!-- 隱藏的原生音檔元素 -->
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

                <!-- 自定義播放進度條 -->
                <div class="custom-audio-player">
                  <!-- 進度條 -->
                  <div class="progress-bar-container" @click="seekTo" ref="progressBar">
                    <div class="progress-bar-background">
                      <div class="progress-bar-played" :style="{ width: progressPercent + '%' }"></div>
                      <div class="progress-bar-thumb" :style="{ left: progressPercent + '%' }"></div>
                    </div>
                  </div>

                  <!-- 控制列 -->
                  <div class="audio-controls-row">
                    <!-- 左側：播放控制 -->
                    <div class="audio-controls-left">
                      <button class="audio-control-btn audio-skip-btn" @click="skipBackward" title="快退10秒">
                        <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
                          <path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/>
                          <path d="M3 3v5h5"/>
                        </svg>
                        <span class="control-label">10</span>
                      </button>
                      <button class="audio-control-btn audio-play-btn" @click="togglePlayPause" :title="isPlaying ? '暫停' : '播放'">
                        <svg v-if="!isPlaying" width="26" height="26" viewBox="0 0 24 24" fill="currentColor">
                          <path d="M8 5v14l11-7z"/>
                        </svg>
                        <svg v-else width="26" height="26" viewBox="0 0 24 24" fill="currentColor">
                          <path d="M6 4h4v16H6V4zm8 0h4v16h-4V4z"/>
                        </svg>
                      </button>
                      <button class="audio-control-btn audio-skip-btn" @click="skipForward" title="快進10秒">
                        <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
                          <path d="M21 12a9 9 0 1 1-9-9c2.52 0 4.93 1 6.74 2.74L21 8"/>
                          <path d="M21 3v5h-5"/>
                        </svg>
                        <span class="control-label">10</span>
                      </button>
                      <div class="time-display">
                        {{ formatTime(currentTime) }} / {{ formatTime(duration) }}
                      </div>
                    </div>

                    <!-- 右側：音量和速度 -->
                    <div class="audio-controls-right">
                      <!-- 播放速度 -->
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
                      <!-- 音量控制 -->
                      <div class="volume-control">
                        <button class="audio-control-btn" @click="toggleMute" :title="isMuted ? '取消靜音' : '靜音'">
                          <svg v-if="!isMuted && volume > 0.5" width="20" height="20" viewBox="0 0 24 24" fill="currentColor">
                            <path d="M3 9v6h4l5 5V4L7 9H3zm13.5 3c0-1.77-1.02-3.29-2.5-4.03v8.05c1.48-.73 2.5-2.25 2.5-4.02zM14 3.23v2.06c2.89.86 5 3.54 5 6.71s-2.11 5.85-5 6.71v2.06c4.01-.91 7-4.49 7-8.77s-2.99-7.86-7-8.77z"/>
                          </svg>
                          <svg v-else-if="!isMuted && volume > 0" width="20" height="20" viewBox="0 0 24 24" fill="currentColor">
                            <path d="M3 9v6h4l5 5V4L7 9H3zm13.5 3c0-1.77-1.02-3.29-2.5-4.03v8.05c1.48-.73 2.5-2.25 2.5-4.02z"/>
                          </svg>
                          <svg v-else width="20" height="20" viewBox="0 0 24 24" fill="currentColor">
                            <path d="M16.5 12c0-1.77-1.02-3.29-2.5-4.03v2.21l2.45 2.45c.03-.2.05-.41.05-.63zm2.5 0c0 .94-.2 1.82-.54 2.64l1.51 1.51C20.63 14.91 21 13.5 21 12c0-4.28-2.99-7.86-7-8.77v2.06c2.89.86 5 3.54 5 6.71zM4.27 3L3 4.27 7.73 9H3v6h4l5 5v-6.73l4.25 4.25c-.67.52-1.42.93-2.25 1.18v2.06c1.38-.31 2.63-.95 3.69-1.81L19.73 21 21 19.73l-9-9L4.27 3zM12 4L9.91 6.09 12 8.18V4z"/>
                          </svg>
                        </button>
                        <input
                          type="range"
                          class="volume-slider"
                          min="0"
                          max="100"
                          :value="volume * 100"
                          @input="setVolume"
                          title="調整音量"
                        />
                      </div>

                      <!-- 快捷鍵說明 -->
                      <div class="shortcuts-info">
                        <button class="audio-control-btn shortcuts-btn" title="鍵盤快捷鍵">
                          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                            <circle cx="12" cy="12" r="10"></circle>
                            <line x1="12" y1="16" x2="12" y2="12"></line>
                            <line x1="12" y1="8" x2="12.01" y2="8"></line>
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
                    </div>
                  </div>
                </div>
              </div>

              <!-- 逐字稿內容區域 -->
              <div class="transcript-content-wrapper">
                <!-- 固定顯示的當前 Timecode（左上角） -->
                <div
                  v-if="activeTimecodeIndex >= 0 && timecodeMarkers.length > 0 && currentTranscript.hasAudio"
                  class="timecode-fixed-display"
                  @click="seekToTime(timecodeMarkers[activeTimecodeIndex].time)"
                  :title="`點擊跳轉到 ${timecodeMarkers[activeTimecodeIndex].label}`"
                >
                  <div class="timecode-label">{{ timecodeMarkers[activeTimecodeIndex].label }}</div>
                </div>

                <!-- 逐字稿內容 -->
                <div
                  class="transcript-content"
                  :class="{ 'with-sidebar': timecodeMarkers.length > 0 && currentTranscript.hasAudio }"
                  ref="transcriptContent"
                >
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
                    :class="{ 'show-reference-line': timecodeMarkers.length > 0 && currentTranscript.hasAudio }"
                  >
                    <textarea
                      v-model="currentTranscript.content"
                      class="transcript-textarea"
                      :readonly="!isEditing"
                      :class="{ 'editing': isEditing }"
                      ref="textarea"
                      @input="updateScrollHeight"
                      @scroll="syncScroll"
                    ></textarea>
                  </div>
                </div>
              </div>

              <!-- 對話框操作區域 -->
              <div class="transcript-actions">
                <!-- 取代工具列（僅在編輯模式顯示） -->
                <div v-if="isEditing && !loadingTranscript && !transcriptError" class="replace-toolbar-inline">
                  <input
                    v-model="findText"
                    type="text"
                    placeholder="尋找"
                    class="replace-input-inline"
                    @compositionstart="isComposing = true"
                    @compositionend="isComposing = false"
                    @keydown.enter="replaceAll"
                  />
                  <input
                    v-model="replaceText"
                    type="text"
                    placeholder="取代為"
                    class="replace-input-inline"
                    @compositionstart="isComposing = true"
                    @compositionend="isComposing = false"
                    @keyup.enter="replaceAll"
                  />
                  <button
                    class="btn btn-replace-inline"
                    @click="replaceAll"
                    :disabled="!findText"
                    title="取代所有符合的文字"
                  >
                    取代全部
                  </button>
                </div>

                <!-- 操作按鈕 - 三聯組合 -->
                <div class="action-buttons">
                  <!-- 非編輯模式的三聯按鈕 -->
                  <div v-if="!isEditing" class="btn-group-modal">
                    <button
                      class="btn btn-modal-edit btn-group-left"
                      @click="startEditing"
                    >
                      編輯
                    </button>
                    <button
                      class="btn btn-modal-download btn-group-middle"
                      @click="downloadCurrentTranscript"
                    >
                      下載
                    </button>
                    <button
                      class="btn btn-modal-close btn-group-right"
                      @click="closeTranscriptDialog"
                    >
                      關閉
                    </button>
                  </div>

                  <!-- 編輯模式的雙聯按鈕 -->
                  <div v-if="isEditing" class="btn-group-modal">
                    <button
                      class="btn btn-modal-save btn-group-left"
                      @click="saveTranscript"
                      :disabled="savingTranscript"
                    >
                      <span v-if="savingTranscript" class="spinner"></span>
                      {{ savingTranscript ? '儲存中' : '儲存' }}
                    </button>
                    <button
                      class="btn btn-modal-cancel btn-group-right"
                      @click="cancelEditing"
                    >
                      取消
                    </button>
                  </div>
                </div>
              </div>
            </div>
          </div>
          <div class="electric-glow-1"></div>
          <div class="electric-glow-2"></div>
        </div>
        <div class="electric-overlay"></div>
        <div class="electric-bg-glow"></div>
      </div>
    </div>
  </div>

</template>

<script setup>
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import api, { API_BASE, TokenManager } from '../utils/api'
import ElectricBorder from '../components/shared/ElectricBorder.vue'
import UploadZone from '../components/UploadZone.vue'

const tasks = ref([])
const uploading = ref(false)
const enableDiarization = ref(true)
const maxSpeakers = ref(null)
const showConfirmDialog = ref(false)
const pendingFile = ref(null)
const selectedTags = ref([])
const tagInput = ref('')
const showTranscriptDialog = ref(false)
const currentTranscript = ref({})
const loadingTranscript = ref(false)
const transcriptError = ref(null)
const isEditing = ref(false)
const savingTranscript = ref(false)
const originalContent = ref('')
const findText = ref('')
const replaceText = ref('')
const isComposing = ref(false)
const segments = ref([])
const timecodeMarkers = ref([])
const audioElement = ref(null)
const textarea = ref(null)
const transcriptContent = ref(null)
const textareaScrollHeight = ref(0)
const audioError = ref(null)
const activeTimecodeIndex = ref(-1)  // 當前活躍的 timecode 索引
const isPlaying = ref(false)  // 音檔播放狀態
// 自定義音檔播放器狀態
const progressBar = ref(null)
const currentTime = ref(0)
const duration = ref(0)
const progressPercent = ref(0)
const volume = ref(1)
const isMuted = ref(false)
const playbackRate = ref(1)
// 任務名稱編輯
const isEditingTitle = ref(false)
const editingTaskName = ref('')
const titleInput = ref(null)
const savingName = ref(false)

// SSE 連接管理
const eventSources = new Map() // 存儲每個任務的 SSE 連接

// 監聽對話框開關，控制背景滾動
watch(showTranscriptDialog, (newValue) => {
  if (newValue) {
    // 對話框打開時，禁用背景滾動
    document.body.style.overflow = 'hidden'
  } else {
    // 對話框關閉時，恢復背景滾動
    document.body.style.overflow = ''
  }
})

// 獲取所有唯一標籤
const allTags = computed(() => {
  const tags = new Set()
  tasks.value.forEach(task => {
    if (task.tags && task.tags.length > 0) {
      task.tags.forEach(tag => tags.add(tag))
    }
  })
  return Array.from(tags).sort()
})

// 可用的快速標籤（排除已選擇的）
const availableQuickTags = computed(() => {
  return allTags.value.filter(tag => !selectedTags.value.includes(tag))
})

// 選擇檔案後顯示確認對話框
function handleFileUpload(file) {
  pendingFile.value = file
  showConfirmDialog.value = true
}

// 標籤管理
function addTag() {
  const tag = tagInput.value.trim()
  if (tag && !selectedTags.value.includes(tag)) {
    selectedTags.value.push(tag)
    tagInput.value = ''
  } else if (selectedTags.value.includes(tag)) {
    tagInput.value = ''
  }
}

function addQuickTag(tag) {
  if (!selectedTags.value.includes(tag)) {
    selectedTags.value.push(tag)
  }
}

function removeTag(index) {
  selectedTags.value.splice(index, 1)
}

// 確認後開始上傳
async function confirmAndUpload() {
  if (!pendingFile.value) return

  showConfirmDialog.value = false
  uploading.value = true

  const formData = new FormData()
  formData.append('file', pendingFile.value)
  formData.append('punct_provider', 'gemini')
  formData.append('chunk_audio', 'true')
  formData.append('language', 'auto')  // 使用 Whisper 自動偵測語言
  formData.append('diarize', enableDiarization.value ? 'true' : 'false')
  if (enableDiarization.value && maxSpeakers.value) {
    formData.append('max_speakers', maxSpeakers.value.toString())
  }
  if (selectedTags.value.length > 0) {
    formData.append('tags', JSON.stringify(selectedTags.value))
  }

  try {
    const response = await api.post('/transcribe', formData, {
      headers: { 'Content-Type': 'multipart/form-data' }
    })

    const newTask = {
      ...response.data,
      file: pendingFile.value.name,
      uploadedAt: new Date().toLocaleString('zh-TW')
    }

    tasks.value.unshift(newTask)
    // 為新任務建立 SSE 連接
    connectTaskSSE(newTask.task_id)
  } catch (error) {
    console.error('上傳失敗:', error)
    alert('上傳失敗：' + (error.response?.data?.detail || error.message))
  } finally {
    uploading.value = false
    pendingFile.value = null
    selectedTags.value = []
    tagInput.value = ''
  }
}

// 取消上傳
function cancelUpload() {
  showConfirmDialog.value = false
  pendingFile.value = null
  selectedTags.value = []
  tagInput.value = ''
}

// SSE 實時更新任務狀態
function connectTaskSSE(taskId) {
  // 如果已經有連接，不要重複建立
  if (eventSources.has(taskId)) {
    console.log(`⏭️ 跳過 SSE 連接（已存在）: ${taskId}`)
    return
  }

  const token = TokenManager.getAccessToken()
  if (!token) {
    console.error('❌ 無法建立 SSE 連接：未登入')
    return
  }

  // 創建 SSE 連接（帶 token）
  const url = `${API_BASE}/transcribe/${taskId}/events?token=${token}`
  const eventSource = new EventSource(url)

  console.log(`🔌 建立 SSE 連接: ${taskId}`)

  eventSource.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data)

      // 找到對應的任務並更新
      const task = tasks.value.find(t => t.task_id === taskId)
      if (task) {
        // 保存 cancelling 狀態
        const cancelling = task.cancelling
        Object.assign(task, data)

        // 處理取消狀態
        if (cancelling && data.status === 'cancelled') {
          task.cancelling = false
          delete task.cancelledAt
          console.log('✅ 任務已完全停止:', taskId)
        } else if (cancelling) {
          task.cancelling = true
        }

        // 如果任務已完成、失敗或取消，主動關閉 SSE 連接
        if (['completed', 'failed', 'cancelled'].includes(data.status)) {
          console.log(`✅ 任務結束（${data.status}），關閉 SSE: ${taskId}`)
          disconnectTaskSSE(taskId)
        }
      }
    } catch (error) {
      console.error('❌ 解析 SSE 數據失敗:', error)
    }
  }

  eventSource.addEventListener('end', (event) => {
    console.log(`✅ 任務完成，關閉 SSE: ${taskId}`)
    disconnectTaskSSE(taskId)
  })

  eventSource.addEventListener('error', (event) => {
    console.error(`❌ SSE 錯誤: ${taskId}`)
    // 嘗試解析錯誤訊息
    try {
      const data = JSON.parse(event.data)
      console.error('錯誤詳情:', data.error)
    } catch (e) {
      // 無法解析錯誤訊息
    }
  })

  eventSource.onerror = (error) => {
    console.error(`❌ SSE 連接錯誤: ${taskId}`, error)
    // SSE 會自動重連，但如果是權限問題或任務不存在，應該關閉連接
    if (eventSource.readyState === EventSource.CLOSED) {
      console.log(`🔌 SSE 連接已關閉: ${taskId}`)
      disconnectTaskSSE(taskId)
    }
  }

  eventSources.set(taskId, eventSource)
}

// 斷開 SSE 連接
function disconnectTaskSSE(taskId) {
  const eventSource = eventSources.get(taskId)
  if (eventSource) {
    eventSource.close()
    eventSources.delete(taskId)
    console.log(`🔌 關閉 SSE: ${taskId}`)
  }
}

// 斷開所有 SSE 連接
function disconnectAllSSE() {
  eventSources.forEach((eventSource, taskId) => {
    eventSource.close()
    console.log(`🔌 關閉 SSE: ${taskId}`)
  })
  eventSources.clear()
}

// 下載結果
async function downloadTask(taskId) {
  try {
    const response = await api.get(`/transcribe/${taskId}/download`, {
      responseType: 'blob'
    })

    // 從 Content-Disposition header 取得檔名
    let filename = 'transcript.txt'
    const contentDisposition = response.headers['content-disposition']
    if (contentDisposition) {
      const filenameMatch = contentDisposition.match(/filename\*?=(?:UTF-8'')?["']?([^"';]+)["']?/i)
      if (filenameMatch && filenameMatch[1]) {
        filename = decodeURIComponent(filenameMatch[1])
      }
    }

    // 如果無法從 header 取得，使用 task 資料作為備用
    if (filename === 'transcript.txt') {
      const task = tasks.value.find(t => t.task_id === taskId)
      filename = task?.result_filename || 'transcript.txt'
    }

    const url = window.URL.createObjectURL(new Blob([response.data]))
    const link = document.createElement('a')
    link.href = url
    link.setAttribute('download', filename)
    document.body.appendChild(link)
    link.click()
    link.remove()
    window.URL.revokeObjectURL(url)
  } catch (error) {
    console.error('下載失敗:', error)
    alert('下載失敗：' + (error.response?.data?.detail || error.message))
  }
}

// 取消任務
async function cancelTask(taskId) {
  if (!confirm('確定要取消此任務嗎？任務將停止執行，暫存檔案將被刪除。')) {
    return
  }

  // 找到任務並設置取消中狀態
  const task = tasks.value.find(t => t.task_id === taskId)
  if (task) {
    task.cancelling = true
    task.cancelledAt = Date.now()  // 記錄取消時間
  }

  try {
    await api.post(`/transcribe/${taskId}/cancel`)

    console.log('任務取消指令已發送:', taskId)

    // 不要立即設置狀態，讓輪詢來更新
    // 當後端真正停止時，輪詢會獲取到 cancelled 狀態
    // 此時 pollTaskStatus 會清除 cancelling 標記
  } catch (error) {
    console.error('取消失敗:', error)
    if (task) {
      task.cancelling = false
      delete task.cancelledAt
    }
    alert('取消失敗：' + (error.response?.data?.detail || error.message))
  }
}

// 刪除任務
async function deleteTask(taskId) {
  if (!confirm('確定要刪除此任務及其檔案嗎？此操作無法復原。')) {
    return
  }

  try {
    await api.delete(`/transcribe/${taskId}`)

    // 從本地列表中移除
    const index = tasks.value.findIndex(t => t.task_id === taskId)
    if (index !== -1) {
      tasks.value.splice(index, 1)
    }

    console.log('任務已刪除:', taskId)
  } catch (error) {
    console.error('刪除失敗:', error)
    alert('刪除失敗：' + (error.response?.data?.detail || error.message))
  }
}

// 刷新所有任務
async function refreshTasks() {
  try {
    const response = await api.get('/transcribe/active/list')
    const serverTasks = response.data.all_tasks || []

    // 保存本地任務的 cancelling 狀態
    const cancellingStates = new Map()
    tasks.value.forEach(task => {
      if (task.cancelling !== undefined) {
        cancellingStates.set(task.task_id, task.cancelling)
      }
    })

    // 用伺服器任務列表替換本地列表
    tasks.value = serverTasks.map(serverTask => {
      // 恢復 cancelling 狀態（如果有）
      if (cancellingStates.has(serverTask.task_id)) {
        return { ...serverTask, cancelling: cancellingStates.get(serverTask.task_id) }
      }
      return serverTask
    })

    // 為進行中的任務建立 SSE 連接
    tasks.value.forEach(task => {
      if (['pending', 'processing'].includes(task.status)) {
        connectTaskSSE(task.task_id)
      }
    })
  } catch (error) {
    console.error('刷新任務列表失敗:', error)
  }
}

// 格式化時間戳為 MM:SS 或 HH:MM:SS
function formatTimecode(seconds) {
  const hours = Math.floor(seconds / 3600)
  const minutes = Math.floor((seconds % 3600) / 60)
  const secs = Math.floor(seconds % 60)

  if (hours > 0) {
    return `${hours}:${minutes.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`
  }
  return `${minutes}:${secs.toString().padStart(2, '0')}`
}

// 從 segments 生成 timecode markers（約每30秒一個），使用實際 segment 位置
function generateTimecodeMarkers(segmentList) {
  if (!segmentList || segmentList.length === 0) return []

  const markers = []
  const INTERVAL = 15 // 約每15秒一個標記

  // 確保 segments 按時間排序
  const sortedSegments = [...segmentList].sort((a, b) => a.start - b.start)

  // 使用實際的 transcript content 來查找每個 segment 的字符位置
  const transcriptContent = currentTranscript.value.content
  const segmentPositions = []
  let cumulativeChars = 0 // 使用累積字符作為估算位置

  for (const segment of sortedSegments) {
    // 清理 segment 文字（移除多餘空格、換行）
    const segmentText = segment.text.trim().replace(/\s+/g, ' ')

    // 嘗試多種搜索策略
    let charStart = -1

    // 策略 1：直接搜索原始文字
    charStart = transcriptContent.indexOf(segment.text.trim(), cumulativeChars)

    // 策略 2：搜索清理後的文字
    if (charStart === -1) {
      charStart = transcriptContent.indexOf(segmentText, cumulativeChars)
    }

    // 策略 3：搜索前幾個字（至少 10 個字）
    if (charStart === -1 && segmentText.length > 10) {
      const prefix = segmentText.substring(0, Math.min(20, segmentText.length))
      charStart = transcriptContent.indexOf(prefix, cumulativeChars)
    }

    // 策略 4：從頭開始搜索（可能順序有變化）
    if (charStart === -1) {
      charStart = transcriptContent.indexOf(segmentText, 0)
    }

    if (charStart !== -1) {
      segmentPositions.push({
        start: segment.start,
        end: segment.end,
        charStart: charStart,
        charEnd: charStart + segmentText.length,
        text: segmentText
      })
      // 更新累積位置
      cumulativeChars = charStart + segmentText.length
    } else {
      // 如果還是找不到，使用累積字符位置作為估算
      segmentPositions.push({
        start: segment.start,
        end: segment.end,
        charStart: cumulativeChars,
        charEnd: cumulativeChars + segmentText.length,
        text: segmentText
      })
      cumulativeChars += segmentText.length
    }
  }

  const totalChars = transcriptContent.length

  // 使用實際 segment 起始點作為標記，選擇接近 60 秒間隔的
  const maxTime = sortedSegments[sortedSegments.length - 1].end
  const usedSegments = new Set() // 避免重複使用同一個 segment

  // 生成所有目標時間點（每 60 秒一個）
  const targetTimes = []
  for (let t = 0; t <= maxTime; t += INTERVAL) {
    targetTimes.push(t)
  }

  // 為每個目標時間找到最接近的 segment
  for (const targetTime of targetTimes) {
    let closestSegment = null
    let minDistance = Infinity

    for (const seg of segmentPositions) {
      // 跳過已使用的 segment
      if (usedSegments.has(seg)) continue

      // 計算 segment 起始時間與目標時間的距離
      const distance = Math.abs(seg.start - targetTime)

      // 只選擇距離在合理範圍內的 segment（比如 120 秒內）
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
    // 如果找不到 closestSegment，繼續嘗試下一個目標時間，不要 break
  }

  // 確保 markers 按時間排序
  markers.sort((a, b) => a.time - b.time)

  // 計算每個 marker 的字符位置百分比（用於絕對定位）
  for (let i = 0; i < markers.length; i++) {
    markers[i].positionPercent = totalChars > 0
      ? (markers[i].charPosition / totalChars) * 100
      : 0
  }

  console.log(`📍 生成 ${markers.length} 個 timecode markers，音檔總長度: ${Math.floor(maxTime / 60)}:${Math.floor(maxTime % 60).toString().padStart(2, '0')}`)
  if (markers.length > 0) {
    console.log(`   第一個: ${markers[0].label}, 最後一個: ${markers[markers.length - 1].label}`)
  }

  return markers
}

// 點擊 timecode 跳轉到音檔位置
function seekToTime(time) {
  if (audioElement.value) {
    audioElement.value.currentTime = time
    audioElement.value.play().catch(err => {
      console.log('播放失敗:', err)
    })
  }
}

// 快退10秒
function skipBackward() {
  if (audioElement.value) {
    audioElement.value.currentTime = Math.max(0, audioElement.value.currentTime - 10)
  }
}

// 快進10秒
function skipForward() {
  if (audioElement.value) {
    audioElement.value.currentTime = Math.min(
      audioElement.value.duration || 0,
      audioElement.value.currentTime + 10
    )
  }
}

// 播放/暫停切換
function togglePlayPause() {
  if (!audioElement.value) return

  if (audioElement.value.paused) {
    audioElement.value.play().then(() => {
      isPlaying.value = true
    }).catch(err => {
      console.error('播放失敗:', err)
      audioError.value = '播放失敗'
    })
  } else {
    audioElement.value.pause()
    isPlaying.value = false
  }
}

// 自定義播放器事件處理
function updateProgress() {
  if (!audioElement.value) return
  currentTime.value = audioElement.value.currentTime
  if (duration.value > 0) {
    progressPercent.value = (currentTime.value / duration.value) * 100
  }
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
  currentTime.value = newTime
  progressPercent.value = percent
}

function setVolume(event) {
  if (!audioElement.value) return
  const newVolume = parseInt(event.target.value) / 100
  audioElement.value.volume = newVolume
  volume.value = newVolume
  if (newVolume > 0 && isMuted.value) {
    audioElement.value.muted = false
    isMuted.value = false
  }
}

function toggleMute() {
  if (!audioElement.value) return
  audioElement.value.muted = !audioElement.value.muted
  isMuted.value = audioElement.value.muted
}

function setPlaybackRate(rate) {
  if (!audioElement.value) return
  audioElement.value.playbackRate = rate
  playbackRate.value = rate
}

function formatTime(seconds) {
  if (!seconds || isNaN(seconds)) return '0:00'

  const hours = Math.floor(seconds / 3600)
  const mins = Math.floor((seconds % 3600) / 60)
  const secs = Math.floor(seconds % 60)

  if (hours > 0) {
    return `${hours}:${mins.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`
  } else {
    return `${mins}:${secs.toString().padStart(2, '0')}`
  }
}

// 鍵盤快捷鍵處理（使用 Alt 鍵避免系統快捷鍵衝突）
function handleKeyboardShortcuts(event) {
  // 如果沒有音檔，不處理快捷鍵
  if (!currentTranscript.value.hasAudio || !audioElement.value) return

  // 使用 Alt 鍵組合（編輯時也可用，較少衝突）
  if (event.altKey && !event.ctrlKey && !event.metaKey) {
    switch(event.key) {
      case 'k':
      case 'K':
        // Alt + K：播放/暫停
        event.preventDefault()
        togglePlayPause()
        break
      case 'j':
      case 'J':
        // Alt + J：快退 10 秒
        event.preventDefault()
        skipBackward()
        break
      case 'l':
      case 'L':
        // Alt + L：快進 10 秒
        event.preventDefault()
        skipForward()
        break
      case 'ArrowLeft':
        // Alt + Left：快退 10 秒
        event.preventDefault()
        skipBackward()
        break
      case 'ArrowRight':
        // Alt + Right：快進 10 秒
        event.preventDefault()
        skipForward()
        break
      case ',':
        // Alt + , ：快退 5 秒
        event.preventDefault()
        if (audioElement.value) {
          audioElement.value.currentTime = Math.max(0, audioElement.value.currentTime - 5)
        }
        break
      case '.':
        // Alt + . ：快進 5 秒
        event.preventDefault()
        if (audioElement.value) {
          audioElement.value.currentTime = Math.min(
            audioElement.value.duration || 0,
            audioElement.value.currentTime + 5
          )
        }
        break
      case 'm':
      case 'M':
        // Alt + M：靜音/取消靜音
        event.preventDefault()
        toggleMute()
        break
    }
    return
  }

  // 非編輯模式下的額外快捷鍵（不使用修飾鍵）
  if (!isEditing.value && !isEditingTitle.value) {
    // 確保焦點不在 input 或 textarea
    if (event.target.tagName === 'INPUT' || event.target.tagName === 'TEXTAREA') return

    switch(event.key) {
      case ' ':
        // 空格：播放/暫停（僅非編輯模式）
        event.preventDefault()
        togglePlayPause()
        break
      case 'ArrowLeft':
        // 左箭頭：快退 10 秒（僅非編輯模式）
        event.preventDefault()
        skipBackward()
        break
      case 'ArrowRight':
        // 右箭頭：快進 10 秒（僅非編輯模式）
        event.preventDefault()
        skipForward()
        break
    }
  }
}

// 監聽對話框開啟/關閉，控制鍵盤快捷鍵
watch(showTranscriptDialog, (newValue) => {
  if (newValue) {
    // 對話框打開時，添加鍵盤監聽器
    window.addEventListener('keydown', handleKeyboardShortcuts)
  } else {
    // 對話框關閉時，移除鍵盤監聽器
    window.removeEventListener('keydown', handleKeyboardShortcuts)
  }
})

// 改進的 timecode 匹配：結合位置和內容匹配
function findActiveTimecode(charOffset) {
  if (timecodeMarkers.value.length === 0) return -1

  const content = currentTranscript.value.content
  const contextLength = 30 // 用於匹配的上下文長度

  // 取得當前位置的文字片段
  const currentText = content.substring(
    Math.max(0, charOffset - contextLength),
    Math.min(content.length, charOffset + contextLength)
  ).trim()

  // Binary search 找到位置最接近的 marker
  let left = 0
  let right = timecodeMarkers.value.length - 1
  let closest = 0

  while (left <= right) {
    const mid = Math.floor((left + right) / 2)
    const marker = timecodeMarkers.value[mid]

    if (marker.charPosition <= charOffset) {
      closest = mid
      left = mid + 1
    } else {
      right = mid - 1
    }
  }

  // 在附近的 markers 中尋找內容最匹配的（考慮編輯造成的偏移）
  const searchRange = 3 // 前後搜尋 3 個 markers
  const startIdx = Math.max(0, closest - searchRange)
  const endIdx = Math.min(timecodeMarkers.value.length - 1, closest + searchRange)

  let bestMatch = closest
  let bestScore = 0

  for (let i = startIdx; i <= endIdx; i++) {
    const marker = timecodeMarkers.value[i]

    // 找到對應的 segment
    const segment = segments.value.find(s => Math.abs(s.start - marker.time) < 0.1)
    if (!segment) continue

    // 計算文字相似度（簡單的子字串匹配）
    const segmentText = segment.text.trim()
    let score = 0

    // 檢查當前文字片段是否包含 segment 的部分內容
    const segmentWords = segmentText.split(/\s+/).filter(w => w.length > 2)
    for (const word of segmentWords) {
      if (currentText.includes(word)) {
        score += word.length
      }
    }

    // 距離懲罰：距離越遠，分數越低
    const distancePenalty = Math.abs(i - closest) * 10
    score -= distancePenalty

    if (score > bestScore) {
      bestScore = score
      bestMatch = i
    }
  }

  // 如果找到了明顯更好的匹配（分數 > 0），使用它；否則用位置最近的
  return bestScore > 0 ? bestMatch : closest
}

// 計算字符的視覺寬度（區分中文、英文等）
function getCharWidth(char) {
  const code = char.charCodeAt(0)

  // 中文字符（CJK 統一表意文字）
  if ((code >= 0x4E00 && code <= 0x9FFF) ||   // 基本漢字
      (code >= 0x3400 && code <= 0x4DBF) ||   // 擴展 A
      (code >= 0x20000 && code <= 0x2A6DF) || // 擴展 B
      (code >= 0xF900 && code <= 0xFAFF) ||   // 兼容漢字
      (code >= 0x2E80 && code <= 0x2EFF) ||   // 部首補充
      (code >= 0x3000 && code <= 0x303F)) {   // CJK 符號和標點
    return 15 // 15px (等於 font-size)
  }

  // 全角符號
  if (code >= 0xFF00 && code <= 0xFFEF) {
    return 15
  }

  // 英文、數字、半角符號
  if ((code >= 0x0020 && code <= 0x007E) ||   // 基本拉丁字母
      (code >= 0x00A0 && code <= 0x00FF)) {   // 拉丁補充
    return 8.5 // 約 0.57 倍的 font-size
  }

  // 其他字符（預設）
  return 10
}

// 計算一行文字的視覺寬度（像素）
function calculateLineWidth(line) {
  let width = 0
  for (let i = 0; i < line.length; i++) {
    width += getCharWidth(line[i])
  }
  return width
}

// 基於換行符和實際行數精確計算字符偏移量
function estimateCharOffsetFromScroll(targetScrollTop) {
  if (!textarea.value) return 0

  const content = currentTranscript.value.content
  const lineHeight = parseFloat(getComputedStyle(textarea.value).lineHeight) || 27 // line-height: 1.8, font-size: 15px

  // 取得實際可用寬度（扣除 padding）
  const computedStyle = getComputedStyle(textarea.value)
  const paddingLeft = parseFloat(computedStyle.paddingLeft) || 0
  const paddingRight = parseFloat(computedStyle.paddingRight) || 0
  const textareaWidth = textarea.value.clientWidth - paddingLeft - paddingRight

  // 計算目標滾動位置對應的行數
  const targetLineNumber = Math.floor(targetScrollTop / lineHeight)

  // 分割文字為行（根據換行符）
  const lines = content.split('\n')

  // 累計字符數，找到對應的行
  let charOffset = 0
  let currentLine = 0

  for (let i = 0; i < lines.length && currentLine < targetLineNumber; i++) {
    const line = lines[i]

    // 計算這一行的實際視覺寬度
    const lineWidth = calculateLineWidth(line)

    // 計算這一行會佔用多少視覺行（考慮自動換行）
    const visualLines = Math.max(1, Math.ceil(lineWidth / textareaWidth))

    if (currentLine + visualLines <= targetLineNumber) {
      // 整行都在目標行之前
      charOffset += line.length + 1 // +1 for \n
      currentLine += visualLines
    } else {
      // 目標位置在這一行的中間
      const remainingLines = targetLineNumber - currentLine
      const targetWidthInLine = remainingLines * textareaWidth

      // 累積字符直到達到目標寬度
      let accumulatedWidth = 0
      let charsInLine = 0

      for (let j = 0; j < line.length; j++) {
        const charWidth = getCharWidth(line[j])
        if (accumulatedWidth + charWidth > targetWidthInLine) {
          break
        }
        accumulatedWidth += charWidth
        charsInLine++
      }

      charOffset += charsInLine
      break
    }
  }

  return Math.min(charOffset, content.length)
}

// 滾動時更新活躍的 timecode
function syncScroll() {
  if (!textarea.value) return

  // 1. 計算基準線位置（視窗頂部向下 25% 的位置）
  const referenceLineOffset = textarea.value.clientHeight * 0.25
  const referenceScrollTop = textarea.value.scrollTop + referenceLineOffset

  // 2. 將基準線滾動位置轉換為字符偏移量（使用二分搜索 + 換行符計算）
  const estimatedCharOffset = estimateCharOffsetFromScroll(referenceScrollTop)
  const scrollPercent = referenceScrollTop / textarea.value.scrollHeight

  // 3. 使用 binary search 找到對應的 timecode
  const newActiveIndex = findActiveTimecode(estimatedCharOffset)

  // 4. 調試信息：顯示當前位置的文字片段和對應的 segment
  if (newActiveIndex !== activeTimecodeIndex.value) {
    activeTimecodeIndex.value = newActiveIndex

    // 顯示基準線位置附近的文字片段（幫助調試）
    const textAtReference = currentTranscript.value.content.substring(
      Math.max(0, estimatedCharOffset - 30),
      Math.min(currentTranscript.value.content.length, estimatedCharOffset + 30)
    )

    const marker = timecodeMarkers.value[newActiveIndex]

    // 找到對應的 segment
    let correspondingSegment = null
    if (marker && segments.value.length > 0) {
      // 找到時間最接近 marker 的 segment
      correspondingSegment = segments.value.reduce((closest, seg) => {
        const currentDiff = Math.abs(seg.start - marker.time)
        const closestDiff = Math.abs(closest.start - marker.time)
        return currentDiff < closestDiff ? seg : closest
      })
    }

    const lineHeight = parseFloat(getComputedStyle(textarea.value).lineHeight) || 27
    const targetLine = Math.floor((textarea.value.scrollTop + textarea.value.clientHeight * 0.25) / lineHeight)

    console.log(`🎯 滾動 ${(scrollPercent * 100).toFixed(1)}% (scrollTop: ${textarea.value.scrollTop.toFixed(0)}px)`)
    console.log(`   目標行: ${targetLine} (行高: ${lineHeight.toFixed(1)}px) → 字符 ${estimatedCharOffset}/${currentTranscript.value.content.length}`)
    console.log(`   顯示 Timecode: ${marker?.label || 'N/A'} (charPos: ${marker?.charPosition})`)
    console.log(`   基準線文字: "...${textAtReference.replace(/\n/g, '↵')}..."`)
    if (correspondingSegment) {
      console.log(`   Segment文字: "${correspondingSegment.text.trim().substring(0, 60).replace(/\n/g, '↵')}..."`)
    }
  }
}

// 更新 textarea 的 scrollHeight
function updateScrollHeight() {
  if (textarea.value) {
    // 使用 nextTick 確保 DOM 更新後再計算高度
    setTimeout(() => {
      textareaScrollHeight.value = textarea.value.scrollHeight
    }, 0)
  }
}

// 瀏覽逐字稿
async function viewTranscript(taskId) {
  const task = tasks.value.find(t => t.task_id === taskId)
  if (!task) return

  showTranscriptDialog.value = true
  loadingTranscript.value = true
  transcriptError.value = null
  segments.value = []
  timecodeMarkers.value = []
  activeTimecodeIndex.value = -1  // 重置活躍索引

  // 設置基本資訊（巢狀結構）
  currentTranscript.value = {
    task_id: task.task_id,
    filename: task.file?.filename || task.filename, // 支援巢狀與扁平格式
    custom_name: task.custom_name,
    created_at: task.timestamps?.completed_at || task.timestamps?.created_at || task.completed_at || task.created_at,
    text_length: task.result?.text_length || task.text_length,
    duration_text: task.duration_text,
    result_filename: task.result?.transcription_filename || task.result_filename,
    hasAudio: !!(task.result?.audio_file || task.audio_file),  // 檢查是否有音檔
    content: ''
  }

  try {
    // 並行獲取逐字稿和 segments
    const [transcriptResponse, segmentsResponse] = await Promise.all([
      api.get(`/transcribe/${taskId}/download`, {
        responseType: 'text'
      }),
      api.get(`/transcribe/${taskId}/segments`).catch(err => {
        console.log('無法獲取 segments（可能是舊任務）:', err)
        return null
      })
    ])

    currentTranscript.value.content = transcriptResponse.data

    // 如果有 segments 數據，生成 timecode markers
    if (segmentsResponse && segmentsResponse.data.segments) {
      segments.value = segmentsResponse.data.segments
      timecodeMarkers.value = generateTimecodeMarkers(segments.value)
    }

    loadingTranscript.value = false

    // 初始化 scrollHeight
    setTimeout(() => {
      updateScrollHeight()
    }, 100)
  } catch (error) {
    console.error('載入逐字稿失敗:', error)
    transcriptError.value = '載入逐字稿失敗：' + (error.response?.data?.detail || error.message)
    loadingTranscript.value = false
  }
}

// 獲取音檔 URL（添加 token 查詢參數，因為 audio 元素不支持 Authorization header）
function getAudioUrl(taskId) {
  const token = TokenManager.getAccessToken()
  if (!token) {
    console.warn('無法獲取音檔：未登入')
    return ''
  }
  return `${API_BASE}/transcribe/${taskId}/audio?token=${encodeURIComponent(token)}`
}

// 音檔載入成功
function handleAudioLoaded() {
  audioError.value = null
  console.log('音檔載入成功')
}

// 音檔載入錯誤
function handleAudioError(event) {
  console.error('音檔載入失敗:', event)
  const audio = event.target
  if (audio.error) {
    switch (audio.error.code) {
      case audio.error.MEDIA_ERR_ABORTED:
        audioError.value = '音檔載入被中止'
        break
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
        audioError.value = '未知錯誤'
    }
  }
}

// 關閉逐字稿對話框
function closeTranscriptDialog() {
  showTranscriptDialog.value = false
  currentTranscript.value = {}
  transcriptError.value = null
  audioError.value = null
  isEditing.value = false
  originalContent.value = ''
  findText.value = ''
  replaceText.value = ''
  segments.value = []
  timecodeMarkers.value = []
  isComposing.value = false
}

// 從對話框下載逐字稿
function downloadCurrentTranscript() {
  if (currentTranscript.value.task_id) {
    downloadTask(currentTranscript.value.task_id)
  }
}

// 開始編輯
function startEditing() {
  isEditing.value = true
  originalContent.value = currentTranscript.value.content
}

// 取消編輯
function cancelEditing() {
  currentTranscript.value.content = originalContent.value
  isEditing.value = false

}

// 儲存逐字稿
async function saveTranscript() {
  if (!currentTranscript.value.task_id) return

  savingTranscript.value = true

  try {
    await api.put(`/transcribe/${currentTranscript.value.task_id}/content`, {
      content: currentTranscript.value.content
    }, {
      headers: { 'Content-Type': 'application/json' }
    })

    // 更新原始內容
    originalContent.value = currentTranscript.value.content
    isEditing.value = false
    findText.value = ''
    replaceText.value = ''

    alert('逐字稿已成功儲存！')
  } catch (error) {
    console.error('儲存逐字稿失敗:', error)
    alert('儲存失敗：' + (error.response?.data?.detail || error.message))
  } finally {
    savingTranscript.value = false
  }
}

// 開始編輯標題
function startTitleEdit() {
  editingTaskName.value = currentTranscript.value.custom_name || currentTranscript.value.filename || ''
  isEditingTitle.value = true
  // 等待下一個 tick 讓 input 渲染後再聚焦
  setTimeout(() => {
    if (titleInput.value) {
      titleInput.value.focus()
      titleInput.value.select()
    }
  }, 0)
}

// 取消編輯標題
function cancelTitleEdit() {
  isEditingTitle.value = false
  editingTaskName.value = ''
}

// 儲存任務名稱
async function saveTaskName() {
  if (!currentTranscript.value.task_id || savingName.value) return

  // 如果名稱沒有改變，直接關閉編輯模式
  const currentName = currentTranscript.value.custom_name || currentTranscript.value.filename || ''
  if (editingTaskName.value === currentName) {
    cancelTitleEdit()
    return
  }

  savingName.value = true

  try {
    const response = await api.put(
      `/transcribe/${currentTranscript.value.task_id}/metadata`,
      {
        custom_name: editingTaskName.value || null
      },
      {
        headers: { 'Content-Type': 'application/json' }
      }
    )

    // 更新當前逐字稿的資料
    currentTranscript.value.custom_name = response.data.custom_name

    // 重新載入任務列表
    await refreshTasks()

    isEditingTitle.value = false
  } catch (error) {
    console.error('更新任務名稱失敗:', error)
    alert('更新失敗：' + (error.response?.data?.detail || error.message))
  } finally {
    savingName.value = false
  }
}

// 全文取代
function replaceAll() {

  if (isComposing.value) return   // 中文選字中，不觸發
  if (!findText.value) {
    alert('請輸入要尋找的文字')
    return
  }


  const content = currentTranscript.value.content
  const searchText = findText.value
  const replacementText = replaceText.value

  // 計算會有多少個匹配
  const regex = new RegExp(searchText.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'g')
  const matches = content.match(regex)
  const count = matches ? matches.length : 0

  if (count === 0) {
    alert(`找不到「${searchText}」`)
    return
  }

  if (confirm(`找到 ${count} 個「${searchText}」，確定要全部取代為「${replacementText}」嗎？`)) {
    currentTranscript.value.content = content.replaceAll(searchText, replacementText)
    alert(`已成功取代 ${count} 處`)

    // 清空輸入框
    findText.value = ''
    replaceText.value = ''
  }
}

// 生命週期
onMounted(() => {
  refreshTasks()  // refreshTasks 內部會自動為進行中的任務建立 SSE 連接
})

onUnmounted(() => {
  disconnectAllSSE()  // 斷開所有 SSE 連接
})
</script>

<style scoped>
.container {
  animation: fadeIn 0.5s ease-in;
}

@keyframes fadeIn {
  from {
    opacity: 0;
    transform: translateY(20px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

.header {
  text-align: center;
  color: #2d2d2d;
  margin-bottom: 30px;
}

.header h1 {
  font-size: 36px;
  margin-bottom: 10px;
  text-shadow: 0 2px 8px rgba(139, 69, 19, 0.3);
  font-weight: 700;
}

.header p {
  font-size: 16px;
  opacity: 0.8;
}

/* 確認對話框 */
.modal-overlay {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(0, 0, 0, 0.3);
  backdrop-filter: blur(8px);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
  animation: fadeIn 0.3s ease;
}

.modal-content {
  width: 90%;
  max-width: 500px;
  animation: slideUp 0.3s ease;
}

@keyframes slideUp {
  from {
    opacity: 0;
    transform: translateY(30px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

.modal-body {
  padding: 20px;
  overflow-y: auto;
  /* max-height 由 flex 布局自動處理，移除以避免衝突 */
}

.modal-section {
  margin-bottom: 20px;
  padding-bottom: 16px;
  border-bottom: 1px solid rgba(221, 132, 72, 0.15);
}

.modal-section:last-of-type {
  border-bottom: none;
  padding-bottom: 0;
}

.section-label {
  display: block;
  font-size: 13px;
  color: rgba(45, 45, 45, 0.6);
  font-weight: 600;
  margin-bottom: 10px;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.file-info {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
  font-size: 14px;
}

.file-info:last-child {
  margin-bottom: 0;
}

.file-info .label {
  color: rgba(45, 45, 45, 0.6);
  font-weight: 500;
}

.file-info .value {
  color: rgba(45, 45, 45, 0.95);
  font-weight: 600;
}

.checkbox-item {
  display: flex;
  align-items: center;
  gap: 10px;
}

.checkbox-item input[type="checkbox"] {
  width: 18px;
  height: 18px;
  cursor: pointer;
  accent-color: var(--electric-primary);
  flex-shrink: 0;
}

.checkbox-item label {
  cursor: pointer;
  font-size: 14px;
  color: rgba(45, 45, 45, 0.9);
  font-weight: 500;
}

.sub-setting {
  margin-top: 14px;
  padding-left: 28px;
  animation: slideDown 0.2s ease;
}

@keyframes slideDown {
  from {
    opacity: 0;
    transform: translateY(-10px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

.sub-label {
  display: block;
  font-size: 13px;
  color: rgba(45, 45, 45, 0.8);
  font-weight: 500;
  margin-bottom: 8px;
}

.sub-label .hint {
  display: block;
  font-size: 12px;
  color: rgba(45, 45, 45, 0.6);
  font-weight: 400;
  margin-top: 4px;
}

.select-input {
  width: 100%;
  padding: 10px 12px;
  font-size: 14px;
  border: 2px solid rgba(221, 132, 72, 0.3);
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.9);
  color: #2d2d2d;
  transition: all 0.3s;
  cursor: pointer;
}

.select-input:focus {
  outline: none;
  border-color: var(--electric-primary);
  box-shadow: 0 0 0 3px rgba(221, 132, 72, 0.1);
}

.number-input {
  width: 100%;
  padding: 10px 12px;
  font-size: 14px;
  border: 2px solid rgba(221, 132, 72, 0.3);
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.9);
  color: #2d2d2d;
  transition: all 0.3s;
}

.number-input:focus {
  outline: none;
  border-color: var(--electric-primary);
  box-shadow: 0 0 0 3px rgba(221, 132, 72, 0.1);
}

.number-input::placeholder {
  color: rgba(45, 45, 45, 0.4);
}

/* 標籤輸入樣式 */
.tag-input-container {
  margin-top: 10px;
}

.tag-input-wrapper {
  display: flex;
  gap: 8px;
  margin-bottom: 12px;
}

.tag-input-wrapper .text-input {
  flex: 1;
  padding: 10px 12px;
  font-size: 14px;
  border: 2px solid rgba(221, 132, 72, 0.3);
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.9);
  color: #2d2d2d;
  transition: all 0.3s;
}

.tag-input-wrapper .text-input:focus {
  outline: none;
  border-color: var(--electric-primary);
  box-shadow: 0 0 0 3px rgba(221, 132, 72, 0.1);
}

.btn-add-tag {
  padding: 10px 20px;
  font-size: 14px;
  font-weight: 500;
  color: white;
  background: #77969A;
  border: none;
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.3s;
  white-space: nowrap;
}

.btn-add-tag:hover:not(:disabled) {
  background: #336774;
  transform: translateY(-1px);
  box-shadow: 0 4px 12px rgba(119, 150, 154, 0.3);
}

.btn-add-tag:disabled {
  background: rgba(119, 150, 154, 0.4);
  cursor: not-allowed;
}

/* 快速標籤選擇區 */
.quick-tags-section {
  margin-bottom: 12px;
  padding: 10px;
  background: rgba(119, 150, 154, 0.05);
  border-radius: 8px;
  border: 1px dashed rgba(119, 150, 154, 0.2);
}

.quick-tags-label {
  display: inline-block;
  font-size: 12px;
  font-weight: 600;
  color: rgba(119, 150, 154, 0.8);
  margin-bottom: 8px;
}

.quick-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 8px;
}

.quick-tag-btn {
  padding: 5px 12px;
  font-size: 12px;
  font-weight: 500;
  color: #77969A;
  background: white;
  border: 1.5px solid rgba(119, 150, 154, 0.3);
  border-radius: 10px;
  cursor: pointer;
  transition: all 0.2s;
}

.quick-tag-btn:hover {
  background: rgba(119, 150, 154, 0.1);
  border-color: #77969A;
  transform: translateY(-1px);
  box-shadow: 0 2px 6px rgba(119, 150, 154, 0.15);
}

.quick-tag-btn:active {
  transform: translateY(0);
}

.selected-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.selected-tag {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px 12px;
  background: rgba(102, 126, 234, 0.15);
  border: 1px solid rgba(102, 126, 234, 0.3);
  border-radius: 12px;
  font-size: 13px;
  font-weight: 500;
  color: #667eea;
  transition: all 0.2s;
}

.selected-tag:hover {
  background: rgba(102, 126, 234, 0.2);
  border-color: rgba(102, 126, 234, 0.4);
}

.remove-tag {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 18px;
  height: 18px;
  padding: 0;
  margin: 0;
  background: rgba(102, 126, 234, 0.2);
  border: none;
  border-radius: 50%;
  color: #667eea;
  font-size: 16px;
  line-height: 1;
  cursor: pointer;
  transition: all 0.2s;
}

.remove-tag:hover {
  background: rgba(239, 68, 68, 0.2);
  color: #ef4444;
}

/* 信息提示框 */
.info-section {
  margin-top: 20px;
  border: none;
  padding: 0;
}

.info-box {
  display: flex;
  gap: 12px;
  padding: 14px 16px;
  background: linear-gradient(135deg, rgba(221, 132, 72, 0.08) 0%, rgba(221, 132, 72, 0.04) 100%);
  border-left: 3px solid var(--electric-primary);
  border-radius: 8px;
  align-items: flex-start;
}

.info-icon {
  flex-shrink: 0;
  color: var(--electric-primary);
  margin-top: 2px;
}

.info-text {
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: 14px;
  color: #5d4e37;
  line-height: 1.5;
}

.info-text strong {
  color: var(--electric-primary);
  font-weight: 600;
}

.info-text span {
  color: #6d5d47;
}

.modal-actions {
  display: flex;
  gap: 12px;
  margin-top: 24px;
}

.modal-actions .btn {
  flex: 1;
  padding: 12px 24px;
  font-size: 15px;
  font-weight: 600;
  border: none;
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.3s;
}

.btn-primary {
  background: var(--electric-primary);
  color: white;
  box-shadow: 0 4px 12px rgba(221, 132, 72, 0.3);
}

.btn-primary:hover {
  background: #c97840;
  box-shadow: 0 6px 16px rgba(221, 132, 72, 0.5);
  transform: translateY(-2px);
}

.btn-secondary {
  background: rgba(221, 132, 72, 0.1);
  color: var(--electric-primary);
  border: 2px solid rgba(221, 132, 72, 0.3);
}

.btn-secondary:hover {
  background: rgba(221, 132, 72, 0.2);
  border-color: var(--electric-primary);
  transform: translateY(-2px);
}

/* 逐字稿瀏覽對話框 */
.transcript-modal {
  width: 90%;
  max-width: 900px;
  max-height: 90vh;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  height: 90vh;
}

/* 確保對話框內部的所有層級都正確傳遞 flex 布局 */
.transcript-modal .electric-inner,
.transcript-modal .electric-border-outer,
.transcript-modal .electric-main {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-height: 0;
  overflow: hidden;
}

.transcript-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 16px;
  padding-bottom: 16px;
  border-bottom: 2px solid rgba(221, 132, 72, 0.2);
  flex-shrink: 0;
}

/* 音檔播放器 */
.audio-player-container {
  margin-bottom: 16px;
  /* padding: 12px 16px; */
  /* background: rgba(160, 82, 45, 0.05); */
  border-radius: 8px;
  /* border: 1px solid rgba(160, 82, 45, 0.2); */
  position: relative;
  z-index: 10;
}

.audio-player-label {
  font-size: 13px;
  font-weight: 600;
  color: rgba(45, 45, 45, 0.7);
  margin-bottom: 8px;
}

.audio-player {
  background-color: #f0f0f000;
  width: 100%;
  height: 40px;
  outline: none;
  margin-bottom: 8px;
}

.audio-player::-webkit-media-controls-play-button {
  display: none;
}

.audio-player::-webkit-media-controls-panel {
  background-color: rgba(255, 255, 255, 0.9);
  /* background: transparent; */
}

/* 音檔控制按鈕 */
.audio-controls {
  display: flex;
  gap: 8px;
  justify-content: center;
  align-items: center;
}

.audio-control-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  min-width: 40px;
  height: 30px;
  padding: 8px;
  background: rgba(160, 81, 45, 0);
  border: 1px solid rgba(160, 81, 45, 0);
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.2s;
  color: #a0522d;
  position: relative;
}

.audio-control-btn:hover {
  background: rgba(160, 82, 45, 0.2);
  /* border-color: #a0522d; */
  transform: scale(1.05);
  box-shadow: 0 2px 8px rgba(160, 82, 45, 0.3);
}

.audio-control-btn:active {
  transform: scale(0.98);
}

.audio-control-btn svg {
  display: block;
}

/* 播放按鈕特殊樣式（稍大一點） */
/* .audio-control-btn.audio-play-btn {
  min-width: 48px;
  height: 48px;
} */

/* 控制按鈕標籤 */
.control-label {
  position: absolute;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  font-size: 10px;
  font-weight: 700;
  line-height: 1;
  color: inherit;
  pointer-events: none;
}

/* 自定義音檔播放器 */
.custom-audio-player {
  background: rgba(237, 213, 194, 0.044);
  backdrop-filter: blur(20px) saturate(180%);
  -webkit-backdrop-filter: blur(20px) saturate(180%);
  border-radius: 12px;
  padding: 16px;
  border: 1px solid rgba(231, 208, 194, 0.5);
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.1);
}

/* 進度條容器 */
.progress-bar-container {
  margin-bottom: 16px;
  cursor: pointer;
  padding: 8px 0;
}

.progress-bar-background {
  position: relative;
  height: 6px;
  background: rgba(160, 82, 45, 0.15);
  border-radius: 3px;
  overflow: visible;
}

.progress-bar-played {
  position: absolute;
  top: 0;
  left: 0;
  height: 100%;
  background: linear-gradient(90deg, #a0522d, #d2691e);
  border-radius: 3px;
  transition: width 0.1s linear;
}

.progress-bar-thumb {
  position: absolute;
  top: 50%;
  transform: translate(-50%, -50%);
  width: 14px;
  height: 14px;
  background: white;
  border: 2px solid #a0522d;
  border-radius: 50%;
  box-shadow: 0 2px 6px rgba(0, 0, 0, 0.2);
  transition: left 0.1s linear;
  cursor: grab;
}

.progress-bar-thumb:hover {
  transform: translate(-50%, -50%) scale(1.2);
}

.progress-bar-thumb:active {
  cursor: grabbing;
  transform: translate(-50%, -50%) scale(1.1);
}

/* 控制列 */
.audio-controls-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 16px;
}

.audio-controls-left {
  display: flex;
  align-items: center;
  gap: 8px;
  flex: 1;
}

.audio-controls-right {
  display: flex;
  align-items: center;
  gap: 12px;
}

/* 時間顯示 */
.time-display {
  font-size: 13px;
  font-weight: 500;
  color: rgba(45, 45, 45, 0.8);
  min-width: 100px;
  text-align: center;
}

/* 播放速度控制 */
.speed-control {
  position: relative;
  display: flex;
  align-items: center;
  z-index: 10;
}

.speed-btn {
  position: relative;
  z-index: 2;
}

.speed-label {
  font-size: 13px;
  font-weight: 600;
  color: #a0522d;
  min-width: 40px;
  text-align: center;
}

/* 速度下拉選單 */
.speed-dropdown {
  position: absolute;
  top: 100%;
  left: 50%;
  transform: translateX(-50%);
  background: rgba(255, 255, 255, 0.5);
  backdrop-filter: blur(20px) saturate(180%);
  -webkit-backdrop-filter: blur(20px) saturate(180%);
  /* border: 1px solid rgba(255, 255, 255, 0.2); */
  border-radius: 8px;
  padding: 4px;
  /* padding-top: 8px; */
  /* margin-top: -4px; */
  display: flex;
  flex-direction: column;
  gap: 2px;
  opacity: 0;
  visibility: hidden;
  transition: all 0.2s ease;
  box-shadow: 0 4px 16px rgba(255, 255, 255, 0.3);
  min-width: 60px;
  z-index: 1000;
}

.speed-control:hover .speed-dropdown,
.speed-dropdown:hover {
  opacity: 1;
  visibility: visible;
}

.speed-option {
  padding: 6px 12px;
  background: transparent;
  border: none;
  border-radius: 4px;
  cursor: pointer;
  font-size: 13px;
  font-weight: 500;
  color: #a0522d;
  transition: all 0.2s;
  text-align: center;
  white-space: nowrap;
}

.speed-option:hover {
  background: rgba(160, 82, 45, 0.15);
}

.speed-option.active {
  background: rgba(160, 82, 45, 0.1);
  font-weight: 700;
  color: #8b4513;
}

/* 音量控制 */
.volume-control {
  display: flex;
  align-items: center;
  gap: 8px;
}

.volume-slider {
  width: 80px;
  height: 4px;
  -webkit-appearance: none;
  appearance: none;
  background: rgba(160, 82, 45, 0.2);
  border-radius: 2px;
  outline: none;
  cursor: pointer;
}

.volume-slider::-webkit-slider-thumb {
  -webkit-appearance: none;
  appearance: none;
  width: 12px;
  height: 12px;
  background: #a0522d;
  border-radius: 50%;
  cursor: pointer;
  transition: all 0.2s;
}

.volume-slider::-webkit-slider-thumb:hover {
  transform: scale(1.2);
  box-shadow: 0 0 0 4px rgba(160, 82, 45, 0.2);
}

.volume-slider::-moz-range-thumb {
  width: 12px;
  height: 12px;
  background: #a0522d;
  border: none;
  border-radius: 50%;
  cursor: pointer;
  transition: all 0.2s;
}

.volume-slider::-moz-range-thumb:hover {
  transform: scale(1.2);
  box-shadow: 0 0 0 4px rgba(160, 82, 45, 0.2);
}

/* 快捷鍵說明 */
.shortcuts-info {
  position: relative;
  display: flex;
  align-items: center;
}

.shortcuts-btn {
  padding: 6px;
  opacity: 0.7;
  transition: all 0.2s;
}

.shortcuts-btn:hover {
  opacity: 1;
  background: rgba(160, 82, 45, 0.1);
}

.shortcuts-info:hover .shortcuts-tooltip {
  opacity: 1;
  visibility: visible;
  transform: translateY(0);
}

.shortcuts-tooltip {
  position: absolute;
  top: calc(100% + 12px);
  right: 0;
  background: white;
  border: 1px solid rgba(160, 82, 45, 0.2);
  border-radius: 8px;
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.15);
  padding: 16px;
  min-width: 320px;
  opacity: 0;
  visibility: hidden;
  transform: translateY(-4px);
  transition: all 0.2s ease;
  z-index: 1000;
  pointer-events: none;
}

.shortcuts-title {
  font-size: 15px;
  font-weight: 700;
  color: #2d2d2d;
  margin-bottom: 12px;
  padding-bottom: 8px;
  border-bottom: 2px solid rgba(160, 82, 45, 0.2);
}

.shortcuts-section {
  margin-bottom: 12px;
}

.shortcuts-section:last-child {
  margin-bottom: 0;
}

.shortcuts-section-title {
  font-size: 12px;
  font-weight: 600;
  color: #8b4513;
  margin-bottom: 8px;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.shortcut-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 0;
  font-size: 13px;
  color: #2d2d2d;
}

.shortcut-item kbd {
  display: inline-block;
  padding: 3px 8px;
  font-family: 'Monaco', 'Consolas', monospace;
  font-size: 11px;
  font-weight: 600;
  color: #2d2d2d;
  background: linear-gradient(180deg, #ffffff 0%, #f5f5f5 100%);
  border: 1px solid rgba(0, 0, 0, 0.2);
  border-radius: 4px;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.1), inset 0 1px 0 rgba(255, 255, 255, 0.8);
  text-transform: uppercase;
  white-space: nowrap;
}

.shortcut-item span {
  flex: 1;
  color: rgba(45, 45, 45, 0.8);
}

/* 音檔錯誤訊息 */
.audio-error {
  margin-top: 8px;
  padding: 8px 12px;
  background: rgba(239, 68, 68, 0.1);
  border: 1px solid rgba(239, 68, 68, 0.3);
  border-radius: 6px;
  color: #dc2626;
  font-size: 13px;
  text-align: center;
}

.transcript-title-section h2 {
  font-size: 20px;
  color: #2d2d2d;
  margin: 0 0 8px 0;
  font-weight: 700;
}

.transcript-meta {
  display: flex;
  gap: 16px;
  font-size: 13px;
  color: rgba(45, 45, 45, 0.6);
  flex-wrap: wrap;
}

.btn-close {
  background: rgba(239, 68, 68, 0.1);
  border: 2px solid rgba(239, 68, 68, 0.2);
  border-radius: 8px;
  width: 40px;
  height: 40px;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  transition: all 0.3s;
  color: rgba(239, 68, 68, 0.8);
  flex-shrink: 0;
}

.btn-close:hover {
  background: rgba(239, 68, 68, 0.2);
  border-color: rgba(239, 68, 68, 0.4);
  transform: translateY(-2px);
}

/* 內容區域包裝器（包含側邊欄和文字） */
.transcript-content-wrapper {
  position: relative;
  flex: 1;
  overflow: hidden;
  margin-bottom: 20px;
  max-height: calc(90vh - 350px);
  min-height: min(400px, 60vh);
}

/* 固定顯示的當前 Timecode（右上角，貼在基準線上方） - 玻璃態設計 */
.timecode-fixed-display {
  position: absolute;
  top: calc(25% - 36px); /* 基準線上方，留出按鈕高度 */
  right: 37px; /* 往左偏移，避開滾動條 */
  display: flex;
  align-items: center;
  gap: 8px;
  background: rgba(126, 86, 76, 0.15); /* 更低透明度，增強玻璃感 */
  border-radius: 8px;
  padding: 6px 12px;
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.08),
              0 0 0 1px rgba(255, 255, 255, 0.15) inset; /* 內陰影增加深度 */
  cursor: pointer;
  transition: all 0.3s ease;
  z-index: 100;
  backdrop-filter: blur(16px) saturate(200%); /* 更強的毛玻璃效果 */
  -webkit-backdrop-filter: blur(16px) saturate(200%);
}

.timecode-fixed-display:hover {
  background: rgba(255, 255, 255, 0.25);
  transform: translateY(-2px);
  box-shadow: 0 6px 20px rgba(0, 0, 0, 0.12),
              0 0 0 1px rgba(255, 255, 255, 0.25) inset;
  border-color: rgba(255, 255, 255, 0.4);
}

.timecode-icon {
  font-size: 16px;
  line-height: 1;
  color: #6b5d52;
}

.timecode-label {
  font-family: 'Monaco', 'Menlo', 'Courier New', monospace;
  font-size: 13px;
  font-weight: 600;
  color: #4a4a4a; /* 深灰色文字 */
  white-space: nowrap;
}

/* 逐字稿內容區域 */
.transcript-content {
  flex: 1;
  background: rgba(255, 255, 255, 0.5);
  border-radius: 8px;
  padding: 20px;
  border: 1px solid rgba(221, 132, 72, 0.15);
  display: flex;
  flex-direction: column;
  height: 100%;
  position: relative;
  z-index: 1;
  overflow: hidden;
  min-height: 0;
}

/* 當有側邊欄時，內容不需要 margin-bottom */
.transcript-content.with-sidebar {
  margin-bottom: 0;
}

/* 取代工具列 - 內聯版本 */
.replace-toolbar-inline {
  display: flex;
  gap: 8px;
  align-items: center;
  flex: 1;
}

.replace-input-inline {
  padding: 10px 12px;
  font-size: 14px;
  border: 2px solid rgba(130, 162, 140, 0.3);
  border-radius: 6px;
  background: rgba(255, 255, 255, 0.9);
  color: #2d2d2d;
  transition: all 0.3s;
  min-width: 120px;
}

.replace-input-inline:focus {
  outline: none;
  border-color: rgba(130, 162, 140, 0.6);
  box-shadow: 0 0 0 3px rgba(130, 162, 140, 0.1);
}

.replace-input-inline::placeholder {
  color: rgba(45, 45, 45, 0.4);
}

.btn-replace-inline {
  padding: 10px 16px;
  background: #77969Ae6;
  color: white;
  border: none;
  border-radius: 6px;
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.3s;
  white-space: nowrap;
}

.btn-replace-inline:hover:not(:disabled) {
  background: #336774e6;
  transform: translateY(-1px);
}

.btn-replace-inline:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.loading-state,
.error-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 40px 20px;
  text-align: center;
  color: rgba(45, 45, 45, 0.6);
}

.loading-state .spinner {
  width: 40px;
  height: 40px;
  margin-bottom: 16px;
}

.error-state p {
  color: #f87171;
  font-size: 14px;
}

.transcript-text {
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC', 'Hiragino Sans GB', 'Microsoft YaHei', sans-serif;
  font-size: 15px;
  line-height: 1.8;
  color: #2d2d2d;
  white-space: pre-wrap;
  word-wrap: break-word;
  margin: 0;
  padding: 0;
}

/* Textarea 容器 - 用於放置基準線 */
.textarea-wrapper {
  width: 100%;
  flex: 1;
  position: relative;
  min-height: 0;
  overflow: hidden;
}

/* 基準線 - 使用偽元素固定在 25% 位置（更細的線） */
.textarea-wrapper.show-reference-line::before {
  content: '';
  position: absolute;
  top: 25%;
  left: 0;
  right: 0;
  height: 1px; /* 從 3px 改為 1px */
  background: linear-gradient(90deg,
    transparent 0%,
    rgba(139, 69, 19, 0.5) 5%,
    rgba(139, 69, 19, 0.5) 95%,
    transparent 100%
  );
  box-shadow: 0 0 3px rgba(139, 69, 19, 0.3);
  pointer-events: none;
  z-index: 10;
}

/* 基準線端點標記 - 移除左側標記，保持視覺簡潔 */
.textarea-wrapper.show-reference-line::after {
  content: '';
  position: absolute;
  top: calc(25% - 1.5px);
  right: 5px;
  width: 4px;
  height: 4px;
  background: rgba(139, 69, 19, 0.7);
  border-radius: 50%;
  pointer-events: none;
  z-index: 10;
}

.transcript-textarea {
  width: 100%;
  height: 100%;
  min-height: 0;
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC', 'Hiragino Sans GB', 'Microsoft YaHei', sans-serif;
  font-size: 15px;
  line-height: 1.8;
  color: #2d2d2d;
  background: transparent;
  border: none;
  outline: none;
  resize: none;
  padding: 0;
  overflow-y: auto;
}

.transcript-textarea:readonly {
  cursor: default;
}

.transcript-textarea.editing {
  background: rgba(255, 255, 255, 0.8);
  padding: 12px;
  border-radius: 6px;
  border: 2px solid var(--electric-primary);
  cursor: text;
}

.btn-edit {
  background: rgba(82, 162, 140, 0.9);
  color: white;
  border: none;
}

.btn-edit:hover {
  background: rgba(78, 108, 79, 0.9);
  transform: translateY(-2px);
}

.btn-success {
  background: rgba(16, 185, 129, 0.9);
  color: white;
  border: none;
}

.btn-success:hover:not(:disabled) {
  background: rgba(5, 150, 105, 0.9);
  transform: translateY(-2px);
}

.btn-success:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.transcript-actions {
  display: flex;
  gap: 16px;
  justify-content: space-between;
  align-items: center;
  flex-shrink: 0;
  margin-top: auto;
  padding-top: 20px;
}

.action-buttons {
  display: flex;
  gap: 12px;
  margin-left: auto;
}

/* 對話框中的三聯按鈕組 */
.btn-group-modal {
  display: inline-flex;
  border-radius: 8px;
  overflow: hidden;
  box-shadow: 0 2px 8px rgba(139, 69, 19, 0.2);
}

.btn-group-modal .btn {
  border-radius: 0;
  margin: 0;
  position: relative;
  padding: 10px 24px;
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.3s;
  border: none;
}

.btn-group-modal .btn:not(:last-child) {
  border-right: 1px solid rgba(255, 255, 255, 0.2);
}

.btn-group-modal .btn-group-left {
  border-radius: 8px 0 0 8px !important;
}

.btn-group-modal .btn-group-middle {
  border-radius: 0 !important;
}

.btn-group-modal .btn-group-right {
  border-radius: 0 8px 8px 0 !important;
}

.btn-group-modal .btn:hover {
  z-index: 1;
}

/* 編輯按鈕 - 實心棕色 */
.btn-modal-edit {
  background: #a0522d;
  color: white;
}

.btn-modal-edit:hover {
  background: #8b4513;
  transform: translateY(-1px);
}

/* 儲存按鈕 - 實心綠棕色 */
.btn-modal-save {
  background: #77969A;
  color: white;
}

.btn-modal-save:hover:not(:disabled) {
  background: #336774;
  transform: translateY(-1px);
}

.btn-modal-save:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

/* 下載按鈕 - 實心棕色 */
.btn-modal-download {
  background: #a0522d;
  color: white;
}

.btn-modal-download:hover {
  background: #8b4513;
  transform: translateY(-1px);
}

/* 關閉/取消按鈕 - 空心棕色 */
.btn-modal-close,
.btn-modal-cancel {

  background: rgba(139, 69, 19, 0.255);
  border-color: #6b341000 !important;
  color: #82461a;

}

.btn-modal-close:hover,
.btn-modal-cancel:hover {
  background: #783d16df;
  color: rgb(255, 255, 255);

  transform: translateY(-1px);
}

/* RWD: 小螢幕調整 */
@media (max-height: 800px) {
  .transcript-modal {
    max-height: 92vh;
    height: 92vh;
  }

  .modal-body {
    padding: 16px;
  }

  .transcript-content-wrapper {
    max-height: calc(92vh - 320px);
    min-height: min(300px, 50vh);
  }

  .transcript-header {
    margin-bottom: 12px;
    padding-bottom: 12px;
  }
}

@media (max-height: 700px) {
  .transcript-modal {
    max-height: 94vh;
    height: 94vh;
  }

  .modal-body {
    padding: 12px;
  }

  .transcript-content-wrapper {
    max-height: calc(94vh - 280px);
    min-height: min(250px, 45vh);
  }

  .audio-player-container {
    margin-bottom: 10px;
  }

  .transcript-header {
    margin-bottom: 10px;
    padding-bottom: 10px;
  }

  .transcript-actions {
    flex-wrap: wrap;
    gap: 8px;
  }

  .replace-toolbar-inline {
    flex-wrap: wrap;
  }
}

@media (max-height: 600px) {
  .transcript-modal {
    max-height: 96vh;
    height: 96vh;
  }

  .modal-body {
    padding: 10px;
  }

  .transcript-content-wrapper {
    max-height: calc(96vh - 240px);
    min-height: min(200px, 40vh);
  }

  .audio-player-container {
    margin-bottom: 6px;
  }

  .transcript-header {
    margin-bottom: 6px;
    padding-bottom: 6px;
  }

  .transcript-meta {
    font-size: 12px;
    gap: 10px;
  }

  .transcript-actions {
    flex-wrap: wrap;
    gap: 6px;
  }

  .btn {
    padding: 6px 10px;
    font-size: 0.85em;
  }
}

@media (max-height: 500px) {
  .transcript-modal {
    max-height: 98vh;
    height: 98vh;
  }

  .modal-body {
    padding: 8px;
  }

  .transcript-content-wrapper {
    max-height: calc(98vh - 200px);
    min-height: min(150px, 35vh);
  }

  .audio-player-container {
    margin-bottom: 4px;
  }

  .transcript-header {
    margin-bottom: 4px;
    padding-bottom: 4px;
  }

  .transcript-meta {
    font-size: 11px;
    gap: 8px;
  }

  .transcript-actions {
    flex-wrap: wrap;
    gap: 4px;
  }

  .btn {
    padding: 5px 8px;
    font-size: 0.8em;
  }
}

@media (max-width: 768px) {
  .transcript-modal {
    width: 95%;
    max-height: 92vh;
    height: 92vh;
  }

  .modal-body {
    padding: 16px;
  }

  .transcript-content-wrapper {
    max-height: calc(92vh - 300px);
    min-height: min(300px, 50vh);
  }

  .transcript-header {
    flex-direction: column;
    gap: 12px;
  }

  .transcript-actions {
    flex-direction: column;
    align-items: stretch;
  }

  .action-buttons {
    width: 100%;
    justify-content: space-between;
  }

  .replace-toolbar-inline {
    flex-direction: column;
  }

  .replace-input-inline {
    width: 100%;
  }
}

/* 名稱編輯按鈕和 inline 編輯 */
.transcript-title-section {
  flex: 1;
  min-width: 0;
}

.title-with-edit {
  display: block;
  width: 100%;
}

.editable-title {
  cursor: pointer;
  padding: 4px 8px;
  border-radius: 4px;
  transition: all 0.2s ease;
  margin: 0 0 8px 0;
  font-size: 20px;
  color: #2d2d2d;
  font-weight: 700;
  display: inline-block;
}

.editable-title:hover {
  background: rgba(255, 255, 255, 0.1);
}

.title-input {
  width: 100%;
  max-width: none;
  font-size: 1.1em;
  font-weight: 600;
  padding: 8px 14px;
  border: 2px solid #667eea;
  border-radius: 6px;
  background: rgba(255, 255, 255, 0.95);
  color: #333;
  outline: none;
  box-shadow: 0 0 0 3px rgba(102, 126, 234, 0.2);
  transition: all 0.2s ease;
  margin-bottom: 8px;
  box-sizing: border-box;
}

.title-input:focus {
  box-shadow: 0 0 0 4px rgba(102, 126, 234, 0.3);
}

.tasks-prompt {
  text-align: center;
  padding: 24px;
  background: var(--neu-bg);
  border-radius: 20px;
  box-shadow: var(--neu-shadow-inset);
  margin-bottom: 20px;
}

.tasks-prompt p {
  margin: 0;
  font-size: 1rem;
  color: var(--neu-text);
}

.tasks-link {
  color: var(--neu-primary);
  text-decoration: none;
  font-weight: 600;
  transition: color 0.3s ease;
}

.tasks-link:hover {
  color: var(--neu-primary-dark);
  text-decoration: underline;
}
</style>
