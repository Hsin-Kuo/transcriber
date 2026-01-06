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
          <button v-if="!isEditing" @click="handleStartEditing" class="btn btn-action">
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
          <button v-if="isEditing" @click="handleCancelEditing" class="btn btn-action">
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
              :key="`transcript-${showTimecodeMarkers}-${isEditing}-${contentVersion}`"
              ref="textareaRef"
              @keydown="handleContentEditableKeyDown"
            >
              <template v-for="(part, index) in getContentParts()" :key="index">
                <span v-if="!part.isMarker" class="text-part">{{ part.text }}</span>
                <span v-else class="marker-wrapper"><span
                    v-if="showTimecodeMarkers"
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
                  </span><span
                    class="text-part"
                    :class="{ 'clickable': isAltPressed && currentTranscript.hasAudio }"
                    @click="handleTextClick(part.start, $event)"
                  >{{ part.text }}<span v-if="isAltPressed && currentTranscript.hasAudio" class="text-timecode-tooltip">
                      {{ formatTime(part.start) }}
                    </span></span>
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
          @replace-all="handleReplaceAll"
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
  duration,
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
  titleInput, // 用於 template ref
  startTitleEdit,
  cancelTitleEdit,
  startEditing,
  cancelEditing,
  finishEditing,
  replaceAll,
  handleBeforeUnload
} = useTranscriptEditor(currentTranscript, originalContent, displayMode, groupedSegments, convertTableToPlainText)

// 重新定義 hasUnsavedChanges，檢查實際的 DOM 內容
const hasUnsavedChanges = computed(() => {
  if (!isEditing.value) return false

  if (displayMode.value === 'paragraph') {
    // 段落模式：從 contenteditable div 提取實際內容並比較
    if (!textareaRef.value) return false
    const currentContent = extractTextContent(textareaRef.value)
    return currentContent !== originalContent.value
  } else if (displayMode.value === 'subtitle') {
    // 字幕模式：比較表格內容
    const currentContent = convertTableToPlainText(groupedSegments.value)
    return currentContent !== originalContent.value
  }

  return false
})

// ========== Segment 標記 ==========
const {
  segmentMarkers,
  textareaRef,
  generateSegmentMarkers,
  formatTime
} = useSegmentMarkers()

// 控制是否顯示 timecode 標記
const showTimecodeMarkers = ref(true)

// 保存編輯前的 timecode markers 狀態
const savedTimecodeMarkersState = ref(true)

// 控制 Alt 鍵狀態（用於點擊句子跳轉）
const isAltPressed = ref(false)

// 內容版本號（用於強制重新渲染 contenteditable）
const contentVersion = ref(0)

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
  toggleMute,
  setPlaybackRate,
  playbackRate
)

// ========== 頁面生命週期 ==========

// 載入逐字稿的包裝函數
async function loadTranscript(taskId) {
  const result = await loadTranscriptData(
    taskId,
    getAudioUrl,
    null
  )

  if (result) {
    if (result.audioUrl) {
      audioUrl.value = result.audioUrl
      audioError.value = null
    }

    // 生成segment標記（僅在段落模式下）
    if (displayMode.value === 'paragraph' && segments.value && currentTranscript.value.content) {
      generateSegmentMarkers(segments.value, currentTranscript.value.content)
    }
  }
}

// 開始編輯的包裝函數（保存滾動位置）
function handleStartEditing() {
  // 保存滾動位置（段落模式）
  let savedScrollTop = 0
  if (displayMode.value === 'paragraph' && textareaRef.value) {
    savedScrollTop = textareaRef.value.scrollTop
  }

  // 保存 timecode markers 狀態，並在編輯模式下關閉（避免 IME 輸入問題）
  if (displayMode.value === 'paragraph') {
    savedTimecodeMarkersState.value = showTimecodeMarkers.value
    showTimecodeMarkers.value = false
  }

  // 調用原始的 startEditing
  startEditing()

  // 恢復滾動位置
  if (displayMode.value === 'paragraph' && savedScrollTop > 0) {
    setTimeout(() => {
      if (textareaRef.value) {
        textareaRef.value.scrollTop = savedScrollTop
      }
    }, 100)
  }
}

