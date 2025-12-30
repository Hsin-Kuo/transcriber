<template>
  <div class="transcript-detail-container">
    <!-- 雙欄佈局 -->
    <div class="transcript-layout">
      <!-- 左側控制面板 -->
      <div class="left-panel card">
        <!-- 返回按鈕 -->
        <button @click="goBack" class="btn-back-icon" :title="$t('transcriptDetail.goBack')">
          <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M19 12H5M12 19l-7-7 7-7"/>
          </svg>
        </button>

        <!-- 任務名稱 -->
        <div class="task-name-section">
          <label class="section-label">{{ $t('taskList.taskName') }}</label>
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
          <h2 v-else @click="startTitleEdit" class="editable-title" :title="$t('transcriptDetail.edit')">
            {{ currentTranscript.custom_name || currentTranscript.filename || $t('transcriptDetail.transcript') }}
          </h2>
        </div>

        <!-- 元數據 -->
        <TranscriptMetadata
          :created-at="currentTranscript.created_at"
          :text-length="currentTranscript.text_length"
          :duration-text="currentTranscript.duration_text"
        />

        <!-- 段落模式控制項 -->
        <div v-if="displayMode === 'paragraph'" class="paragraph-controls">
          <div class="control-group">
            <label class="toggle-label" :class="{ 'disabled': isEditing }">
              <input
                type="checkbox"
                v-model="showTimecodeMarkers"
                class="toggle-checkbox"
                :disabled="isEditing"
              />
              <span class="toggle-text">{{ $t('transcriptDetail.timecodeMarkers') }}</span>
            </label>
          </div>
        </div>

        <!-- 按鈕組 -->
        <div class="action-buttons">
          <button v-if="!isEditing" @click="startEditing" class="btn btn-action">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"></path>
              <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"></path>
            </svg>
            <span>{{ $t('transcriptDetail.edit') }}</span>
          </button>
          <button v-else @click="saveEditing" class="btn btn-action">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <polyline points="20 6 9 17 4 12"></polyline>
            </svg>
            <span>{{ $t('transcriptDetail.save') }}</span>
          </button>
          <button v-if="isEditing" @click="cancelEditing" class="btn btn-action">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <line x1="18" y1="6" x2="6" y2="18"></line>
              <line x1="6" y1="6" x2="18" y2="18"></line>
            </svg>
            <span>{{ $t('transcriptDetail.cancel') }}</span>
          </button>
          <button v-if="!isEditing" @click="downloadTranscript" class="btn btn-action">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path>
              <polyline points="7 10 12 15 17 10"></polyline>
              <line x1="12" y1="15" x2="12" y2="3"></line>
            </svg>
            <span>{{ $t('transcriptDetail.download') }}</span>
          </button>
        </div>

        <!-- 音訊播放器組件 -->
        <AudioPlayer
          v-if="currentTranscript.hasAudio"
          ref="audioPlayerRef"
          :audio-url="audioUrl"
          :audio-error="audioError"
          :is-playing="isPlaying"
          :volume="volume"
          :is-muted="isMuted"
          :playback-rate="playbackRate"
          :arc-path="arcPath"
          :arc-length="arcLength"
          :thumb-position="thumbPosition"
          :display-progress="displayProgress"
          :display-time="displayTime"
          :duration="duration"
          @update:is-playing="isPlaying = $event"
          @reload-audio="reloadAudio(currentTranscript.task_id)"
          @toggle-play-pause="togglePlayPause"
          @skip-backward="skipBackward"
          @skip-forward="skipForward"
          @toggle-mute="toggleMute"
          @set-volume="setVolume"
          @set-playback-rate="setPlaybackRate"
          @start-drag-arc="startDragArc"
          @drag-arc="dragArc"
          @stop-drag-arc="stopDragArc"
          @audio-loaded="handleAudioLoaded"
          @audio-error="handleAudioError"
          @update-progress="updateProgress"
          @update-duration="(newDuration) => { duration = newDuration }"
          @update-volume="updateVolume"
          @update-playback-rate="updatePlaybackRate"
        />
      </div>

      <!-- 右側文字區域 -->
      <div class="right-panel card">
        <!-- 逐字稿內容區域 -->
        <div class="transcript-content-wrapper">
          <div v-if="loadingTranscript" class="loading-state">
            <div class="spinner"></div>
            <p>載入逐字稿中...</p>
          </div>
          <div v-else-if="transcriptError" class="error-state">
            <p>{{ transcriptError }}</p>
          </div>
          <!-- 段落模式：使用帶標記的可編輯 div -->
          <div
            v-else-if="displayMode === 'paragraph'"
            class="textarea-wrapper"
          >
            <div
              class="transcript-display"
              :class="{ 'editing': isEditing }"
              :contenteditable="isEditing"
              :key="`transcript-${showTimecodeMarkers}-${isEditing}-${currentTranscript.content}`"
              ref="textareaRef"
            >
              <template v-for="(part, index) in getContentParts()" :key="index">
                <span v-if="!part.isMarker" class="text-part">{{ part.text }}</span>
                <span v-else class="marker-wrapper">
                  <span
                    class="segment-marker"
                    contenteditable="false"
                    @click="handleMarkerClick(part.start)"
                  >
                    <svg width="8" height="8" viewBox="0 0 8 8" fill="currentColor">
                      <path d="M 4 6 L 1 2 L 7 2 Z"/>
                    </svg>
                    <span class="timecode-tooltip">
                      {{ formatTime(part.start) }}
                    </span>
                  </span>
                  <span class="text-part">{{ part.text }}</span>
                </span>
              </template>
            </div>
          </div>

          <!-- 字幕模式：表格組件 -->
          <SubtitleTable
            v-else-if="displayMode === 'subtitle'"
            :grouped-segments="groupedSegments"
            v-model:time-format="timeFormat"
            v-model:density-threshold="densityThreshold"
            v-model:speaker-names="speakerNames"
            :has-speaker-info="hasSpeakerInfo"
            :has-audio="currentTranscript.hasAudio"
            :is-editing="isEditing"
            :format-timestamp="formatTimestamp"
            @seek-to-time="seekToTime"
            @update-row-content="updateRowContent"
            @update-segment-speaker="updateSegmentSpeaker"
          />
        </div>

        <!-- 取代工具列組件 -->
        <ReplaceToolbar
          v-if="isEditing && !loadingTranscript && !transcriptError"
          v-model:find-text="findText"
          v-model:replace-text="replaceText"
          @replace-all="replaceAll"
        />
      </div>
    </div>

    <!-- 下載對話框組件 -->
    <DownloadDialog
      :show="showDownloadDialog"
      :time-format="timeFormat"
      :density-threshold="densityThreshold"
      :has-speaker-info="hasSpeakerInfo"
      v-model:selected-format="selectedDownloadFormat"
      v-model:include-speaker="includeSpeaker"
      @close="showDownloadDialog = false"
      @download="performDownload"
    />
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted, watch, nextTick } from 'vue'
import { useRoute, useRouter, onBeforeRouteLeave } from 'vue-router'
import { useI18n } from 'vue-i18n'

