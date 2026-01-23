<template>
  <div class="transcript-detail-container">
    <!-- 固定頂部 Header -->
    <TranscriptHeader
      ref="headerRef"
      :task-display-name="currentTranscript.custom_name || currentTranscript.filename || $t('transcriptDetail.transcript')"
      :created-at="currentTranscript.created_at"
      :text-length="currentTranscript.text_length"
      :duration-text="currentTranscript.duration_text"
      :is-editing="isEditing"
      :is-editing-title="isEditingTitle"
      :editing-task-name="editingTaskName"
      :display-mode="displayMode"
      :show-timecode-markers="showTimecodeMarkers"
      :time-format="timeFormat"
      :density-threshold="densityThreshold"
      :speaker-names="speakerNames"
      :has-speaker-info="hasSpeakerInfo"
      :unique-speakers="uniqueSpeakers"
      :search-text="searchText"
      :replace-text="replaceText"
      :total-matches="searchMatches.length"
      :current-match-index="currentMatchIndex"
      :match-case="matchCase"
      :match-whole-word="matchWholeWord"
      @go-back="goBack"
      @start-title-edit="startTitleEdit"
      @save-task-name="saveTaskName"
      @cancel-title-edit="cancelTitleEdit"
      @update:editing-task-name="editingTaskName = $event"
      @start-editing="handleStartEditing"
      @save-editing="saveEditing"
      @cancel-editing="handleCancelEditing"
      @download="downloadTranscript"
      @update:show-timecode-markers="showTimecodeMarkers = $event"
      @update:time-format="timeFormat = $event"
      @update:density-threshold="densityThreshold = $event"
      @update:speaker-names="speakerNames = $event"
      @update:search-text="searchText = $event"
      @update:replace-text="replaceText = $event"
      @update:match-case="matchCase = $event"
      @update:match-whole-word="matchWholeWord = $event"
      @search="handleSearch"
      @go-to-previous="goToPreviousMatch"
      @go-to-next="goToNextMatch"
      @replace-current="handleReplaceCurrent"
      @replace-all="handleReplaceAllNew"
    />

    <!-- 雙欄佈局 -->
    <div class="transcript-layout">
      <!-- 左側控制面板 -->
      <div class="left-panel card">
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
            <!-- 替換中的過渡狀態（用於完全卸載 contenteditable 避免 Vue DOM 同步問題） -->
            <div v-if="isReplacing" class="transcript-display replacing-state">
              <span class="replacing-indicator">{{ $t('transcriptDetail.replacing') || '正在替換...' }}</span>
            </div>
            <!-- 編輯模式：保留 segment 標記的 contenteditable -->
            <div
              v-else-if="isEditing"
              class="transcript-display editing"
              contenteditable="true"
              :key="`transcript-editing-${contentVersion}`"
              ref="textareaRef"
              @keydown="handleContentEditableKeyDown"
            ><template v-for="(part, index) in getContentPartsForEditing()" :key="`edit-${index}`"><span v-if="!part.isMarker">{{ part.text }}</span><span
                v-else
                class="segment-text"
                :class="{ 'clickable': isAltPressed && currentTranscript.hasAudio }"
                :data-segment-index="part.segmentIndex"
                :data-start-time="part.start"
                @click="handleTextClick(part.start, $event)"
              >{{ part.text }}<span
                  v-if="isAltPressed && currentTranscript.hasAudio"
                  class="text-timecode-tooltip"
                  contenteditable="false"
                >{{ formatTime(part.start) }}</span></span></template></div>
            <!-- 非編輯模式：使用 v-for 渲染高亮和標記 -->
            <div
              v-else
              class="transcript-display"
              :key="`transcript-${showTimecodeMarkers}-${contentVersion}`"
              ref="textareaRef"
            >
              <template v-for="(part, index) in getContentPartsWithHighlight()" :key="`part-${contentVersion}-${index}`">
                <span v-if="!part.isMarker && !part.isHighlight" class="text-part">{{ part.text }}</span>
                <span
                  v-else-if="part.isHighlight"
                  class="search-highlight"
                  :class="{ 'current': part.isCurrent }"
                >{{ part.text }}</span>
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
                  </span><template v-for="(subPart, subIndex) in splitTextWithHighlight(part.text, part.segmentIndex)" :key="`sub-${subIndex}`">
                    <span
                      v-if="subPart.isHighlight"
                      class="search-highlight"
                      :class="{ 'current': subPart.isCurrent }"
                    >{{ subPart.text }}</span>
                    <span
                      v-else
                      class="text-part"
                      :class="{ 'clickable': isAltPressed && currentTranscript.hasAudio }"
                      :data-segment-index="part.segmentIndex"
                      :data-start-time="part.start"
                      @click="handleTextClick(part.start, $event)"
                    >{{ subPart.text }}<span v-if="isAltPressed && currentTranscript.hasAudio && subIndex === 0" class="text-timecode-tooltip">
                        {{ formatTime(part.start) }}
                      </span></span>
                  </template>
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
            @open-speaker-settings="handleOpenSpeakerSettings"
          />
        </div>

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
import TranscriptHeader from '../components/transcript/TranscriptHeader.vue'
import AudioPlayer from '../components/transcript/AudioPlayer.vue'
import SubtitleTable from '../components/transcript/SubtitleTable.vue'
import DownloadDialog from '../components/transcript/DownloadDialog.vue'

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

// 組件引用
const audioPlayerRef = ref(null)
const headerRef = ref(null)

// ========== 數據管理 ==========
const {
  currentTranscript,
  segments,
  speakerNames,
  subtitleSettings,
  loadingTranscript,
  transcriptError,
  originalContent,
  loadTranscript: loadTranscriptData,
  saveTranscript,
  updateTaskName,
  updateSpeakerNames,
  updateSubtitleSettings
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
  startTitleEdit,
  cancelTitleEdit,
  startEditing,
  cancelEditing,
  finishEditing,
  handleBeforeUnload
} = useTranscriptEditor(currentTranscript, originalContent, displayMode, groupedSegments, convertTableToPlainText)

