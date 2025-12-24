<template>
  <div class="container">
    <!-- SVG 濾鏡定義 -->
    <ElectricBorder />

    <!-- <header class="header">
      <h1>🎙️ Whisper Transcription Service</h1>
      <p>Upload audio files for automatic transcription with punctuation</p>
    </header> -->

    <!-- 上傳區域 -->
    <UploadZone @file-selected="handleFileUpload" :uploading="uploading" :disabled="!!pendingFile" />

    <!-- 確認表單（在上傳區下方） -->
    <div v-if="pendingFile" class="confirm-section electric-card">
        <div class="electric-inner">
          <div class="electric-border-outer">
            <div class="electric-main modal-body">
              <!-- 第一排：檔案資訊 + 說話者辨識 + 標籤 -->
              <div class="confirm-row">
                <!-- 檔案資訊 -->
                <div class="modal-section file-section">
                  <label class="section-label">檔案資訊</label>
                  <div class="file-info">
                    <span class="label">檔案名稱</span>
                    <span class="value">{{ pendingFile?.name }}</span>
                  </div>
                  <div class="file-info" v-if="pendingFile">
                    <span class="label">檔案大小</span>
                    <span class="value">{{ (pendingFile.size / 1024 / 1024).toFixed(2) }} MB</span>
                  </div>
                  <div class="file-note">
                    音檔保留規則：最多可保留3個音檔，超過會從最舊的依序刪除，亦可手動勾選保留。
                  </div>
                </div>

                <!-- 說話者辨識 -->
                <div class="modal-section diarize-section">
                  <label class="section-label">說話者辨識</label>

                  <label class="toggle-item">
                    <div class="toggle-wrapper">
                      <input type="checkbox" id="modal-diarize" v-model="enableDiarization" class="toggle-input" />
                      <span class="toggle-track">
                        <span class="toggle-thumb"></span>
                      </span>
                    </div>
                    <span class="toggle-label-text">啟用</span>
                  </label>

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
                <div class="modal-section tag-section">
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
              </div>

              <!-- 動作按鈕 -->
              <div class="modal-actions">
                <button class="btn btn-primary btn-start" @click="confirmAndUpload">開始轉錄</button>
                <button class="btn btn-secondary btn-cancel" @click="cancelUpload">取消</button>
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

</template>

<script setup>
import { ref, computed, onMounted, onUnmounted, watch, inject } from 'vue'
import api, { API_BASE, TokenManager } from '../utils/api'
import ElectricBorder from '../components/shared/ElectricBorder.vue'
import UploadZone from '../components/UploadZone.vue'

// 新 API 服務層
import { transcriptionService, taskService, legacyService } from '../api/services'

const showNotification = inject('showNotification')
const tasks = ref([])
const uploading = ref(false)
const enableDiarization = ref(true)
const maxSpeakers = ref(null)
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

// 選擇檔案後顯示確認表單
function handleFileUpload(file) {
  pendingFile.value = file
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
    // 使用新 API 服務層
    const responseData = await transcriptionService.create(formData)

    const newTask = {
      ...responseData,
      file: pendingFile.value.name,
      uploadedAt: new Date().toLocaleString('zh-TW')
    }

    tasks.value.unshift(newTask)

    // 顯示轉錄中通知
    if (showNotification) {
      showNotification({
        title: '轉錄中',
        message: `正在轉錄「${pendingFile.value.name}」`,
        type: 'processing',
        duration: 5000  // 5秒後自動關閉
      })
    }
  } catch (error) {
    console.error('上傳失敗:', error)
    if (showNotification) {
      showNotification({
        title: '上傳失敗',
        message: error.response?.data?.detail || error.message,
        type: 'error',
        duration: 5000
      })
    } else {
      alert('上傳失敗：' + (error.response?.data?.detail || error.message))
    }
  } finally {
    uploading.value = false
    pendingFile.value = null
    selectedTags.value = []
    tagInput.value = ''
  }
}

// 取消上傳
function cancelUpload() {
  pendingFile.value = null
  selectedTags.value = []
  tagInput.value = ''
}