const { t: $t } = useI18n()

// 子組件
import AudioPlayer from '../components/transcript/AudioPlayer.vue'
import SubtitleTable from '../components/transcript/SubtitleTable.vue'
import DownloadDialog from '../components/transcript/DownloadDialog.vue'
import ReplaceToolbar from '../components/transcript/ReplaceToolbar.vue'
import TranscriptMetadata from '../components/transcript/TranscriptMetadata.vue'

// Composables
import { useTranscriptData } from '../composables/transcript/useTranscriptData'
import { useAudioPlayer } from '../composables/transcript/useAudioPlayer'
import { useSubtitleMode } from '../composables/transcript/useSubtitleMode'
import { useTranscriptEditor } from '../composables/transcript/useTranscriptEditor'
// import { useTimecodeMarkers } from '../composables/transcript/useTimecodeMarkers'
import { useSegmentMarkers } from '../composables/transcript/useSegmentMarkers'
import { useKeyboardShortcuts } from '../composables/transcript/useKeyboardShortcuts'
import { useTranscriptDownload } from '../composables/transcript/useTranscriptDownload'

const route = useRoute()
const router = useRouter()

// 音訊播放器組件引用
const audioPlayerRef = ref(null)

// ========== 數據管理 ==========
const {
  currentTranscript,
  segments,
  speakerNames,
  loadingTranscript,
  transcriptError,
  originalContent,
  loadTranscript: loadTranscriptData,
  saveTranscript,
  updateTaskName,
  updateSpeakerNames
} = useTranscriptData()