// 取消編輯的包裝函數（保存滾動位置）
function handleCancelEditing() {
  // 保存滾動位置（段落模式）
  let savedScrollTop = 0
  if (displayMode.value === 'paragraph' && textareaRef.value) {
    savedScrollTop = textareaRef.value.scrollTop
  }

  // 調用原始的 cancelEditing
  cancelEditing()

  // 恢復 timecode markers 狀態
  if (displayMode.value === 'paragraph') {
    showTimecodeMarkers.value = savedTimecodeMarkersState.value
  }

  // 恢復滾動位置
  if (displayMode.value === 'paragraph' && savedScrollTop > 0) {
    setTimeout(() => {
      if (textareaRef.value) {
        textareaRef.value.scrollTop = savedScrollTop
      }
    }, 100)
  }
}

// 儲存編輯的包裝函數
async function saveEditing() {
  let contentToSave = ''
  let segmentsToSave = null

  // 保存滾動位置（段落模式）
  let savedScrollTop = 0
  if (displayMode.value === 'paragraph' && textareaRef.value) {
    // 滾動發生在 .transcript-display 元素本身
    savedScrollTop = textareaRef.value.scrollTop
  }

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

    // 恢復 timecode markers 狀態
    if (displayMode.value === 'paragraph') {
      showTimecodeMarkers.value = savedTimecodeMarkersState.value
    }

    // 恢復滾動位置（段落模式）
    if (displayMode.value === 'paragraph' && savedScrollTop > 0) {
      // 使用 setTimeout 給 DOM 更多時間重新渲染
      setTimeout(() => {
        if (textareaRef.value) {
          textareaRef.value.scrollTop = savedScrollTop
        }
      }, 100)
    }
  }
}

// 儲存任務名稱的包裝函數
async function saveTaskName() {
  await updateTaskName(editingTaskName.value)
  // 無論成功或失敗都關閉編輯模式
  isEditingTitle.value = false
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
  // 克隆元素以避免修改原始 DOM，防止 Vue 更新時出錯
  const clone = element.cloneNode(true)

  let text = ''

  function traverseNode(node) {
    // 跳過 segment-marker 元素及其內容
    if (node.classList && node.classList.contains('segment-marker')) {
      return
    }

    // 跳過 text-timecode-tooltip 元素（Alt 模式的 tooltip）
    if (node.classList && node.classList.contains('text-timecode-tooltip')) {
      return
    }

    // 處理文字節點
    if (node.nodeType === Node.TEXT_NODE) {
      text += node.textContent
      return
    }

    // 處理 <br> 標籤
    if (node.nodeName === 'BR') {
      text += '\n'
      return
    }

    // 處理塊級元素（div）- 在前面添加換行（如果不是第一個元素）
    if (node.nodeName === 'DIV' && text.length > 0 && !text.endsWith('\n')) {
      text += '\n'
    }

    // 遞歸處理子節點（使用 Array.from 避免 NodeList 被修改）
    const children = Array.from(node.childNodes)
    for (let child of children) {
      traverseNode(child)
    }

    // 處理塊級元素（div）- 在後面添加換行（如果內容不為空且不是只有 br）
    if (node.nodeName === 'DIV' && node.childNodes.length > 0) {
      // 檢查 div 是否只包含 <br>
      const hasOnlyBr = node.childNodes.length === 1 && node.childNodes[0].nodeName === 'BR'
      if (!hasOnlyBr && !text.endsWith('\n')) {
        text += '\n'
      }
    }
  }

  // 從克隆的根元素開始遍歷
  const children = Array.from(clone.childNodes)
  for (let child of children) {
    traverseNode(child)
  }

  // 移除零寬度空格（用於修復中文輸入）
  return text.replace(/\u200B/g, '')
}

