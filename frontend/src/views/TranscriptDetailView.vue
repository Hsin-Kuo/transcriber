<template>
  <div class="transcript-detail-container">
    <!-- 主要內容 -->
    <div class="transcript-main card">
      <!-- 標題區域 -->
      <div class="transcript-header">
        <div class="header-top">
          <div class="header-left">
            <button @click="goBack" class="btn-back-icon" title="返回">
              <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M19 12H5M12 19l-7-7 7-7"/>
              </svg>
            </button>
            <div class="title-section">
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
              <h1 v-else @click="startTitleEdit" class="editable-title" title="點擊編輯名稱">
                {{ currentTranscript.custom_name || currentTranscript.filename || '逐字稿' }}
              </h1>
            </div>
          </div>
          <div class="header-actions">
            <button v-if="!isEditing" @click="startEditing" class="btn btn-primary">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"></path>
                <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"></path>
              </svg>
              <span>編輯</span>
            </button>
            <button v-else @click="saveEditing" class="btn btn-primary">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <polyline points="20 6 9 17 4 12"></polyline>
              </svg>
              <span>儲存</span>
            </button>
            <button v-if="isEditing" @click="cancelEditing" class="btn btn-secondary">
              取消
            </button>
            <button @click="downloadTranscript" class="btn btn-secondary">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path>
                <polyline points="7 10 12 15 17 10"></polyline>
                <line x1="12" y1="15" x2="12" y2="3"></line>
              </svg>
              <span>下載</span>
            </button>
          </div>
        </div>
        <div class="transcript-meta">
          <span v-if="currentTranscript.created_at" class="meta-item">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <rect x="3" y="4" width="18" height="18" rx="2" ry="2"></rect>
              <line x1="16" y1="2" x2="16" y2="6"></line>
              <line x1="8" y1="2" x2="8" y2="6"></line>
              <line x1="3" y1="10" x2="21" y2="10"></line>
            </svg>
            {{ formatDate(currentTranscript.created_at) }}
          </span>
          <span v-if="currentTranscript.text_length" class="meta-item">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path>
              <polyline points="14 2 14 8 20 8"></polyline>
            </svg>
            {{ currentTranscript.text_length }} 字
          </span>
          <span v-if="currentTranscript.duration_text" class="meta-item">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <circle cx="12" cy="12" r="10"></circle>
              <polyline points="12 6 12 12 16 14"></polyline>
            </svg>
            {{ currentTranscript.duration_text }}
          </span>
        </div>
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

        <div class="custom-audio-player">
          <div class="progress-bar-container" @click="seekTo" ref="progressBar">
            <div class="progress-bar-background">
              <div class="progress-bar-played" :style="{ width: progressPercent + '%' }"></div>
              <div class="progress-bar-thumb" :style="{ left: progressPercent + '%' }"></div>
            </div>
          </div>

          <div class="audio-controls-row">
            <div class="audio-controls-left">
              <button class="audio-control-btn audio-skip-btn" @click="skipBackward" title="快退10秒">
                <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
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
                <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
                  <path d="M21 12a9 9 0 1 1-9-9c2.52 0 4.93 1 6.74 2.74L21 8"/>
                  <path d="M21 3v5h-5"/>
                </svg>
                <span class="control-label">10</span>
              </button>
              <div class="time-display">
                {{ formatTime(currentTime) }} / {{ formatTime(duration) }}
              </div>
            </div>

            <div class="audio-controls-right">
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
                />
              </div>
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

      <!-- 逐字稿內容區域 -->
      <div class="transcript-content-wrapper">
        <!-- 固定顯示的當前 Timecode -->
        <div
          v-if="activeTimecodeIndex >= 0 && timecodeMarkers.length > 0 && currentTranscript.hasAudio"
          class="timecode-fixed-display"
          @click="seekToTime(timecodeMarkers[activeTimecodeIndex].time)"
          :title="`點擊跳轉到 ${timecodeMarkers[activeTimecodeIndex].label}`"
        >
          <div class="timecode-label">{{ timecodeMarkers[activeTimecodeIndex].label }}</div>
        </div>

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
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted, nextTick } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import api, { API_BASE, TokenManager } from '../utils/api'

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

// 時間碼標記
const segments = ref([])
const timecodeMarkers = ref([])
const activeTimecodeIndex = ref(-1)
const textarea = ref(null)
const titleInput = ref(null)