// 顯示模式
const displayMode = computed(() => {
  return currentTranscript.value?.task_type || 'paragraph'
})

// ========== 音訊播放器 ==========
const {
  audioElement,
  isPlaying,
  currentTime,
  duration,
  progressPercent,
  displayProgress,
  displayTime,
  volume,
  isMuted,
  playbackRate,
  arcPath,
  arcLength,
  thumbPosition,
  audioUrl,
  audioError,
  getAudioUrl,
  reloadAudio,
  handleAudioLoaded,
  handleAudioError,
  updateProgress,
  updateDuration,
  updateVolume,
  updatePlaybackRate,
  togglePlayPause,
  skipBackward,
  skipForward,
  seekToTime,
  setVolume,
  toggleMute,
  setPlaybackRate,
  startDragArc,
  dragArc,
  stopDragArc
} = useAudioPlayer()

// 同步 audioElement 引用（用於播放控制）
watch(audioPlayerRef, (newRef) => {
  if (newRef?.audioElement) {
    audioElement.value = newRef.audioElement
  }
}, { immediate: true })

onMounted(() => {
  // 確保在組件掛載後設定引用
  nextTick(() => {
    if (audioPlayerRef.value?.audioElement) {
      audioElement.value = audioPlayerRef.value.audioElement
    }
  })
})

// ========== 字幕模式 ==========
const {
  timeFormat,
  densityThreshold,
  hasSpeakerInfo,
  groupedSegments,
  formatTimestamp,
  updateRowContent,
  convertTableToPlainText,
  reconstructSegmentsFromGroups,
  generateSubtitleText,
  generateSRTText,
  generateVTTText
} = useSubtitleMode(segments)

// ========== 編輯管理 ==========
const {
  isEditing,
  isEditingTitle,
  editingTaskName,
  findText,
  replaceText,
  hasUnsavedChanges,
  titleInput, // 用於 template ref
  startTitleEdit,
  cancelTitleEdit,
  startEditing,
  cancelEditing,
  finishEditing,
  replaceAll,
  handleBeforeUnload
} = useTranscriptEditor(currentTranscript, originalContent, displayMode, groupedSegments, convertTableToPlainText)

// ========== 時間碼標記 ==========
// const {
//   timecodeMarkers,
//   activeTimecodeIndex,
//   textarea, // 用於 template ref
//   generateTimecodeMarkers,
//   syncScroll
// } = useTimecodeMarkers()

// ========== Segment 標記 ==========
const {
  segmentMarkers,
  textareaRef,
  generateSegmentMarkers,
  calculateMarkerPosition,
  formatTime
} = useSegmentMarkers()

// 控制是否顯示 timecode 標記
const showTimecodeMarkers = ref(true)

// 講者名稱自動儲存（debounced）
let speakerNamesSaveTimer = null
watch(speakerNames, (newValue) => {
  // 只有在字幕模式下才需要自動儲存
  if (displayMode.value !== 'subtitle') return

  // 清除之前的計時器
  if (speakerNamesSaveTimer) {
    clearTimeout(speakerNamesSaveTimer)
  }

  // 設定新的計時器（1秒後儲存）
  speakerNamesSaveTimer = setTimeout(async () => {
    console.log('🔄 ' + $t('transcriptDetail.autoSavingSpeaker') + ':', newValue)
    await updateSpeakerNames(newValue)
  }, 1000)
}, { deep: true })