// 處理取代全部（段落模式專用）
function handleReplaceAll() {
  if (displayMode.value === 'paragraph') {
    // 如果沒有輸入查找文字，直接返回
    if (!findText.value) {
      return
    }

    // 從 contenteditable div 提取當前的純文字（排除標記）
    let contentToReplace = currentTranscript.value.content
    if (textareaRef.value) {
      contentToReplace = extractTextContent(textareaRef.value)
    }

    // 計算會取代多少處
    const regex = new RegExp(findText.value, 'g')
    const matches = contentToReplace.match(regex)
    const matchCount = matches ? matches.length : 0

    // 如果沒有找到，提示用戶
    if (matchCount === 0) {
      alert(`找不到「${findText.value}」`)
      return
    }

    // 顯示確認對話框
    const confirmMessage = `找到 ${matchCount} 處「${findText.value}」\n確定全部取代為「${replaceText.value}」嗎？`
    if (!confirm(confirmMessage)) {
      return // 用戶取消
    }

    // 保存滾動位置
    let savedScrollTop = 0
    if (textareaRef.value) {
      savedScrollTop = textareaRef.value.scrollTop
    }

    // ✅ 只更新一次: 先執行替換,再賦值
    const replacedContent = contentToReplace.replace(regex, replaceText.value)
    currentTranscript.value.content = replacedContent  // 只觸發一次 reactive 更新

    // 清空舊標記，避免混合新舊索引
    segmentMarkers.value = []

    // 增加版本號，強制 Vue 重新渲染 contenteditable（避免舊內容殘留）
    contentVersion.value++

    // 重新生成標記（使用取代後的內容）
    if (segments.value && currentTranscript.value.content) {
      generateSegmentMarkers(segments.value, currentTranscript.value.content)
    }

    // 恢復滾動位置
    if (savedScrollTop > 0) {
      nextTick(() => {
        if (textareaRef.value) {
          textareaRef.value.scrollTop = savedScrollTop
        }
      })
    }

    // 清空輸入框
    findText.value = ''
    replaceText.value = ''
  } else {
    // 字幕模式直接使用原本的取代邏輯
    replaceAll()

    // 清空輸入框
    findText.value = ''
    replaceText.value = ''
  }
}