// 載入逐字稿
onMounted(async () => {
  const taskId = route.params.taskId
  if (!taskId) {
    transcriptError.value = '無效的任務 ID'
    return
  }

  loadingTranscript.value = true
  transcriptError.value = null

  try {
    const taskResponse = await api.get(`/transcribe/active/list`)
    const task = taskResponse.data.all_tasks?.find(t => t.task_id === taskId)

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
      api.get(`/transcribe/${taskId}/download`, {
        responseType: 'text'
      }),
      api.get(`/transcribe/${taskId}/segments`).catch(err => {
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
      await api.put(`/transcribe/${currentTranscript.value.task_id}/metadata`, {
        custom_name: newName
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
    await api.put(`/transcribe/${currentTranscript.value.task_id}/content`, {
      content: currentTranscript.value.content
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
  return `${API_BASE}/transcribe/${taskId}/audio?token=${encodeURIComponent(token)}`
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

  // 更新時間碼顯示（不滾動）
  updateTimecodeFromAudio()
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

function updateTimecodeFromAudio() {
  if (!audioElement.value || timecodeMarkers.value.length === 0) return

  const currentAudioTime = audioElement.value.currentTime

  // 根據當前播放時間更新時間碼索引
  let closestIndex = 0
  let minDistance = Infinity
  for (let i = 0; i < timecodeMarkers.value.length; i++) {
    const distance = Math.abs(timecodeMarkers.value[i].time - currentAudioTime)
    if (distance < minDistance) {
      minDistance = distance
      closestIndex = i
    }
  }
  activeTimecodeIndex.value = closestIndex
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
  max-width: 1200px;
  margin: 0 auto;
  padding: 20px;
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

.custom-audio-player {
  background: var(--neu-bg);
  padding: 20px;
  border-radius: 16px;
  box-shadow: var(--neu-shadow-raised);
}

.progress-bar-container {
  cursor: pointer;
  padding: 10px 0;
  margin-bottom: 16px;
}

.progress-bar-background {
  position: relative;
  height: 6px;
  background: var(--neu-bg);
  box-shadow: var(--neu-shadow-inset);
  border-radius: 3px;
}

.progress-bar-played {
  position: absolute;
  height: 100%;
  background: linear-gradient(90deg, var(--neu-primary), var(--neu-primary-light));
  border-radius: 3px;
  transition: width 0.1s linear;
}

.progress-bar-thumb {
  position: absolute;
  top: 50%;
  transform: translate(-50%, -50%);
  width: 14px;
  height: 14px;
  background: var(--neu-primary);
  border-radius: 50%;
  box-shadow: 0 2px 4px rgba(0, 0, 0, 0.2);
}

.audio-controls-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 16px;
}

.audio-controls-left,
.audio-controls-right {
  display: flex;
  align-items: center;
  gap: 12px;
}

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
}

.audio-control-btn:hover {
  box-shadow: var(--neu-shadow-btn-hover);
  transform: translateY(-2px);
}

.audio-play-btn {
  width: 50px;
  height: 50px;
}

.audio-skip-btn {
  width: 40px;
  height: 40px;
}

.control-label {
  position: absolute;
  font-size: 10px;
  font-weight: 700;
  bottom: 2px;
  color: var(--neu-primary);
}

.time-display {
  font-size: 0.9rem;
  color: var(--neu-text);
  font-weight: 600;
  white-space: nowrap;
}

.speed-control,
.volume-control {
  position: relative;
}

.speed-btn {
  width: 50px;
  border-radius: 12px;
}

.speed-label {
  font-size: 0.85rem;
  font-weight: 600;
}

.speed-dropdown {
  position: absolute;
  bottom: 100%;
  right: 0;
  margin-bottom: 8px;
  background: var(--neu-bg);
  box-shadow: var(--neu-shadow-raised);
  border-radius: 12px;
  padding: 8px;
  display: none;
  flex-direction: column;
  gap: 4px;
  z-index: 10;
}

.speed-control:hover .speed-dropdown {
  display: flex;
}

.speed-option {
  background: var(--neu-bg);
  box-shadow: var(--neu-shadow-btn);
  border: none;
  padding: 8px 16px;
  border-radius: 8px;
  cursor: pointer;
  font-size: 0.9rem;
  font-weight: 600;
  color: var(--neu-text);
  transition: all 0.2s ease;
}

.speed-option:hover,
.speed-option.active {
  box-shadow: var(--neu-shadow-btn-active);
  color: var(--neu-primary);
}

.volume-slider {
  width: 80px;
  height: 4px;
  -webkit-appearance: none;
  appearance: none;
  background: var(--neu-bg);
  box-shadow: var(--neu-shadow-inset);
  border-radius: 2px;
  outline: none;
}

.volume-slider::-webkit-slider-thumb {
  -webkit-appearance: none;
  appearance: none;
  width: 12px;
  height: 12px;
  background: var(--neu-primary);
  border-radius: 50%;
  cursor: pointer;
}

.volume-slider::-moz-range-thumb {
  width: 12px;
  height: 12px;
  background: var(--neu-primary);
  border-radius: 50%;
  cursor: pointer;
  border: none;
}

/* 取代工具列 */
.replace-toolbar {
  display: flex;
  gap: 12px;
  margin-bottom: 20px;
  padding: 16px;
  background: rgba(163, 177, 198, 0.1);
  border-radius: 12px;
}

.replace-input {
  flex: 1;
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
}

.timecode-fixed-display {
  position: sticky;
  top: 0;
  left: 0;
  z-index: 10;
  background: var(--neu-bg);
  box-shadow: var(--neu-shadow-btn);
  padding: 8px 16px;
  border-radius: 8px;
  margin-bottom: 12px;
  cursor: pointer;
  display: inline-block;
  transition: all 0.2s ease;
}

.timecode-fixed-display:hover {
  box-shadow: var(--neu-shadow-btn-hover);
  transform: translateY(-2px);
}

.timecode-label {
  font-size: 0.9rem;
  font-weight: 700;
  color: var(--neu-primary);
}

.transcript-content-area {
  position: relative;
  min-height: 400px;
}

.textarea-wrapper {
  position: relative;
  width: 100%;
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
  min-height: 400px;
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
  height: 600px;
  max-height: 80vh;
  padding: 20px;
  border: none;
  border-radius: 12px;
  background: var(--neu-bg);
  box-shadow: var(--neu-shadow-inset);
  color: var(--neu-text);
  font-size: 1rem;
  line-height: 1.8;
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
  resize: vertical;
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

  .audio-controls-row {
    flex-direction: column;
  }

  .replace-toolbar {
    flex-direction: column;
  }

  .volume-slider {
    width: 100%;
  }
}
</style>