// ========== 下載功能 ==========
const {
  showDownloadDialog,
  selectedDownloadFormat,
  includeSpeaker,
  downloadParagraphMode,
  performSubtitleDownload,
  openDownloadDialog
} = useTranscriptDownload()

// ========== 鍵盤快捷鍵 ==========
const hasAudio = computed(() => currentTranscript.value.hasAudio)
useKeyboardShortcuts(
  hasAudio,
  audioElement,
  isEditing,
  isEditingTitle,
  togglePlayPause,
  skipBackward,
  skipForward,
  toggleMute
)

// ========== 頁面生命週期 ==========

// 載入逐字稿的包裝函數
async function loadTranscript(taskId) {
  const result = await loadTranscriptData(
    taskId,
    getAudioUrl,
    // (segs) => generateTimecodeMarkers(segs, currentTranscript.value.content)
    null
  )

  if (result) {
    if (result.audioUrl) {
      audioUrl.value = result.audioUrl
      audioError.value = null
    }
    // if (result.timecodeMarkers) {
    //   timecodeMarkers.value = result.timecodeMarkers
    //   if (result.timecodeMarkers.length > 0) {
    //     activeTimecodeIndex.value = 0
    //   }
    // }

    // 生成segment標記（僅在段落模式下）
    if (displayMode.value === 'paragraph' && segments.value && currentTranscript.value.content) {
      generateSegmentMarkers(segments.value, currentTranscript.value.content)
    }
  }
}

// 儲存編輯的包裝函數
async function saveEditing() {
  let contentToSave = ''
  let segmentsToSave = null

  if (displayMode.value === 'paragraph') {
    // 從 contenteditable div 中提取純文字內容（排除標記元素）
    if (textareaRef.value) {
      contentToSave = extractTextContent(textareaRef.value)
      // 更新到 currentTranscript
      currentTranscript.value.content = contentToSave
    } else {
      contentToSave = currentTranscript.value.content
    }
  } else {
    // 字幕模式：只更新 segments，不更新純文字檔案
    // contentToSave = convertTableToPlainText(groupedSegments.value, speakerNames.value)
    contentToSave = originalContent.value // 保持原有的純文字內容不變
    segmentsToSave = reconstructSegmentsFromGroups(groupedSegments.value)
  }

  const success = await saveTranscript(contentToSave, segmentsToSave, displayMode.value)

  if (success) {
    finishEditing()

    // 如果有更新 segments，也要更新本地的 segments 資料
    if (segmentsToSave) {
      segments.value = segmentsToSave
    }
  }
}

// 儲存任務名稱的包裝函數
async function saveTaskName() {
  const success = await updateTaskName(editingTaskName.value)
  if (success || !success) {
    // 無論成功或失敗都關閉編輯模式
    isEditingTitle.value = false
  }
}

// 下載逐字稿
function downloadTranscript() {
  if (displayMode.value === 'subtitle') {
    openDownloadDialog()
  } else {
    const filename = currentTranscript.value.custom_name || currentTranscript.value.filename || 'transcript'
    downloadParagraphMode(currentTranscript.value.content, filename)
  }
}

// 執行下載（從對話框）
function performDownload() {
  // 根據用戶選擇決定是否包含講者資訊
  // null 表示不顯示講者，{} 或 speakerNames 表示顯示講者（使用自定義名稱或原始代號）
  const speakerNamesToUse = includeSpeaker.value ? speakerNames.value : null
  const filename = currentTranscript.value.custom_name || currentTranscript.value.filename || 'transcript'

  let content = ''
  const format = selectedDownloadFormat.value

  // 根據選擇的格式生成對應的內容
  if (format === 'srt') {
    content = generateSRTText(groupedSegments.value, speakerNamesToUse)
  } else if (format === 'vtt') {
    content = generateVTTText(groupedSegments.value, speakerNamesToUse)
  } else {
    // TXT 格式：使用用戶當前選擇的時間格式
    content = generateSubtitleText(groupedSegments.value, timeFormat.value, speakerNamesToUse)
  }

  performSubtitleDownload(content, filename, format)
}