// ========== 搜尋/取代功能 ==========
const searchText = ref('')
const replaceText = ref('')
const searchMatches = ref([]) // 存放所有匹配的位置 { start, end }
const currentMatchIndex = ref(0)
const matchCase = ref(false)
const matchWholeWord = ref(false)

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
const showTimecodeMarkers = ref(false)

// 保存編輯前的 timecode markers 狀態
const savedTimecodeMarkersState = ref(true)

// 控制 Alt 鍵狀態（用於點擊句子跳轉）
const isAltPressed = ref(false)

// 計算唯一講者列表（用於字幕模式設定）
const uniqueSpeakers = computed(() => {
  if (!segments.value || segments.value.length === 0) return []
  const speakers = new Set()
  segments.value.forEach(seg => {
    if (seg.speaker) {
      speakers.add(seg.speaker)
    }
  })
  return Array.from(speakers).sort()
})

// 內容版本號（用於強制重新渲染 contenteditable）
const contentVersion = ref(0)

// 是否正在執行替換（用於暫時卸載 contenteditable 避免 Vue DOM 同步問題）
const isReplacing = ref(false)

// 保存編輯前的 segments 狀態（用於取消編輯時恢復）
const originalSegments = ref([])

// 講者名稱自動儲存（debounced）
let speakerNamesSaveTimer = null
// 疏密度自動儲存（debounced）
let densityThresholdSaveTimer = null
// 用於追蹤滾動位置恢復的計時器（以便在 unmount 時清理）
let scrollRestoreTimers = []
// 追蹤組件是否已卸載
let isMounted = true
// 追蹤是否正在初始化（避免載入時觸發儲存）
let isInitializing = true

watch(speakerNames, (newValue) => {
  // 只有在字幕模式下才需要自動儲存
  if (displayMode.value !== 'subtitle') return

  // 清除之前的計時器
  if (speakerNamesSaveTimer) {
    clearTimeout(speakerNamesSaveTimer)
  }

  // 設定新的計時器（1秒後儲存）
  speakerNamesSaveTimer = setTimeout(async () => {
    if (!isMounted) return // 如果組件已卸載，不執行
    console.log('🔄 ' + $t('transcriptDetail.autoSavingSpeaker') + ':', newValue)
    await updateSpeakerNames(newValue)
  }, 1000)
}, { deep: true })

// 疏密度自動儲存（僅在字幕模式下，且非初始化階段）
watch(densityThreshold, (newValue) => {
  // 只有在字幕模式下才需要自動儲存
  if (displayMode.value !== 'subtitle') return
  // 初始化階段不儲存
  if (isInitializing) return

  // 清除之前的計時器
  if (densityThresholdSaveTimer) {
    clearTimeout(densityThresholdSaveTimer)
  }

  // 設定新的計時器（1秒後儲存）
  densityThresholdSaveTimer = setTimeout(async () => {
    if (!isMounted) return // 如果組件已卸載，不執行
    console.log('🔄 自動儲存疏密度設定:', newValue)
    await updateSubtitleSettings({ density_threshold: newValue })
  }, 1000)
})

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
  // 標記為初始化階段
  isInitializing = true

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

    // 應用已儲存的字幕設定（僅在字幕模式下）
    if (displayMode.value === 'subtitle' && subtitleSettings.value) {
      if (subtitleSettings.value.density_threshold !== undefined) {
        densityThreshold.value = subtitleSettings.value.density_threshold
        console.log('✅ 已應用儲存的疏密度設定:', densityThreshold.value)
      }
    }
  }

  // 延遲結束初始化狀態，確保 watch 不會在載入階段觸發
  nextTick(() => {
    isInitializing = false
  })
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

  // 保存原始的 segments 狀態（以便取消時恢復）
  if (segments.value.length > 0) {
    // 深拷貝 segments 以避免引用問題
    originalSegments.value = JSON.parse(JSON.stringify(segments.value))
  }

  // 調用原始的 startEditing
  startEditing()

  // 恢復滾動位置
  if (displayMode.value === 'paragraph' && savedScrollTop > 0) {
    const timerId = setTimeout(() => {
      if (!isMounted) return
      if (textareaRef.value) {
        textareaRef.value.scrollTop = savedScrollTop
      }
    }, 100)
    scrollRestoreTimers.push(timerId)
  }

  // 如果有搜尋結果，應用 CSS 高亮
  if (displayMode.value === 'paragraph' && searchMatches.value.length > 0) {
    nextTick(() => {
      applySearchHighlightsWithCSS()
    })
  }
}

// 取消編輯的包裝函數（保存滾動位置）
function handleCancelEditing() {
  // 清除 CSS 高亮
  if (CSS.highlights) {
    CSS.highlights.delete('search-highlight')
    CSS.highlights.delete('search-highlight-current')
  }

  // 保存滾動位置（段落模式）
  let savedScrollTop = 0
  if (displayMode.value === 'paragraph' && textareaRef.value) {
    savedScrollTop = textareaRef.value.scrollTop
  }

  // 恢復原始的 segments 狀態
  if (originalSegments.value.length > 0) {
    segments.value = JSON.parse(JSON.stringify(originalSegments.value))
    // 清空備份
    originalSegments.value = []
  }

  // 調用原始的 cancelEditing
  cancelEditing()

  // 恢復 timecode markers 狀態
  if (displayMode.value === 'paragraph') {
    showTimecodeMarkers.value = savedTimecodeMarkersState.value
  }

  // 恢復滾動位置
  if (displayMode.value === 'paragraph' && savedScrollTop > 0) {
    const timerId = setTimeout(() => {
      if (!isMounted) return
      if (textareaRef.value) {
        textareaRef.value.scrollTop = savedScrollTop
      }
    }, 100)
    scrollRestoreTimers.push(timerId)
  }

  // 如果有搜尋內容，重新搜尋以更新匹配位置
  if (searchText.value) {
    nextTick(() => {
      handleSearch(searchText.value)
    })
  }
}