// 下載結果
async function downloadTask(taskId) {
  try {
    // 使用新 API 服務層
    const response = await transcriptionService.download(taskId)

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
    // 使用新 API 服務層
    await taskService.cancel(taskId)

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
    // 使用新 API 服務層
    await taskService.delete(taskId)

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
    // 使用新 API 服務層
    const response = await taskService.getActiveList()
    const serverTasks = response.all_tasks || []

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
    // 並行獲取逐字稿和 segments（使用新 API 服務層）
    const [transcriptResponse, segmentsResponse] = await Promise.all([
      transcriptionService.download(taskId).then(res => ({
        data: res.data
      })),
      transcriptionService.getSegments(taskId).catch(err => {
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
  // 使用新 API 服務層
  return transcriptionService.getAudioUrl(taskId, token)
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
    // 使用新 API 服務層
    await transcriptionService.updateContent(
      currentTranscript.value.task_id,
      currentTranscript.value.content
    )

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
  refreshTasks()
  // 限制視窗高度
  document.body.classList.add('upload-page')
})

onUnmounted(() => {
  // 清理：移除視窗高度限制
  document.body.classList.remove('upload-page')
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

/* 確認表單區域（在上傳區下方） */
.confirm-section {
  width: 100%;
  margin: 20px 0 0;
  animation: slideDown 0.3s ease;
}

@keyframes slideDown {
  from {
    opacity: 0;
    transform: translateY(-20px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

/* 確認對話框（保留用於其他對話框） */
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

/* 確認區響應式排版 */
.confirm-row {
  display: grid;
  grid-template-columns: 1fr 1fr 1fr;
  gap: 20px;
  margin-bottom: 20px;
}

/* 平板版：兩欄 */
@media (max-width: 1024px) {
  .confirm-row {
    grid-template-columns: 1fr 1fr;
  }

  .confirm-row .tag-section {
    grid-column: 1 / -1;
  }
}

/* 移動版：垂直排列 */
@media (max-width: 768px) {
  .confirm-row {
    grid-template-columns: 1fr;
    gap: 0;
  }

  .confirm-row .modal-section {
    margin-bottom: 20px;
  }
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

/* 確認區的 section 不需要底部邊框 */
.confirm-row .modal-section {
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

.file-note {
  margin-top: 12px;
  padding-top: 12px;
  border-top: 1px solid rgba(163, 177, 198, 0.2);
  font-size: 11px;
  line-height: 1.5;
  color: var(--neu-text-light);
  font-style: italic;
}

/* Neumorphism Toggle 開關 */
.toggle-item {
  display: flex;
  align-items: center;
  gap: 12px;
  cursor: pointer;
  user-select: none;
}

.toggle-wrapper {
  position: relative;
  width: 40px;
  height: 22px;
}

.toggle-input {
  opacity: 0;
  width: 0;
  height: 0;
  position: absolute;
}

.toggle-track {
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: var(--neu-bg);
  border-radius: 11px;
  transition: all 0.3s ease;
  box-shadow: var(--neu-shadow-inset);
}

.toggle-thumb {
  position: absolute;
  top: 3px;
  left: 3px;
  width: 16px;
  height: 16px;
  background: var(--neu-bg);
  border-radius: 50%;
  transition: all 0.3s ease;
  box-shadow: var(--neu-shadow-btn-sm);
}

.toggle-input:checked + .toggle-track {
  background: linear-gradient(145deg, #c8e6c9, #a5d6a7);
}

.toggle-input:checked + .toggle-track .toggle-thumb {
  transform: translateX(18px);
  box-shadow: var(--neu-shadow-btn-hover-sm);
}

.toggle-item:hover .toggle-track {
  box-shadow: var(--neu-shadow-inset-hover);
}

.toggle-item:hover .toggle-input:checked + .toggle-track {
  background: linear-gradient(145deg, #b8d6b9, #95c697);
}

.toggle-label-text {
  font-size: 14px;
  color: var(--neu-text);
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
  justify-content: center;
  align-items: center;
}

.modal-actions .btn {
  padding: 12px 32px;
  font-size: 15px;
  font-weight: 600;
}

.modal-actions .btn-cancel {
  padding: 8px 20px;
  font-size: 13px;
}

/* 開始轉錄按鈕 - 使用者頭貼風格 */
.modal-actions .btn-start {
  background: var(--neu-bg);
  color: var(--neu-primary);
  box-shadow: var(--neu-shadow-btn);
}

.modal-actions .btn-start:hover {
  box-shadow: var(--neu-shadow-btn-hover);
  color: var(--neu-primary-dark);
}

.modal-actions .btn-start:active {
  box-shadow: var(--neu-shadow-btn-active);
}

</style>