// 更新 segment 的講者
function updateSegmentSpeaker({ groupId, newSpeaker }) {
  // 找到對應的 group
  const group = groupedSegments.value.find(g => g.id === groupId)
  if (!group) return

  // 更新該 group 中所有 segments 的 speaker
  group.speaker = newSpeaker
  group.segments.forEach(segment => {
    segment.speaker = newSpeaker
  })

  // 更新原始 segments 數據
  segments.value = segments.value.map(seg => {
    const groupSegment = group.segments.find(gs =>
      gs.start === seg.start && gs.end === seg.end && gs.text === seg.text
    )
    if (groupSegment) {
      return { ...seg, speaker: newSpeaker }
    }
    return seg
  })

  // 自動儲存到後端
  saveSegmentsToBackend()
}

// 儲存 segments 到後端
async function saveSegmentsToBackend() {
  try {
    await saveTranscript(
      currentTranscript.value.content,
      segments.value,
      'subtitle'
    )
    console.log('✅ ' + $t('transcriptDetail.segmentsAutoSaved'))
  } catch (error) {
    console.error('❌ ' + $t('transcriptDetail.errorSavingSegments') + ':', error)
  }
}

// 返回
function goBack() {
  router.back()
}

// 從 contenteditable div 中提取純文字內容（排除標記元素）
function extractTextContent(element) {
  // 克隆元素以避免修改原始 DOM
  const clone = element.cloneNode(true)

  // 移除所有的標記元素
  const markers = clone.querySelectorAll('.segment-marker')
  markers.forEach(marker => marker.remove())

  // 提取純文字
  return clone.innerText || ''
}

// 將文字內容分割成帶有標記的片段
function getContentParts() {
  const content = currentTranscript.value.content || ''

  // 關閉了 timecode 標記顯示時，返回純文字
  if (!showTimecodeMarkers.value || !segmentMarkers.value || segmentMarkers.value.length === 0) {
    return [{ text: content, isMarker: false }]
  }

  const parts = []
  let lastIndex = 0

  // 按照文字索引排序標記
  const sortedMarkers = [...segmentMarkers.value].sort((a, b) => a.textStartIndex - b.textStartIndex)

  sortedMarkers.forEach(marker => {
    // 添加標記之前的文字
    if (marker.textStartIndex > lastIndex) {
      parts.push({
        text: content.substring(lastIndex, marker.textStartIndex),
        isMarker: false
      })
    }

    // 添加帶標記的文字
    parts.push({
      text: marker.text,
      isMarker: true,
      start: marker.start,
      end: marker.end
    })

    lastIndex = marker.textEndIndex
  })

  // 添加最後剩餘的文字
  if (lastIndex < content.length) {
    parts.push({
      text: content.substring(lastIndex),
      isMarker: false
    })
  }

  return parts
}

// 處理標記點擊
function handleMarkerClick(startTime) {
  if (currentTranscript.value.hasAudio) {
    seekToTime(startTime)
  }
}

// 修復字幕模式編輯時的滾動問題
function fixSubtitleScrolling() {
  const wrapper = document.querySelector('.subtitle-table-wrapper')
  if (!wrapper) return

  const handleWheel = (e) => {
    const delta = e.deltaY
    wrapper.scrollTop += delta
    e.preventDefault()
  }

  const addScrollListeners = () => {
    const editableCells = wrapper.querySelectorAll('.col-content[contenteditable="true"]')
    editableCells.forEach(cell => {
      cell.addEventListener('wheel', handleWheel, { passive: false })
    })
  }

  addScrollListeners()

  const observer = new MutationObserver(() => {
    addScrollListeners()
  })

  observer.observe(wrapper, {
    childList: true,
    subtree: true,
    attributes: true,
    attributeFilter: ['contenteditable']
  })
}