// 將文字內容分割成帶有標記的片段
function getContentParts() {
  const content = currentTranscript.value.content || ''

  // 如果沒有 segment 資料,返回純文字
  if (!segmentMarkers.value || segmentMarkers.value.length === 0) {
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
    // isMarker: true 表示這是一個 segment,不論是否顯示標記
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

// 處理文字點擊（當 Alt 鍵按下時）
function handleTextClick(startTime, event) {
  // Alt 鍵按下 + 有音訊時才跳轉
  if (isAltPressed.value && currentTranscript.value.hasAudio) {
    // 在編輯模式下，阻止預設行為以避免游標移動
    if (isEditing.value && event) {
      event.preventDefault()
    }
    seekToTime(startTime)
  }
}

// 鍵盤事件處理
function handleKeyDown(e) {
  if (e.altKey) {
    isAltPressed.value = true

    // 防止 Alt 組合鍵的預設瀏覽器行為（如輸入特殊字符）
    // 只針對我們有定義快捷鍵的按鍵
    const shortcutKeys = [' ', 'm', 'M', ',', '.', 'ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown']
    if (shortcutKeys.includes(e.key)) {
      e.preventDefault()
      e.stopPropagation() // 阻止事件繼續傳播，避免 contenteditable 插入字元
    }
  }
}

function handleKeyUp(e) {
  if (!e.altKey) {
    isAltPressed.value = false
  }
}

// 處理視窗失焦（確保 Alt 鍵狀態重置）
function handleBlur() {
  isAltPressed.value = false
}

// 處理 contenteditable 區域的按鍵事件
function handleContentEditableKeyDown(e) {
  if (!e.altKey) return

  // Alt + Space: 播放/暫停
  if (e.key === ' ') {
    e.preventDefault()
    e.stopPropagation()
    if (hasAudio.value && audioElement.value) {
      togglePlayPause()
    }
    return
  }

  // Alt + ArrowUp: 加速播放
  if (e.key === 'ArrowUp') {
    e.preventDefault()
    e.stopPropagation()
    const newRate = Math.min(2, playbackRate.value + 0.25)
    setPlaybackRate(newRate)
    return
  }

  // Alt + ArrowDown: 減速播放
  if (e.key === 'ArrowDown') {
    e.preventDefault()
    e.stopPropagation()
    const newRate = Math.max(0.25, playbackRate.value - 0.25)
    setPlaybackRate(newRate)
    return
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
  // 註冊 Alt 鍵監聽
  window.addEventListener('keydown', handleKeyDown)
  window.addEventListener('keyup', handleKeyUp)
  window.addEventListener('blur', handleBlur)

  loadTranscript(route.params.taskId)

  // 延遲執行以確保 DOM 已渲染
  setTimeout(() => {
    fixSubtitleScrolling()
  }, 100)
})

onUnmounted(() => {
  window.removeEventListener('beforeunload', handleBeforeUnload)
  // 移除 Alt 鍵監聽
  window.removeEventListener('keydown', handleKeyDown)
  window.removeEventListener('keyup', handleKeyUp)
  window.removeEventListener('blur', handleBlur)

  document.body.classList.remove('editing-transcript')
  document.body.classList.remove('transcript-detail-page')
})

// 監聽路由參數變化
watch(() => route.params.taskId, (newTaskId, oldTaskId) => {
  if (newTaskId && newTaskId !== oldTaskId) {
    // 如果有未儲存的變更，先確認
    if (hasUnsavedChanges.value) {
      const answer = window.confirm($t('transcriptDetail.confirmLeave'))
      if (!answer) {
        // 使用者取消，恢復到原來的任務
        router.replace({ name: 'transcript-detail', params: { taskId: oldTaskId } })
        return
      }
    }
    // 載入新任務
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
  overflow-x: visible;
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

/* 操作按鈕 */
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

.textarea-wrapper {
  position: relative;
  width: 100%;
  flex: 1;
  min-height: 0;
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
  position: relative;
  padding: 1px 3px; /* 預先保留空間，避免 Alt 切換時文字重排 */
  border-radius: 3px;
  transition: background-color 0.2s ease;
}

/* Alt 鍵按下時的可點擊文字樣式 */
.text-part.clickable {
  background-color: rgba(196, 140, 226, 0.175);
  cursor: pointer;
}

.text-part.clickable:hover {
  background-color: rgba(163, 177, 198, 0.25);
}

/* 文字部分的 Timecode Tooltip */
.text-timecode-tooltip {
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

.text-part.clickable:hover .text-timecode-tooltip {
  opacity: 1;
}

/* Tooltip 箭頭 */
.text-timecode-tooltip::after {
  content: '';
  position: absolute;
  top: 100%;
  left: 50%;
  transform: translateX(-50%);
  border: 4px solid transparent;
  border-top-color: rgba(0, 0, 0, 0.85);
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
  user-select: none !important;
  -webkit-user-select: none !important;
  -moz-user-select: none !important;
  -ms-user-select: none !important;
}

/* 標記內所有元素都不可選中 */
.segment-marker * {
  user-select: none !important;
  -webkit-user-select: none !important;
  -moz-user-select: none !important;
  -ms-user-select: none !important;
}

/* 編輯模式下標記仍可點擊 */
.editing .segment-marker {
  cursor: pointer;
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