// 儲存編輯的包裝函數
async function saveEditing() {
  // 清除 CSS 高亮
  if (CSS.highlights) {
    CSS.highlights.delete('search-highlight')
    CSS.highlights.delete('search-highlight-current')
  }

  let contentToSave = ''
  let segmentsToSave = null

  // 保存滾動位置（段落模式）
  let savedScrollTop = 0
  if (displayMode.value === 'paragraph' && textareaRef.value) {
    // 滾動發生在 .transcript-display 元素本身
    savedScrollTop = textareaRef.value.scrollTop
  }

  if (displayMode.value === 'paragraph') {
    // 從 contenteditable div 中提取純文字內容
    if (textareaRef.value) {
      contentToSave = extractTextContent(textareaRef.value)

      // 更新到 currentTranscript
      currentTranscript.value.content = contentToSave

      // 如果有 segments 資料，使用差異比對來更新 segments
      if (segments.value && segments.value.length > 0 && segmentMarkers.value.length > 0) {
        const updatedSegments = updateSegmentsFromTextDiff(
          originalContent.value,
          contentToSave,
          segments.value,
          segmentMarkers.value
        )

        if (updatedSegments) {
          segmentsToSave = updatedSegments
        }
      }
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

    // 清空 segments 備份
    originalSegments.value = []

    // 恢復 timecode markers 狀態
    if (displayMode.value === 'paragraph') {
      showTimecodeMarkers.value = savedTimecodeMarkersState.value
    }

    // 恢復滾動位置（段落模式）
    if (displayMode.value === 'paragraph' && savedScrollTop > 0) {
      // 使用 setTimeout 給 DOM 更多時間重新渲染
      const timerId = setTimeout(() => {
        if (!isMounted) return
        if (textareaRef.value) {
          textareaRef.value.scrollTop = savedScrollTop
        }
      }, 100)
      scrollRestoreTimers.push(timerId)
    }

    // 如果有搜尋內容，重新搜尋以更新匹配位置
    if (searchText.value) {
      nextTick(() => {
        handleSearch(searchText.value)
      })
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

// 打開講者設置面板（從 SubtitleTable 的重新命名按鈕觸發）
function handleOpenSpeakerSettings(speakerCode) {
  console.log('🔧 打開講者設置面板，當前講者:', speakerCode)
  // 打開 Header 的更多選項面板，並 focus 到該講者的輸入框
  if (headerRef.value) {
    headerRef.value.openMoreOptions(speakerCode)
  }
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

/**
 * 找出兩段文字之間的編輯區域
 * @param {string} oldText - 原始文字
 * @param {string} newText - 新文字
 * @returns {Object} 編輯區域資訊
 */
function findEditRegion(oldText, newText) {
  // 找出從頭開始第一個不同的位置
  let startDiff = 0
  while (startDiff < oldText.length && startDiff < newText.length &&
         oldText[startDiff] === newText[startDiff]) {
    startDiff++
  }

  // 找出從尾部開始第一個不同的位置
  let endDiffOld = oldText.length
  let endDiffNew = newText.length
  while (endDiffOld > startDiff && endDiffNew > startDiff &&
         oldText[endDiffOld - 1] === newText[endDiffNew - 1]) {
    endDiffOld--
    endDiffNew--
  }

  return {
    startDiff,              // 編輯開始位置
    oldEndDiff: endDiffOld, // 原始文字的編輯結束位置
    newEndDiff: endDiffNew  // 新文字的編輯結束位置
  }
}

/**
 * 使用文字差異比對來更新 segments
 * @param {string} oldText - 原始文字
 * @param {string} newText - 新文字
 * @param {Array} segments - 原始 segments
 * @param {Array} markers - segment 標記（包含位置資訊）
 * @returns {Array|null} 更新後的 segments，如果沒有變更則返回 null
 */
function updateSegmentsFromTextDiff(oldText, newText, segments, markers) {
  if (oldText === newText) {
    return null // 沒有變更
  }

  const edit = findEditRegion(oldText, newText)
  const lengthDelta = newText.length - oldText.length

  // 按位置排序標記
  const sortedMarkers = [...markers].sort((a, b) => a.textStartIndex - b.textStartIndex)

  const updatedSegments = segments.map((seg) => ({ ...seg }))
  let hasChanges = false

  sortedMarkers.forEach((marker) => {
    const segIndex = marker.segmentIndex
    if (segIndex < 0 || segIndex >= updatedSegments.length) return

    let newStartIndex = marker.textStartIndex
    let newEndIndex = marker.textEndIndex

    if (marker.textEndIndex <= edit.startDiff) {
      // segment 完全在編輯區域之前，不受影響
      return
    } else if (marker.textStartIndex >= edit.oldEndDiff) {
      // segment 完全在編輯區域之後，需要調整位置
      newStartIndex += lengthDelta
      newEndIndex += lengthDelta
    } else {
      // segment 與編輯區域重疊，需要重新計算
      if (marker.textStartIndex < edit.startDiff) {
        // segment 開始在編輯區域之前
        if (marker.textEndIndex <= edit.oldEndDiff) {
          // segment 結束在編輯區域內
          newEndIndex = edit.newEndDiff
        } else {
          // segment 跨越整個編輯區域
          newEndIndex += lengthDelta
        }
      } else {
        // segment 開始在編輯區域內
        if (marker.textEndIndex <= edit.oldEndDiff) {
          // segment 完全在編輯區域內
          newStartIndex = edit.startDiff
          newEndIndex = edit.newEndDiff
        } else {
          // segment 結束在編輯區域之後
          newStartIndex = edit.newEndDiff
          newEndIndex = marker.textEndIndex + lengthDelta
        }
      }
    }

    // 確保索引有效
    newStartIndex = Math.max(0, Math.min(newStartIndex, newText.length))
    newEndIndex = Math.max(newStartIndex, Math.min(newEndIndex, newText.length))

    // 提取新文字
    const newSegText = newText.substring(newStartIndex, newEndIndex).trim()
    const originalText = updatedSegments[segIndex].text.trim()

    if (newSegText !== originalText) {
      updatedSegments[segIndex].text = newSegText
      hasChanges = true
      console.log(`✏️ Segment ${segIndex} 已修改: "${originalText}" → "${newSegText}"`)
    }
  })

  return hasChanges ? updatedSegments : null
}

/**
 * 從 contenteditable 元素提取文字內容，並記錄每段文字對應的 segment
 * @param {HTMLElement} element - contenteditable 元素
 * @returns {Object} { fullText: string, segmentTexts: Array<{segmentIndex: number, text: string}> }
 */
function extractTextContentWithSegments(element) {
  if (!element) {
    return { fullText: '', segmentTexts: [] }
  }

  const clone = element.cloneNode(true)
  let fullText = ''
  const segmentTexts = []
  let currentSegmentIndex = null
  let currentSegmentText = ''

  function traverseNode(node) {
    // 跳過 segment-marker 元素及其內容
    if (node.classList && node.classList.contains('segment-marker')) {
      return
    }

    // 跳過 text-timecode-tooltip 元素
    if (node.classList && node.classList.contains('text-timecode-tooltip')) {
      return
    }

    // 檢查是否是帶有 data-segment-index 的節點
    if (node.nodeType === Node.ELEMENT_NODE && node.hasAttribute && node.hasAttribute('data-segment-index')) {
      // 如果之前有累積的 segment 文字，先保存
      if (currentSegmentIndex !== null && currentSegmentText) {
        segmentTexts.push({
          segmentIndex: currentSegmentIndex,
          text: currentSegmentText
        })
      }

      // 開始新的 segment
      currentSegmentIndex = parseInt(node.getAttribute('data-segment-index'), 10)
      currentSegmentText = ''
    }

    // 處理文字節點
    if (node.nodeType === Node.TEXT_NODE) {
      const text = node.textContent
      fullText += text

      // 如果當前在某個 segment 中，累積文字
      if (currentSegmentIndex !== null) {
        currentSegmentText += text
      }
      return
    }

    // 處理 <br> 標籤
    if (node.nodeName === 'BR') {
      fullText += '\n'
      if (currentSegmentIndex !== null) {
        currentSegmentText += '\n'
      }
      return
    }

    // 處理塊級元素（div）
    if (node.nodeName === 'DIV' && fullText.length > 0 && !fullText.endsWith('\n')) {
      fullText += '\n'
      if (currentSegmentIndex !== null) {
        currentSegmentText += '\n'
      }
    }

    // 遞歸處理子節點
    const children = Array.from(node.childNodes)
    for (let child of children) {
      traverseNode(child)
    }

    // 塊級元素結束時的換行處理
    if (node.nodeName === 'DIV' && node.childNodes.length > 0) {
      const hasOnlyBr = node.childNodes.length === 1 && node.childNodes[0].nodeName === 'BR'
      if (!hasOnlyBr && !fullText.endsWith('\n')) {
        fullText += '\n'
        if (currentSegmentIndex !== null) {
          currentSegmentText += '\n'
        }
      }
    }
  }

  // 遍歷所有子節點
  const children = Array.from(clone.childNodes)
  for (let child of children) {
    traverseNode(child)
  }

  // 保存最後一個 segment
  if (currentSegmentIndex !== null && currentSegmentText) {
    segmentTexts.push({
      segmentIndex: currentSegmentIndex,
      text: currentSegmentText
    })
  }

  // 移除零寬度空格
  fullText = fullText.replace(/\u200B/g, '')
  segmentTexts.forEach(seg => {
    seg.text = seg.text.replace(/\u200B/g, '').trim()
  })

  return { fullText, segmentTexts }
}

// ========== 搜尋功能處理 ==========

// 執行搜尋
function handleSearch(text) {
  const wasSearching = searchText.value && searchMatches.value.length > 0
  searchText.value = text

  if (!text) {
    // 清除 CSS 高亮
    if (CSS.highlights) {
      CSS.highlights.delete('search-highlight')
      CSS.highlights.delete('search-highlight-current')
    }

    // 在編輯模式下，只清除狀態而不觸發 Vue 重新渲染
    // 使用 nextTick 確保狀態更新後再清空 matches，避免 DOM 衝突
    if (isEditing.value && wasSearching) {
      nextTick(() => {
        searchMatches.value = []
        currentMatchIndex.value = 0
      })
    } else {
      searchMatches.value = []
      currentMatchIndex.value = 0
    }
    return
  }

  const content = getSearchableContent()
  const matches = []

  try {
    // 跳脫正則表達式特殊字元
    let escapedText = text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')

    // 全字匹配
    if (matchWholeWord.value) {
      escapedText = `\\b${escapedText}\\b`
    }

    // 大小寫匹配
    const flags = matchCase.value ? 'g' : 'gi'
    const regex = new RegExp(escapedText, flags)
    let match

    while ((match = regex.exec(content)) !== null) {
      matches.push({
        start: match.index,
        end: match.index + match[0].length,
        text: match[0]
      })
    }
  } catch (e) {
    // 無效的正則表達式，忽略
  }

  searchMatches.value = matches
  currentMatchIndex.value = matches.length > 0 ? 0 : 0

  // 編輯模式下使用 CSS Custom Highlight API
  if (isEditing.value && displayMode.value === 'paragraph') {
    nextTick(() => {
      applySearchHighlightsWithCSS()
    })
  }

  // 滾動到第一個匹配項
  if (matches.length > 0) {
    scrollToMatch(0)
  }
}

// 取得可搜尋的內容
function getSearchableContent() {
  if (displayMode.value === 'paragraph') {
    if (textareaRef.value) {
      return extractTextContent(textareaRef.value)
    }
    return currentTranscript.value.content || ''
  } else if (displayMode.value === 'subtitle') {
    // 字幕模式：合併所有 segment 文字
    let content = ''
    groupedSegments.value.forEach(group => {
      group.segments.forEach(segment => {
        content += segment.text + '\n'
      })
    })
    return content
  }
  return ''
}

// 使用 CSS Custom Highlight API 應用搜尋高亮（編輯模式專用）
function applySearchHighlightsWithCSS() {
  // 檢查瀏覽器是否支援 CSS Custom Highlight API
  if (!CSS.highlights) {
    return
  }

  // 清除之前的高亮
  CSS.highlights.delete('search-highlight')
  CSS.highlights.delete('search-highlight-current')

  if (!textareaRef.value || searchMatches.value.length === 0) {
    return
  }

  const ranges = []
  const currentRanges = []

  // 遍歷 contenteditable 元素中的文字節點，建立字符位置映射
  // 邏輯需與 extractTextContent 保持一致
  const textNodes = []
  let charIndex = 0
  let lastCharWasNewline = false

  function collectTextNodes(node) {
    // 跳過 segment-marker 和 tooltip 元素
    if (node.classList && (node.classList.contains('segment-marker') || node.classList.contains('text-timecode-tooltip'))) {
      return
    }

    if (node.nodeType === Node.TEXT_NODE) {
      const text = node.textContent || ''
      if (text.length > 0) {
        // 移除零寬度空格，與 extractTextContent 保持一致
        const cleanText = text.replace(/\u200B/g, '')
        if (cleanText.length > 0) {
          textNodes.push({
            node,
            start: charIndex,
            end: charIndex + cleanText.length,
            // 記錄原始文字長度，用於計算偏移
            originalLength: text.length,
            cleanLength: cleanText.length
          })
          charIndex += cleanText.length
          lastCharWasNewline = cleanText.endsWith('\n')
        }
      }
    } else if (node.nodeType === Node.ELEMENT_NODE) {
      // 處理 BR 標籤作為換行
      if (node.nodeName === 'BR') {
        charIndex += 1
        lastCharWasNewline = true
        return
      }

      // 處理 DIV - 在前面添加換行（與 extractTextContent 一致）
      if (node.nodeName === 'DIV' && charIndex > 0 && !lastCharWasNewline) {
        charIndex += 1
        lastCharWasNewline = true
      }

      // 遞歸處理子節點
      for (const child of node.childNodes) {
        collectTextNodes(child)
      }

      // 處理 DIV - 在後面添加換行（與 extractTextContent 一致）
      if (node.nodeName === 'DIV' && node.childNodes.length > 0) {
        const hasOnlyBr = node.childNodes.length === 1 && node.childNodes[0].nodeName === 'BR'
        if (!hasOnlyBr && !lastCharWasNewline) {
          charIndex += 1
          lastCharWasNewline = true
        }
      }
    }
  }

  // 從根元素的子節點開始遍歷
  for (const child of textareaRef.value.childNodes) {
    collectTextNodes(child)
  }

  // 為每個匹配項創建 Range
  searchMatches.value.forEach((match, matchIndex) => {
    const matchStart = match.start
    const matchEnd = match.end

    // 找到匹配開始和結束位置對應的文字節點
    for (const textNode of textNodes) {
      // 檢查這個文字節點是否與匹配範圍重疊
      if (textNode.end <= matchStart || textNode.start >= matchEnd) {
        continue
      }

      // 計算在這個文字節點中的範圍
      const rangeStart = Math.max(0, matchStart - textNode.start)
      const rangeEnd = Math.min(textNode.node.textContent.length, matchEnd - textNode.start)

      try {
        const range = new Range()
        range.setStart(textNode.node, rangeStart)
        range.setEnd(textNode.node, rangeEnd)

        if (matchIndex === currentMatchIndex.value) {
          currentRanges.push(range)
        } else {
          ranges.push(range)
        }
      } catch (e) {
        // 忽略無效的範圍
      }
    }
  })

  // 註冊高亮
  if (ranges.length > 0) {
    CSS.highlights.set('search-highlight', new Highlight(...ranges))
  }
  if (currentRanges.length > 0) {
    CSS.highlights.set('search-highlight-current', new Highlight(...currentRanges))
  }
}

// 跳到上一個匹配項
function goToPreviousMatch() {
  if (searchMatches.value.length === 0) return
  currentMatchIndex.value = (currentMatchIndex.value - 1 + searchMatches.value.length) % searchMatches.value.length
  // 編輯模式下更新 CSS 高亮
  if (isEditing.value && displayMode.value === 'paragraph') {
    applySearchHighlightsWithCSS()
  }
  scrollToMatch(currentMatchIndex.value)
}

// 跳到下一個匹配項
function goToNextMatch() {
  if (searchMatches.value.length === 0) return
  currentMatchIndex.value = (currentMatchIndex.value + 1) % searchMatches.value.length
  // 編輯模式下更新 CSS 高亮
  if (isEditing.value && displayMode.value === 'paragraph') {
    applySearchHighlightsWithCSS()
  }
  scrollToMatch(currentMatchIndex.value)
}

// 滾動到指定的匹配項
function scrollToMatch(index) {
  if (displayMode.value === 'paragraph') {
    nextTick(() => {
      // 編輯模式下使用 CSS Custom Highlight API，需要手動計算滾動位置
      if (isEditing.value && textareaRef.value && searchMatches.value[index]) {
        const match = searchMatches.value[index]
        const range = findRangeForMatch(match)
        if (range) {
          const rect = range.getBoundingClientRect()
          const containerRect = textareaRef.value.getBoundingClientRect()
          const scrollTop = textareaRef.value.scrollTop + rect.top - containerRect.top - containerRect.height / 2
          textareaRef.value.scrollTo({ top: scrollTop, behavior: 'smooth' })
        }
      } else {
        // 非編輯模式：使用 DOM 元素
        const highlightedElements = document.querySelectorAll('.search-highlight')
        if (highlightedElements[index]) {
          highlightedElements[index].scrollIntoView({ behavior: 'smooth', block: 'center' })
        }
      }
    })
  } else if (displayMode.value === 'subtitle') {
    // 字幕模式：找到對應的行並滾動
    nextTick(() => {
      const highlightedElements = document.querySelectorAll('.search-highlight')
      if (highlightedElements[index]) {
        highlightedElements[index].scrollIntoView({ behavior: 'smooth', block: 'center' })
      }
    })
  }
}

// 找到匹配項對應的 Range（用於編輯模式下的滾動）
function findRangeForMatch(match) {
  if (!textareaRef.value) return null

  const textNodes = []
  let charIndex = 0
  let lastCharWasNewline = false

  function collectTextNodes(node) {
    if (node.classList && (node.classList.contains('segment-marker') || node.classList.contains('text-timecode-tooltip'))) {
      return
    }
    if (node.nodeType === Node.TEXT_NODE) {
      const text = node.textContent || ''
      if (text.length > 0) {
        const cleanText = text.replace(/\u200B/g, '')
        if (cleanText.length > 0) {
          textNodes.push({ node, start: charIndex, end: charIndex + cleanText.length })
          charIndex += cleanText.length
          lastCharWasNewline = cleanText.endsWith('\n')
        }
      }
    } else if (node.nodeType === Node.ELEMENT_NODE) {
      if (node.nodeName === 'BR') {
        charIndex += 1
        lastCharWasNewline = true
        return
      }
      // 處理 DIV - 在前面添加換行
      if (node.nodeName === 'DIV' && charIndex > 0 && !lastCharWasNewline) {
        charIndex += 1
        lastCharWasNewline = true
      }
      for (const child of node.childNodes) {
        collectTextNodes(child)
      }
      // 處理 DIV - 在後面添加換行
      if (node.nodeName === 'DIV' && node.childNodes.length > 0) {
        const hasOnlyBr = node.childNodes.length === 1 && node.childNodes[0].nodeName === 'BR'
        if (!hasOnlyBr && !lastCharWasNewline) {
          charIndex += 1
          lastCharWasNewline = true
        }
      }
    }
  }

  for (const child of textareaRef.value.childNodes) {
    collectTextNodes(child)
  }

  // 找到匹配開始位置對應的文字節點
  for (const textNode of textNodes) {
    if (match.start >= textNode.start && match.start < textNode.end) {
      try {
        const range = new Range()
        const startOffset = match.start - textNode.start
        const endOffset = Math.min(textNode.node.textContent.length, match.end - textNode.start)
        range.setStart(textNode.node, startOffset)
        range.setEnd(textNode.node, endOffset)
        return range
      } catch (e) {
        return null
      }
    }
  }
  return null
}

// 取代當前匹配項
function handleReplaceCurrent(newReplaceText) {
  if (!isEditing.value || searchMatches.value.length === 0) return

  replaceText.value = newReplaceText
  const match = searchMatches.value[currentMatchIndex.value]

  if (displayMode.value === 'paragraph') {
    // 段落模式
    let content = currentTranscript.value.content || ''
    if (textareaRef.value) {
      content = extractTextContent(textareaRef.value)
    }

    // 取代當前匹配
    const before = content.substring(0, match.start)
    const after = content.substring(match.end)
    const replacedContent = before + newReplaceText + after

    // 更新內容
    updateContentAfterReplace(replacedContent)

    // 重新搜尋並跳到下一個（如果有）
    // 需要等待 updateContentAfterReplace 的多層 nextTick 完成後再應用高亮
    const previousIndex = currentMatchIndex.value
    nextTick(() => {
      nextTick(() => {
        nextTick(() => {
          handleSearch(searchText.value)
          // 取代後自動跳到下一個匹配項（保持在同一位置，因為前面的已被取代）
          if (searchMatches.value.length > 0) {
            const nextIndex = Math.min(previousIndex, searchMatches.value.length - 1)
            currentMatchIndex.value = nextIndex
            if (isEditing.value && displayMode.value === 'paragraph') {
              applySearchHighlightsWithCSS()
            }
            scrollToMatch(nextIndex)
          }
        })
      })
    })
  } else if (displayMode.value === 'subtitle') {
    // 字幕模式：找到匹配項並取代
    let charCount = 0
    let found = false

    for (const group of groupedSegments.value) {
      if (found) break
      for (const segment of group.segments) {
        const segmentEnd = charCount + segment.text.length + 1 // +1 for newline
        if (match.start >= charCount && match.start < segmentEnd) {
          // 找到了對應的 segment
          const localStart = match.start - charCount
          const localEnd = match.end - charCount
          segment.text = segment.text.substring(0, localStart) + newReplaceText + segment.text.substring(localEnd)
          found = true
          break
        }
        charCount = segmentEnd
      }
    }

    // 重新搜尋並跳到下一個（如果有）
    const previousIndex = currentMatchIndex.value
    nextTick(() => {
      handleSearch(searchText.value)
      // 取代後自動跳到下一個匹配項
      if (searchMatches.value.length > 0) {
        const nextIndex = Math.min(previousIndex, searchMatches.value.length - 1)
        currentMatchIndex.value = nextIndex
        scrollToMatch(nextIndex)
      }
    })
  }
}

// 全部取代（新版）
function handleReplaceAllNew(newReplaceText) {
  if (!isEditing.value || searchMatches.value.length === 0) return

  replaceText.value = newReplaceText
  const searchPattern = searchText.value

  // 確認對話框
  const confirmMessage = $t('searchReplace.confirmReplaceAll', {
    count: searchMatches.value.length,
    search: searchPattern,
    replace: newReplaceText
  })
  if (!confirm(confirmMessage)) {
    return
  }

  if (displayMode.value === 'paragraph') {
    // 段落模式
    let content = currentTranscript.value.content || ''
    if (textareaRef.value) {
      content = extractTextContent(textareaRef.value)
    }

    // 跳脫正則表達式特殊字元
    let escapedText = searchPattern.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
    if (matchWholeWord.value) {
      escapedText = `\\b${escapedText}\\b`
    }
    const flags = matchCase.value ? 'g' : 'gi'
    const regex = new RegExp(escapedText, flags)
    const replacedContent = content.replace(regex, newReplaceText)

    // 更新內容
    updateContentAfterReplace(replacedContent)

    // 清空搜尋結果
    searchMatches.value = []
    currentMatchIndex.value = 0
  } else if (displayMode.value === 'subtitle') {
    // 字幕模式
    let escapedText = searchPattern.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
    if (matchWholeWord.value) {
      escapedText = `\\b${escapedText}\\b`
    }
    const flags = matchCase.value ? 'g' : 'gi'
    const regex = new RegExp(escapedText, flags)

    groupedSegments.value.forEach(group => {
      group.segments.forEach(segment => {
        segment.text = segment.text.replace(regex, newReplaceText)
      })
    })

    // 清空搜尋結果
    searchMatches.value = []
    currentMatchIndex.value = 0
  }
}

// 更新內容（取代後）
function updateContentAfterReplace(replacedContent) {
  // 保存滾動位置
  let savedScrollTop = 0
  if (textareaRef.value) {
    savedScrollTop = textareaRef.value.scrollTop
  }

  // 設置替換狀態
  isReplacing.value = true

  nextTick(() => {
    if (!isMounted) return

    // 清空標記
    segmentMarkers.value = []

    // 更新內容
    currentTranscript.value.content = replacedContent

    // 增加版本號
    contentVersion.value++

    // 重新生成標記
    if (segments.value && currentTranscript.value.content) {
      generateSegmentMarkers(segments.value, currentTranscript.value.content)
    }

    nextTick(() => {
      if (!isMounted) return
      isReplacing.value = false

      nextTick(() => {
        if (!isMounted) return
        if (savedScrollTop > 0 && textareaRef.value) {
          textareaRef.value.scrollTop = savedScrollTop
        }
      })
    })
  })
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
      end: marker.end,
      segmentIndex: marker.segmentIndex  // 加入 segment index
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

// 編輯模式專用：將文字內容分割成帶有 segment 標記的片段（不含搜尋高亮）
function getContentPartsForEditing() {
  return getContentParts()
}

// 將文字內容分割成帶有標記和搜尋高亮的片段
function getContentPartsWithHighlight() {
  const parts = getContentParts()

  // 在編輯模式下不渲染搜尋高亮，避免 Vue 更新 contenteditable 導致內容丟失
  // 如果沒有搜尋文字，直接返回原始 parts
  if (isEditing.value || !searchText.value || searchMatches.value.length === 0) {
    return parts
  }

  // 需要將非標記的純文字部分進一步分割為包含搜尋高亮的片段
  const result = []
  let globalCharIndex = 0

  for (const part of parts) {
    if (!part.isMarker) {
      // 純文字部分：分割搜尋高亮
      const subParts = splitTextWithHighlightByPosition(part.text, globalCharIndex)
      result.push(...subParts)
      globalCharIndex += part.text.length
    } else {
      // 標記部分：保留原樣，但內部文字會在模板中用 splitTextWithHighlight 處理
      result.push(part)
      globalCharIndex += part.text.length
    }
  }

  return result
}

// 根據全局位置分割文字並添加搜尋高亮
function splitTextWithHighlightByPosition(text, startPosition) {
  if (!searchText.value || searchMatches.value.length === 0) {
    return [{ text, isMarker: false, isHighlight: false }]
  }

  const endPosition = startPosition + text.length
  const parts = []
  let lastIndex = 0

  // 找出所有在這段文字範圍內的匹配
  const relevantMatches = searchMatches.value
    .map((match, idx) => ({ ...match, matchIndex: idx }))
    .filter(match => match.start < endPosition && match.end > startPosition)

  for (const match of relevantMatches) {
    // 計算在當前文字中的相對位置
    const localStart = Math.max(0, match.start - startPosition)
    const localEnd = Math.min(text.length, match.end - startPosition)

    // 添加匹配之前的普通文字
    if (localStart > lastIndex) {
      parts.push({
        text: text.substring(lastIndex, localStart),
        isMarker: false,
        isHighlight: false
      })
    }

    // 添加高亮文字
    parts.push({
      text: text.substring(localStart, localEnd),
      isMarker: false,
      isHighlight: true,
      isCurrent: match.matchIndex === currentMatchIndex.value
    })

    lastIndex = localEnd
  }

  // 添加剩餘的普通文字
  if (lastIndex < text.length) {
    parts.push({
      text: text.substring(lastIndex),
      isMarker: false,
      isHighlight: false
    })
  }

  // 如果沒有任何分割，返回原始文字
  if (parts.length === 0) {
    return [{ text, isMarker: false, isHighlight: false }]
  }

  return parts
}

// 分割文字並添加搜尋高亮（用於標記內的文字）
function splitTextWithHighlight(text, segmentIndex) {
  if (!searchText.value || !text) {
    return [{ text, isHighlight: false }]
  }

  const parts = []
  let lastIndex = 0

  try {
    let escapedText = searchText.value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
    if (matchWholeWord.value) {
      escapedText = `\\b${escapedText}\\b`
    }
    const flags = matchCase.value ? 'g' : 'gi'
    const regex = new RegExp(escapedText, flags)
    let match

    // 計算這個 segment 的全局起始位置
    let globalOffset = 0
    const sortedMarkers = [...segmentMarkers.value].sort((a, b) => a.textStartIndex - b.textStartIndex)
    const marker = sortedMarkers.find(m => m.segmentIndex === segmentIndex)
    if (marker) {
      globalOffset = marker.textStartIndex
    }

    while ((match = regex.exec(text)) !== null) {
      // 添加匹配之前的普通文字
      if (match.index > lastIndex) {
        parts.push({
          text: text.substring(lastIndex, match.index),
          isHighlight: false
        })
      }

      // 判斷是否是當前選中的匹配項
      const globalMatchStart = globalOffset + match.index
      const isCurrent = searchMatches.value.some((m, idx) =>
        m.start === globalMatchStart && idx === currentMatchIndex.value
      )

      // 添加高亮文字
      parts.push({
        text: match[0],
        isHighlight: true,
        isCurrent
      })

      lastIndex = match.index + match[0].length
    }
  } catch (e) {
    // 無效的正則表達式，返回原始文字
    return [{ text, isHighlight: false }]
  }

  // 添加剩餘的普通文字
  if (lastIndex < text.length) {
    parts.push({
      text: text.substring(lastIndex),
      isHighlight: false
    })
  }

  // 如果沒有任何分割，返回原始文字
  if (parts.length === 0) {
    return [{ text, isHighlight: false }]
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

// 處理內容區域滾動（關閉 Header 的設置面板）
function handleContentAreaScroll() {
  if (headerRef.value) {
    headerRef.value.closeMoreOptions()
  }
}

// 設置滾動監聽器
function setupScrollListeners() {
  // 監聽段落模式的滾動（.transcript-display）
  if (textareaRef.value) {
    textareaRef.value.addEventListener('scroll', handleContentAreaScroll)
  }

  // 監聽字幕模式的滾動（.subtitle-table-wrapper）
  const subtitleWrapper = document.querySelector('.subtitle-table-wrapper')
  if (subtitleWrapper) {
    subtitleWrapper.addEventListener('scroll', handleContentAreaScroll)
  }
}

// 移除滾動監聽器
function removeScrollListeners() {
  if (textareaRef.value) {
    textareaRef.value.removeEventListener('scroll', handleContentAreaScroll)
  }

  const subtitleWrapper = document.querySelector('.subtitle-table-wrapper')
  if (subtitleWrapper) {
    subtitleWrapper.removeEventListener('scroll', handleContentAreaScroll)
  }
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
  // 註冊 Alt 鍵監聯
  window.addEventListener('keydown', handleKeyDown)
  window.addEventListener('keyup', handleKeyUp)
  window.addEventListener('blur', handleBlur)

  loadTranscript(route.params.taskId)

  // 延遲執行以確保 DOM 已渲染
  const timerId = setTimeout(() => {
    if (!isMounted) return
    fixSubtitleScrolling()
    setupScrollListeners()
  }, 100)
  scrollRestoreTimers.push(timerId)
})

onUnmounted(() => {
  // 標記組件已卸載，防止異步操作更新狀態
  isMounted = false

  // 清除講者名稱自動儲存計時器
  if (speakerNamesSaveTimer) {
    clearTimeout(speakerNamesSaveTimer)
    speakerNamesSaveTimer = null
  }

  // 清除疏密度自動儲存計時器
  if (densityThresholdSaveTimer) {
    clearTimeout(densityThresholdSaveTimer)
    densityThresholdSaveTimer = null
  }

  // 清除所有滾動位置恢復計時器
  scrollRestoreTimers.forEach(timer => clearTimeout(timer))
  scrollRestoreTimers = []

  // 移除滾動監聽器
  removeScrollListeners()

  window.removeEventListener('beforeunload', handleBeforeUnload)
  // 移除 Alt 鍵監聯
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

// 監聽 displayMode 變化，重新設置滾動監聽器
watch(displayMode, () => {
  nextTick(() => {
    removeScrollListeners()
    setupScrollListeners()
  })
})
</script>

<style scoped>
/* Header 高度變數 */
.transcript-detail-container {
  --header-height: 70px;
  height: 100vh;
  box-sizing: border-box;
  overflow: hidden;
}

/* 雙欄佈局 */
.transcript-layout {
  display: grid;
  grid-template-columns: 320px 1fr;
  gap: 20px;
  height: calc(100vh - var(--header-height) - 20px);
  align-items: start;
  max-width: 1400px;
  margin: 0 auto;
  padding: 0 20px 20px;
}

/* 左側控制面板 */
.left-panel {
  position: sticky;
  top: 0;
  display: flex;
  flex-direction: column;
  gap: 5px;
  height: fit-content;
  max-height: calc(100vh - var(--header-height) - 40px);
  overflow-y: auto;
  overflow-x: visible;
}

/* 右側文字區域 */
.right-panel {
  height: calc(100vh - var(--header-height) - 40px);
  display: flex;
  flex-direction: column;
  box-sizing: border-box;
  overflow: hidden;
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
  color: var(--main-text-light);
}

.spinner {
  width: 40px;
  height: 40px;
  border: 3px solid rgba(163, 177, 198, 0.2);
  border-top-color: var(--main-primary);
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
  background: var(--main-bg);
  color: var(--main-text);
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
  box-shadow: 0 0 0 2px var(--main-primary);
}

/* 替換中的過渡狀態 */
.transcript-display.replacing-state {
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--upload-bg);
  box-shadow: 0 0 0 2px var(--main-primary);
}

.replacing-indicator {
  color: var(--main-text-light);
  font-size: 14px;
}

/* 文字片段 */
.text-part {
  display: inline;
  position: relative;
  padding: 1px 0px; /* 預先保留空間，避免 Alt 切換時文字重排 */
  border-radius: 3px;
  transition: background-color 0.2s ease;
}

/* 編輯模式下的 segment 文字（保留 data-segment-index 用於儲存時對應） */
.segment-text {
  display: inline;
  position: relative;
}

/* 編輯模式下 Alt 鍵按下時的可點擊樣式 */
.segment-text.clickable {
  background-color: rgba(196, 140, 226, 0.175);
  cursor: pointer;
  border-radius: 3px;
}

.segment-text.clickable:hover {
  background-color: rgba(163, 177, 198, 0.25);
}

/* Alt 鍵按下時的可點擊文字樣式 */
.text-part.clickable {
  background-color: rgba(196, 140, 226, 0.175);
  cursor: pointer;
}

.text-part.clickable:hover {
  background-color: rgba(163, 177, 198, 0.25);
}

/* 搜尋高亮 */
.search-highlight {
  display: inline;
  background-color: rgba(255, 235, 59, 0.4);
  border-radius: 2px;
  padding: 1px 0;
}

.search-highlight.current {
  background-color: rgba(255, 152, 0, 0.6);
  box-shadow: 0 0 0 1px rgba(255, 152, 0, 0.8);
}

/* CSS Custom Highlight API 樣式（用於編輯模式） */
::highlight(search-highlight) {
  background-color: rgba(255, 235, 59, 0.4);
}

::highlight(search-highlight-current) {
  background-color: rgba(255, 152, 0, 0.6);
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

.text-part.clickable:hover .text-timecode-tooltip,
.segment-text.clickable:hover .text-timecode-tooltip {
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
  color: var(--main-primary);
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
  color: var(--main-primary-dark);
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
    --header-height: auto;
  }

  .transcript-layout {
    grid-template-columns: 1fr;
    height: auto;
    padding: 0 12px 12px;
  }

  .left-panel {
    position: relative;
    top: 0;
    max-height: none;
  }

  .right-panel {
    height: calc(100vh - 200px);
  }
}
</style>