// 路由離開前的警告
onBeforeRouteLeave((_to, _from, next) => {
  if (hasUnsavedChanges.value) {
    const answer = window.confirm($t('transcriptDetail.confirmLeave'))
    if (answer) {
      next()
    } else {
      next(false)
    }
  } else {
    next()
  }
})

// 初始載入
onMounted(() => {
  document.body.classList.add('transcript-detail-page')
  window.addEventListener('beforeunload', handleBeforeUnload)
  loadTranscript(route.params.taskId)

  // 延遲執行以確保 DOM 已渲染
  setTimeout(() => {
    fixSubtitleScrolling()
  }, 100) 
})

onUnmounted(() => {
  window.removeEventListener('beforeunload', handleBeforeUnload)
  document.body.classList.remove('editing-transcript')
  document.body.classList.remove('transcript-detail-page')
})

// 監聽路由參數變化
watch(() => route.params.taskId, (newTaskId) => {
  if (newTaskId) {
    loadTranscript(newTaskId)
  }
})

// 監聽編輯狀態變化，控制視窗高度
watch(isEditing, (editing) => {
  if (editing) {
    document.body.classList.add('editing-transcript')
  } else {
    document.body.classList.remove('editing-transcript')
  }
})

// 監聽segments和content變化，重新生成標記（僅在非編輯模式）
watch(
  () => [segments.value, currentTranscript.value.content, displayMode.value, isEditing.value],
  () => {
    if (displayMode.value === 'paragraph' && !isEditing.value && segments.value && currentTranscript.value.content) {
      generateSegmentMarkers(segments.value, currentTranscript.value.content)
    }
  },
  { deep: true }
)
</script>

<style scoped>
.transcript-detail-container {
  max-width: 1400px;
  margin: 0 auto;
  padding: 20px;
  height: 100vh;
  box-sizing: border-box;
  overflow: hidden;
}

/* 雙欄佈局 */
.transcript-layout {
  display: grid;
  grid-template-columns: 320px 1fr;
  gap: 20px;
  height: calc(100vh - 40px);
  align-items: start;
}

/* 左側控制面板 */
.left-panel {
  position: sticky;
  top: 20px;
  display: flex;
  flex-direction: column;
  gap: 5px;
  height: fit-content;
  max-height: calc(100vh - 40px);
  overflow-y: auto;
}

/* 右側文字區域 */
.right-panel {
  height: calc(100vh - 40px);
  display: flex;
  flex-direction: column;
  box-sizing: border-box;
  overflow: hidden;
}

/* 返回按鈕 */
.btn-back-icon {
  width: 44px;
  height: 44px;
  border: none;
  background: var(--neu-bg);
  border-radius: 12px;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.3s ease;
  color: var(--neu-primary);
}

.btn-back-icon:hover {
  transform: translateY(-2px);
}

.btn-back-icon:active {
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
  font-size: 1.5rem;
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
  color: var(--neu-primary);
}

.title-input {
  width: 100%;
  padding: 8px 12px;
  font-size: 1rem;
  font-weight: 400;
  border: 2px solid var(--neu-primary);
  border-radius: 8px;
  background: var(--neu-bg);
  color: var(--neu-text);
}

/* 段落模式控制項 */
.paragraph-controls {
  margin-top: 12px;
  padding-top: 12px;
  border-top: 1px solid rgba(163, 177, 198, 0.2);
}

.control-group {
  margin-bottom: 16px;
}

/* Toggle 標籤 */
.toggle-label {
  display: flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
  user-select: none;
}

.toggle-label.disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.toggle-checkbox {
  width: 16px;
  height: 16px;
  cursor: pointer;
  accent-color: var(--neu-primary);
}

.toggle-checkbox:disabled {
  cursor: not-allowed;
}

.toggle-text {
  font-size: 12px;
  font-weight: 500;
  color: var(--neu-text);
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
  cursor: pointer;
  font-size: 14px;
  font-weight: 600;
  transition: all 0.3s ease;
  width: fit-content;
  align-self: center;
}

.btn-action:hover {
  color: var(--neu-primary-dark);
  transform: translateY(-2px);
}

.btn-action:active {
  transform: translateY(0);
}

.btn-action svg {
  stroke: currentColor;
  flex-shrink: 0;
}

/* 逐字稿內容 */
.transcript-content-wrapper {
  position: relative;
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: visible;
  min-height: 0;
}

/* .timecode-fixed-display {
  position: absolute;
  top: calc(25% - 33px);
  right: 20px;
  display: flex;
  align-items: center;
  gap: 8px;
  background: rgba(255, 219, 184, 0.15);
  border-radius: 8px;
  padding: 8px 12px;
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.08),
              0 0 0 1px rgba(255, 255, 255, 0.15) inset;
  cursor: pointer;
  transition: all 0.3s ease;
  z-index: 100;
  backdrop-filter: blur(5px) saturate(10%);
  -webkit-backdrop-filter: blur(16px) saturate(200%);
}

.timecode-fixed-display:hover {
  transform: translateY(0%) translateX(-2px);
}

.timecode-label {
  font-size: 0.9rem;
  font-weight: 600;
  color: var(--neu-primary);
} */

.textarea-wrapper {
  position: relative;
  width: 100%;
  flex: 1;
  min-height: 0;
}

/* .textarea-wrapper.show-reference-line::before {
  content: '';
  position: absolute;
  top: 25%;
  left: 0;
  right: 0;
  height: 2px;
  background: linear-gradient(90deg, transparent, #ff6b35, transparent);
  z-index: 5;
  pointer-events: none;
} */

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
}

.transcript-textarea.editing {
  background: var(--upload-bg);
  box-shadow: 0 0 0 2px var(--neu-primary);
}

.transcript-textarea[readonly] {
  cursor: default;
}

/* 非編輯模式的文字顯示區 */
.transcript-display {
  width: 100%;
  height: 100%;
  padding: 20px;
  border: none;
  border-radius: 12px;
  background: var(--neu-bg);
  color: var(--neu-text);
  font-size: 1rem;
  line-height: 1.8;
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
  overflow-y: auto;
  overflow-x: hidden;
  white-space: pre-wrap;
  word-wrap: break-word;
  box-sizing: border-box;
  outline: none;
  cursor: text;
}

.transcript-display.editing {
  background: var(--upload-bg);
  box-shadow: 0 0 0 2px var(--neu-primary);
}

/* 文字片段 */
.text-part {
  display: inline;
}

/* 標記包裝器 */
.marker-wrapper {
  position: relative;
  display: inline;
}

/* Segment 標記 */
.segment-marker {
  position: relative;
  display: inline-block;
  width: 8px;
  height: 8px;
  margin-right: 2px;
  vertical-align: super;
  cursor: pointer;
  color: var(--neu-primary);
  opacity: 0.4;
  transition: all 0.2s ease;
  font-size: 8px;
  line-height: 1;
  user-select: none;
  -webkit-user-select: none;
}

.segment-marker:hover {
  opacity: 1;
  transform: scale(1.3);
  color: var(--neu-primary-dark);
}

.segment-marker svg {
  display: block;
  width: 100%;
  height: 100%;
}

/* Timecode Tooltip */
.timecode-tooltip {
  position: absolute;
  bottom: 100%;
  left: 50%;
  transform: translateX(-50%) translateY(-4px);
  padding: 4px 8px;
  background: rgba(0, 0, 0, 0.85);
  color: white;
  border-radius: 4px;
  font-size: 11px;
  font-weight: 500;
  white-space: nowrap;
  pointer-events: none;
  opacity: 0;
  transition: opacity 0.2s ease;
  z-index: 1000;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.2);
}

.segment-marker:hover .timecode-tooltip {
  opacity: 1;
}

/* Tooltip 箭頭 */
.timecode-tooltip::after {
  content: '';
  position: absolute;
  top: 100%;
  left: 50%;
  transform: translateX(-50%);
  border: 4px solid transparent;
  border-top-color: rgba(0, 0, 0, 0.85);
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
}
</style>
