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
      @delete-task="deleteTask"
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
    <div class="transcript-layout"
         :style="{ '--left-panel-width': isEffectivelyCollapsed ? '62px' : '280px' }">
      <!-- 移動端底部抽屜切換按鈕 -->
      <button
        class="mobile-drawer-toggle"
        @click="isMobileDrawerOpen = !isMobileDrawerOpen"
        :class="{ 'drawer-open': isMobileDrawerOpen }"
      >
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <circle cx="12" cy="12" r="3"></circle>
          <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"></path>
        </svg>
      </button>

      <!-- 移動端背景遮罩 -->
      <div
        v-if="isMobileDrawerOpen"
        class="mobile-drawer-backdrop"
        @click="isMobileDrawerOpen = false"
      ></div>

      <!-- 左側控制面板 / 移動端底部抽屜 -->
      <div class="left-panel card" :class="{ 'drawer-open': isMobileDrawerOpen, 'collapsed': isEffectivelyCollapsed }">

        <!-- A) 展開狀態：完整面板 -->
        <template v-if="!isEffectivelyCollapsed">
          <!-- 收合按鈕 -->
          <button class="panel-collapse-btn" @click="isLeftPanelCollapsed = true" title="收合面板">
            <span>−</span>
          </button>

          <!-- 任務資訊卡片 -->
          <TaskInfoCard
            :task-id="currentTranscript.task_id"
            :updated-at="currentTranscript.updated_at"
            :content="currentTranscript.content"
            :tags="currentTranscript.tags"
            :all-tags="allTags"
            @tags-updated="handleTagsUpdated"
          />

          <!-- 顯示設定卡片 -->
          <DisplaySettingsCard
            :display-mode="displayMode"
            v-model:show-timecode-markers="showTimecodeMarkers"
            v-model:time-format="timeFormat"
            v-model:is-dark-mode="isDarkMode"
            v-model:font-size="contentFontSize"
            v-model:font-weight="contentFontWeight"
            v-model:font-family="contentFontFamily"
            v-model:density-threshold="densityThreshold"
          />
        </template>

        <!-- B) 收合狀態：精簡側邊欄 -->
        <div v-else class="collapsed-sidebar">
          <!-- 展開按鈕 -->
          <button class="panel-expand-btn" @click="isLeftPanelCollapsed = false" title="展開面板">
            <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
              <!-- 左上直角 -->
              <polyline points="5,1 1,1 1,5" />
              <!-- 右下直角 -->
              <polyline points="9,13 13,13 13,9" />
            </svg>
          </button>

          <!-- 字體切換 (sans-serif / serif) -->
          <div class="collapsed-font-toggle">
            <button
              class="collapsed-font-btn"
              :class="{ active: contentFontFamily === 'sans-serif' }"
              @click="contentFontFamily = 'sans-serif'"
              title="Sans-serif"
            >
              <span style="font-family: -apple-system, sans-serif; font-size: 11px;">Aa</span>
            </button>
            <button
              class="collapsed-font-btn"
              :class="{ active: contentFontFamily === 'serif' }"
              @click="contentFontFamily = 'serif'"
              title="Serif"
            >
              <span style="font-family: Georgia, serif; font-size: 11px;">Aa</span>
            </button>
          </div>

          <!-- 時間碼/時間格式旋鈕 -->
          <div class="collapsed-knob-wrapper">
            <label v-if="displayMode === 'paragraph'" class="knob" :class="{ active: showTimecodeMarkers }" title="時間標記">
              <input type="checkbox" :checked="showTimecodeMarkers" @change="showTimecodeMarkers = $event.target.checked" />
              <span class="knob-indicator"></span>
            </label>
            <label v-else class="knob" :class="{ active: timeFormat === 'range' }" title="時間格式">
              <input type="checkbox" :checked="timeFormat === 'range'" @change="timeFormat = $event.target.checked ? 'range' : 'start'" />
              <span class="knob-indicator"></span>
            </label>
          </div>

          <!-- 深色/淺色模式旋鈕 -->
          <div class="collapsed-knob-wrapper">
            <label class="knob" :class="{ active: isDarkMode }" title="深色模式">
              <input type="checkbox" :checked="isDarkMode" @change="isDarkMode = $event.target.checked" />
              <span class="knob-indicator"></span>
            </label>
          </div>

          <!-- 垂直滑桿：字體大小 + 字體粗細 (+ 字幕模式疏密度) -->
          <div class="collapsed-sliders-container">
            <div class="collapsed-slider-wrapper">
              <input
                type="range"
                class="collapsed-vertical-slider"
                min="12"
                max="24"
                step="1"
                :value="contentFontSize"
                @input="contentFontSize = Number($event.target.value)"
                title="字體大小"
              />
            </div>
            <div class="collapsed-slider-wrapper">
              <input
                type="range"
                class="collapsed-vertical-slider"
                min="300"
                max="700"
                step="100"
                :value="contentFontWeight"
                @input="contentFontWeight = Number($event.target.value)"
                title="字體粗細"
              />
            </div>
            <div v-if="displayMode === 'subtitle'" class="collapsed-slider-wrapper">
              <input
                type="range"
                class="collapsed-vertical-slider"
                min="0"
                max="120"
                step="1"
                :value="densityThreshold"
                @input="densityThreshold = Number($event.target.value)"
                title="疏密度"
              />
            </div>
          </div>

          <!-- 數位顯示面板 -->
          <div class="collapsed-display-panel">
            <span class="display-row">{{ contentFontSize }}px</span>
            <span class="display-row">{{ contentFontWeight }}</span>
          </div>

          <!-- 音訊控制區域 -->
          <template v-if="hasAudio">
            <div class="collapsed-divider"></div>

            <!-- 音訊控制群組（緊湊間距） -->
            <div class="collapsed-audio-controls">
              <!-- 鍵盤快捷鍵按鈕 + tooltip -->
              <KeyboardShortcutsInfo class="collapsed-shortcuts-wrapper" pop-direction="pop-right" />

              <!-- 播放/暫停按鈕 -->
              <button class="collapsed-icon-btn" @click="togglePlayPause" :title="isPlaying ? $t('audioPlayer.pause') : $t('audioPlayer.play')">
                <svg v-if="!isPlaying" width="20" height="20" viewBox="0 0 24 24" fill="currentColor">
                  <path d="M8 5v14l11-7z"/>
                </svg>
                <svg v-else width="20" height="20" viewBox="0 0 24 24" fill="currentColor">
                  <path d="M6 4h4v16H6V4zm8 0h4v16h-4V4z"/>
                </svg>
              </button>

              <!-- 倒退 10s -->
              <button class="collapsed-icon-btn" @click="skipBackward" :title="$t('audioPlayer.rewind10s')">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
                  <path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/>
                  <path d="M3 3v5h5"/>
                </svg>
              </button>

              <!-- 快進 10s -->
              <button class="collapsed-icon-btn" @click="skipForward" :title="$t('audioPlayer.fastForward10s')">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
                  <path d="M21 12a9 9 0 1 1-9-9c2.52 0 4.93 1 6.74 2.74L21 8"/>
                  <path d="M21 3v5h-5"/>
                </svg>
              </button>

              <!-- 播放速度選擇器 -->
              <PlaybackSpeedControl
                class="collapsed-speed-wrapper"
                :playback-rate="playbackRate"
                pop-direction="pop-right"
                @set-playback-rate="setPlaybackRate"
              />
            </div>
          </template>
        </div>

        <!-- C) AudioPlayer 始終掛載，收合時隱藏（保持 audio element 活躍） -->
        <AudioPlayer
          v-if="currentTranscript.hasAudio"
          v-show="!isEffectivelyCollapsed"
          ref="audioPlayerRef"
          class="desktop-audio-player"
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
      <div
        class="right-panel card"
        :style="{ '--content-font-size': contentFontSize + 'px', '--content-font-weight': contentFontWeight, '--content-font-family': contentFontFamily === 'serif' ? 'Georgia, Times New Roman, serif' : '-apple-system, BlinkMacSystemFont, Segoe UI, Roboto, sans-serif' }"
      >
        <!-- AI 摘要組件 -->
        <AISummary
          v-if="currentTranscript.task_id"
          :task-id="currentTranscript.task_id"
          :initial-summary-status="currentTranscript.summary_status"
          @summary-updated="handleSummaryUpdated"
        />

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
              @paste="handlePaste"
            ><template v-for="(part, index) in getContentPartsForEditing()" :key="`edit-${index}`"><span v-if="!part.isMarker">{{ part.text }}</span><span
                v-else
                class="segment-text"
                :class="{ 'clickable': isAltPressed && currentTranscript.hasAudio }"
                :data-segment-index="part.segmentIndex"
                :data-start-time="part.start"
                @click="handleTextClick(part.start, $event)"
              >{{ part.text }}<span
                  v-if="isAltPressed"
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
                    >{{ subPart.text }}<span v-if="isAltPressed && subIndex === 0" class="text-timecode-tooltip">
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

    <!-- 手機版音訊播放器（固定在底部） -->
    <AudioPlayer
      v-if="currentTranscript.hasAudio"
      class="mobile-audio-player"
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

    <!-- 下載對話框組件 -->
    <DownloadDialog
      :show="showDownloadDialog"
      :display-mode="displayMode"
      :time-format="timeFormat"
      :density-threshold="densityThreshold"
      :has-speaker-info="hasSpeakerInfo"
      :has-summary="hasSummaryData"
      v-model:selected-format="selectedDownloadFormat"
      v-model:include-speaker="includeSpeaker"
      v-model:include-summary="includeSummary"
      v-model:include-transcript="includeTranscript"
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
import TaskInfoCard from '../components/transcript/TaskInfoCard.vue'
import DisplaySettingsCard from '../components/transcript/DisplaySettingsCard.vue'
import AISummary from '../components/transcript/AISummary.vue'
import KeyboardShortcutsInfo from '../components/transcript/KeyboardShortcutsInfo.vue'
import PlaybackSpeedControl from '../components/transcript/PlaybackSpeedControl.vue'

// API 服務
import { taskService, summaryService } from '../api/services.js'

// Composables
import { useTranscriptData } from '../composables/transcript/useTranscriptData'
import { useAudioPlayer } from '../composables/transcript/useAudioPlayer'
import { useSubtitleMode } from '../composables/transcript/useSubtitleMode'
import { useTranscriptEditor } from '../composables/transcript/useTranscriptEditor'
import { useSegmentMarkers } from '../composables/transcript/useSegmentMarkers'
import { useKeyboardShortcuts } from '../composables/transcript/useKeyboardShortcuts'
import { useTranscriptDownload } from '../composables/transcript/useTranscriptDownload'
import { useTaskTags } from '../composables/task/useTaskTags'
import { isMac, isModifierPressed } from '../utils/platform'
import { useAuthStore } from '../stores/auth'

const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()

// 組件引用
const audioPlayerRef = ref(null)
const headerRef = ref(null)

// 移動端底部抽屜狀態
const isMobileDrawerOpen = ref(false)

// 是否為移動端（用於保護收合功能不影響移動端）
const isMobileView = ref(window.innerWidth <= 768)
const handleResize = () => { isMobileView.value = window.innerWidth <= 768 }

// 面板是否實際處於收合狀態（移動端永遠展開）
const isEffectivelyCollapsed = computed(() => isLeftPanelCollapsed.value && !isMobileView.value)

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
  updateSubtitleSettings,
  updateTags
} = useTranscriptData()

// 標籤管理
const { fetchTagColors, customTagOrder } = useTaskTags($t)

// 所有可用標籤（按順序排列）
const allTags = computed(() => customTagOrder.value)

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
  stopDragArc,
  cleanup: cleanupAudioPlayer
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

// 顯示設定
const isDarkMode = ref(document.documentElement.getAttribute('data-theme') === 'dark')
const contentFontSize = ref(16)
const contentFontWeight = ref(400)
const contentFontFamily = ref('sans-serif')

// 左側面板收合狀態
const isLeftPanelCollapsed = ref(localStorage.getItem('leftPanelCollapsed') === 'true')
watch(isLeftPanelCollapsed, (v) => localStorage.setItem('leftPanelCollapsed', String(v)))

// 監聽暗色模式變化，切換全局主題並儲存偏好
watch(isDarkMode, (dark) => {
  const theme = dark ? 'dark' : 'light'
  if (dark) {
    document.documentElement.setAttribute('data-theme', 'dark')
  } else {
    document.documentElement.removeAttribute('data-theme')
  }
  localStorage.setItem('theme', theme)
  authStore.updatePreferences({ theme })
})

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
  includeSummary,
  includeTranscript,
  performSubtitleDownload,
  openDownloadDialog,
  downloadAsPdf
} = useTranscriptDownload()

// AI 摘要數據（用於下載）
const summaryData = ref(null)

// 是否有 AI 摘要
const hasSummaryData = computed(() => {
  return currentTranscript.value.summary_status === 'completed'
})

// 載入 AI 摘要數據
async function loadSummaryForDownload() {
  if (!hasSummaryData.value || summaryData.value) return

  try {
    summaryData.value = await summaryService.get(currentTranscript.value.task_id)
  } catch (error) {
    console.error('載入摘要失敗:', error)
    summaryData.value = null
  }
}

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
    // 從 contenteditable div 中提取純文字內容和 segment 文字
    if (textareaRef.value) {
      const { fullText, segmentTexts } = extractTextContentWithSegments(textareaRef.value)
      contentToSave = fullText

      // 更新到 currentTranscript
      currentTranscript.value.content = contentToSave

      // 如果有 segments 資料，直接從 DOM 提取的 segment 文字來更新
      if (segments.value && segments.value.length > 0 && segmentTexts.length > 0) {
        const updatedSegments = segments.value.map((seg) => ({ ...seg }))
        let hasChanges = false

        // 使用從 DOM 直接提取的 segment 文字來更新
        segmentTexts.forEach(({ segmentIndex, text }) => {
          if (segmentIndex >= 0 && segmentIndex < updatedSegments.length) {
            const originalText = updatedSegments[segmentIndex].text?.trim() || ''
            if (text !== originalText) {
              updatedSegments[segmentIndex].text = text
              hasChanges = true
              console.log(`✏️ Segment ${segmentIndex} 已修改: "${originalText}" → "${text}"`)
            }
          }
        })

        if (hasChanges) {
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
  // 兩種模式都開啟下載對話框
  openDownloadDialog()
}

// 執行下載（從對話框）
async function performDownload() {
  // 根據用戶選擇決定是否包含講者資訊
  // null 表示不顯示講者，{} 或 speakerNames 表示顯示講者（使用自定義名稱或原始代號）
  const speakerNamesToUse = includeSpeaker.value ? speakerNames.value : null
  const filename = currentTranscript.value.custom_name || currentTranscript.value.filename || 'transcript'
  const format = selectedDownloadFormat.value
  const isParagraphMode = displayMode.value === 'paragraph'

  // 取得逐字稿文字的輔助函數
  const getTranscriptText = () => {
    if (isParagraphMode) {
      // 段落模式：直接使用原始內容
      return currentTranscript.value.content || ''
    } else {
      // 字幕模式：根據設定生成格式化文字
      return generateSubtitleText(groupedSegments.value, timeFormat.value, speakerNamesToUse)
    }
  }

  // PDF 格式處理
  if (format === 'pdf') {
    // 如果需要包含摘要且尚未載入，先載入
    if (includeSummary.value && hasSummaryData.value && !summaryData.value) {
      await loadSummaryForDownload()
    }

    // 生成逐字稿文字（如果需要）
    let transcriptText = ''
    if (includeTranscript.value) {
      transcriptText = getTranscriptText()
    }

    await downloadAsPdf({
      filename,
      title: currentTranscript.value.custom_name || currentTranscript.value.filename,
      summary: includeSummary.value ? summaryData.value : null,
      transcriptText,
      includeSummary: includeSummary.value,
      includeTranscript: includeTranscript.value,
      t: $t
    })
    return
  }

  // TXT 格式處理（支援內容選擇）
  if (format === 'txt') {
    let content = ''

    // 如果有摘要且選擇包含
    if (includeSummary.value && hasSummaryData.value) {
      if (!summaryData.value) {
        await loadSummaryForDownload()
      }
      if (summaryData.value) {
        content += formatSummaryAsText(summaryData.value)
        if (includeTranscript.value) {
          content += '\n\n' + '='.repeat(50) + '\n\n'
        }
      }
    }

    // 逐字稿
    if (includeTranscript.value) {
      content += getTranscriptText()
    }

    performSubtitleDownload(content, filename, format)
    return
  }

  // SRT/VTT 格式（僅逐字稿，僅字幕模式可用）
  let content = ''
  if (format === 'srt') {
    content = generateSRTText(groupedSegments.value, speakerNamesToUse)
  } else if (format === 'vtt') {
    content = generateVTTText(groupedSegments.value, speakerNamesToUse)
  }

  performSubtitleDownload(content, filename, format)
}

// 將摘要格式化為純文字
function formatSummaryAsText(summary) {
  if (!summary?.content) return ''

  const content = summary.content
  const lines = []

  lines.push('【AI 摘要】')
  lines.push('')

  // 主題
  if (content.meta?.detected_topic) {
    lines.push(content.meta.detected_topic)
    lines.push('')
  }

  // 摘要
  if (content.summary) {
    lines.push(`【${$t('aiSummary.executiveSummary')}】`)
    lines.push(content.summary)
    lines.push('')
  }

  // 重點
  const points = content.key_points || content.highlights || []
  if (points.length > 0) {
    lines.push(`【${$t('aiSummary.keyPoints')}】`)
    points.forEach(point => {
      const text = typeof point === 'string' ? point : (point.text || point.point || point.content || JSON.stringify(point))
      lines.push(`• ${text}`)
    })
    lines.push('')
  }

  // 內容段落
  if (content.segments && content.segments.length > 0) {
    lines.push(`【${$t('aiSummary.contentSegments')}】`)
    content.segments.forEach(segment => {
      lines.push(`▎${segment.topic}`)
      lines.push(segment.content)
      if (segment.keywords && segment.keywords.length > 0) {
        lines.push(`關鍵詞: ${segment.keywords.join(', ')}`)
      }
      lines.push('')
    })
  }

  // 待辦事項
  if (content.action_items && content.action_items.length > 0) {
    lines.push(`【${$t('aiSummary.actionItems')}】`)
    content.action_items.forEach(item => {
      let line = `☐ ${item.task}`
      const meta = []
      if (item.owner) meta.push(item.owner)
      if (item.deadline) meta.push(item.deadline)
      if (meta.length > 0) line += ` (${meta.join(' / ')})`
      lines.push(line)
    })
    lines.push('')
  }

  return lines.join('\n').trim()
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
  // 打開 Header 的講者設定面板，並 focus 到該講者的輸入框
  if (headerRef.value) {
    headerRef.value.openSpeakerSettings(speakerCode)
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

// 刪除任務
async function deleteTask() {
  if (!confirm($t('tasksView.confirmDeleteTask'))) {
    return
  }

  try {
    await taskService.delete(currentTranscript.value.task_id)
    router.push('/')
  } catch (error) {
    console.error('Delete failed:', error)
    alert($t('tasksView.deleteFailed'))
  }
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

  /**
   * 從節點中提取純文字（用於 segment 內部）
   */
  function extractTextFromNode(node) {
    let text = ''

    // 跳過 segment-marker 和 tooltip 元素
    if (node.classList && (node.classList.contains('segment-marker') || node.classList.contains('text-timecode-tooltip'))) {
      return ''
    }

    if (node.nodeType === Node.TEXT_NODE) {
      return node.textContent
    }

    if (node.nodeName === 'BR') {
      return '\n'
    }

    // 遞歸處理子節點
    const children = Array.from(node.childNodes)
    for (let child of children) {
      text += extractTextFromNode(child)
    }

    return text
  }

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
      const segmentIndex = parseInt(node.getAttribute('data-segment-index'), 10)
      // 直接提取這個 segment span 內的所有文字
      const segmentText = extractTextFromNode(node)

      fullText += segmentText

      if (segmentText) {
        segmentTexts.push({
          segmentIndex: segmentIndex,
          text: segmentText
        })
      }
      // 已處理完這個 segment，不需要再遞歸
      return
    }

    // 處理文字節點
    if (node.nodeType === Node.TEXT_NODE) {
      fullText += node.textContent
      return
    }

    // 處理 <br> 標籤
    if (node.nodeName === 'BR') {
      fullText += '\n'
      return
    }

    // 處理塊級元素（div）
    if (node.nodeName === 'DIV' && fullText.length > 0 && !fullText.endsWith('\n')) {
      fullText += '\n'
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
      }
    }
  }

  // 遍歷所有子節點
  const children = Array.from(clone.childNodes)
  for (let child of children) {
    traverseNode(child)
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

  // 使用 setTimeout 給 Vue 足夠時間完成 DOM 清理，避免 insertBefore 錯誤
  const timerId = setTimeout(() => {
    if (!isMounted) return
    isReplacing.value = false

    nextTick(() => {
      if (!isMounted) return
      if (savedScrollTop > 0 && textareaRef.value) {
        textareaRef.value.scrollTop = savedScrollTop
      }
    })
  }, 50)
  scrollRestoreTimers.push(timerId)
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

// 鍵盤事件處理（Mac 使用 ⌘，Windows/Linux 使用 Ctrl）
function handleKeyDown(e) {
  if (isModifierPressed(e)) {
    isAltPressed.value = true

    // 防止修飾鍵組合的預設瀏覽器行為
    // 只針對我們有定義快捷鍵的按鍵
    const shortcutKeys = [' ', 'm', 'M', ',', '.', 'ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown']
    if (shortcutKeys.includes(e.key)) {
      e.preventDefault()
      e.stopPropagation() // 阻止事件繼續傳播，避免 contenteditable 插入字元
    }
  }
}

function handleKeyUp(e) {
  const modifierStillHeld = isMac ? e.metaKey : e.ctrlKey
  if (!modifierStillHeld) {
    isAltPressed.value = false
  }
}

// 處理視窗失焦（確保 Ctrl 鍵狀態重置）
function handleBlur() {
  isAltPressed.value = false
}

// 處理貼上事件，只允許純文字
function handlePaste(e) {
  e.preventDefault()
  const text = e.clipboardData?.getData('text/plain') || ''
  if (text) {
    document.execCommand('insertText', false, text)
  }
}

// 處理 contenteditable 區域的按鍵事件（Mac 使用 ⌘，Windows/Linux 使用 Ctrl）
function handleContentEditableKeyDown(e) {
  if (!isModifierPressed(e)) return

  // 修飾鍵 + Space: 播放/暫停
  if (e.key === ' ') {
    e.preventDefault()
    e.stopPropagation()
    if (hasAudio.value && audioElement.value) {
      togglePlayPause()
    }
    return
  }

  // 修飾鍵 + ArrowUp: 加速播放
  if (e.key === 'ArrowUp') {
    e.preventDefault()
    e.stopPropagation()
    const newRate = Math.min(2, playbackRate.value + 0.25)
    setPlaybackRate(newRate)
    return
  }

  // 修飾鍵 + ArrowDown: 減速播放
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

// 載入所有可用標籤（包含顏色和順序）
async function loadAllTags() {
  await fetchTagColors()
}

// 處理標籤更新
async function handleTagsUpdated({ taskId, tags }) {
  const success = await updateTags(tags)
  if (success) {
    // 重新載入標籤列表以獲取最新的標籤
    await loadAllTags()
  }
}

// 處理 AI 摘要更新
function handleSummaryUpdated({ taskId, status }) {
  console.log(`✅ AI 摘要已更新: ${taskId}, 狀態: ${status}`)
  // 更新本地狀態
  if (currentTranscript.value.task_id === taskId) {
    currentTranscript.value.summary_status = status
  }
}

// 初始載入
onMounted(() => {
  document.body.classList.add('transcript-detail-page')
  window.addEventListener('beforeunload', handleBeforeUnload)
  // 註冊 Alt 鍵監聯
  window.addEventListener('keydown', handleKeyDown)
  window.addEventListener('keyup', handleKeyUp)
  window.addEventListener('blur', handleBlur)
  window.addEventListener('resize', handleResize)

  loadTranscript(route.params.taskId)
  loadAllTags()

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
  window.removeEventListener('resize', handleResize)

  document.body.classList.remove('editing-transcript')
  document.body.classList.remove('transcript-detail-page')

  // 清理音訊播放器資源（停止 token 自動刷新定時器）
  cleanupAudioPlayer()
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
  grid-template-columns: var(--left-panel-width, 280px) 1fr;
  gap: 20px;
  height: calc(100vh - var(--header-height) - 20px);
  align-items: start;
  max-width: 1400px;
  margin: 0 auto;
  padding: 0 20px 20px;
  transition: grid-template-columns 0.3s ease;
}

/* 左側控制面板 */
.left-panel {
  position: sticky;
  margin-top: 23px;
  display: flex;
  flex-direction: column;
  gap: 5px;
  height: fit-content;
  border: 0.5px solid;
  border-radius: 13px;
  padding: 20px 10px;
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
  font-size: var(--content-font-size, 1rem);
  font-weight: var(--content-font-weight, 400);
  line-height: 1.8;
  font-family: var(--content-font-family, -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif);
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
  background-color: rgba(229, 179, 133, 0.25);
  cursor: pointer;
}

.text-part.clickable:hover {
  background-color: rgba(148, 171, 204, 0.3);
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

/* === 面板收合按鈕 === */
.panel-collapse-btn {
  position: absolute;
  top: 8px;
  right: 8px;
  width: 24px;
  height: 24px;
  border: none;
  background: rgba(var(--color-text-dark-rgb, 0, 0, 0), 0.08);
  border-radius: 50%;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 18px;
  font-weight: 300;
  line-height: 1;
  color: var(--nav-text);
  opacity: 0.5;
  transition: opacity 0.2s, background 0.2s;
  z-index: 2;
}

.panel-collapse-btn:hover {
  opacity: 1;
  background: rgba(var(--color-text-dark-rgb, 0, 0, 0), 0.15);
}

.panel-expand-btn {
  width: 28px;
  height: 28px;
  border: none;
  background: rgba(var(--color-text-dark-rgb, 0, 0, 0), 0.08);
  border-radius: 50%;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 20px;
  font-weight: 300;
  line-height: 1;
  color: var(--nav-text);
  transition: background 0.2s;
  flex-shrink: 0;
  opacity: 0.5;
}

.panel-expand-btn:hover {
  background: rgba(var(--color-text-dark-rgb, 0, 0, 0), 0.15);
  opacity: 1;
}

/* === 收合面板 === */
.left-panel.collapsed {
  width: 62px;
  padding: 8px 4px;
  align-items: center;
  overflow: visible;
  z-index: 10;
}

.collapsed-sidebar {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  width: 100%;
}

/* 收合字體切換 */
.collapsed-font-toggle {
  display: flex;
  flex-direction: column;
  gap: 2px;
  width: 100%;
}

.collapsed-font-btn {
  width: 100%;
  height: 22px;
  border: none;
  border-radius: 4px;
  background: transparent;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  color: rgba(var(--color-text-dark-rgb, 0, 0, 0), 0.4);
  transition: all 0.2s;
}

.collapsed-font-btn.active {
  background: rgba(var(--color-text-dark-rgb, 0, 0, 0), 0.08);
  color: var(--color-text-dark);
}

.collapsed-font-btn:hover {
  color: rgba(var(--color-text-dark-rgb, 0, 0, 0), 0.7);
}

/* 收合旋鈕 */
.collapsed-knob-wrapper {
  display: flex;
  justify-content: center;
}

@import url('https://fonts.googleapis.com/css2?family=VT323&display=swap');

/* Knob Switch (copied from DisplaySettingsCard scoped styles) */
.knob {
  position: relative;
  display: inline-block;
  width: 32px;
  height: 32px;
  background: #dedede;
  border: 0.5px solid;
  border-radius: 50%;
  cursor: pointer;
  transition: all 0.3s ease;
}

.knob input {
  opacity: 0;
  width: 0;
  height: 0;
  position: absolute;
}

.knob-indicator {
  position: absolute;
  top: 50%;
  left: 50%;
  width: 2px;
  height: 14px;
  background-color: var(--nav-active-bg);
  border-radius: 1px;
  transform-origin: center bottom;
  transform: translate(-50%, -100%) rotate(230deg);
  transition: transform 0.3s ease, background-color 0.3s ease;
}

.knob.active {
  background: var(--nav-active-bg);
}

.knob.active .knob-indicator {
  background-color: white;
  transform: translate(-50%, -100%) rotate(130deg);
}

.knob:hover {
  box-shadow: 0 0 0 3px rgba(var(--main-primary-rgb, 59, 130, 246), 0.2);
}

/* 收合垂直滑桿 */
.collapsed-sliders-container {
  display: flex;
  gap: 4px;
  justify-content: center;
  padding: 4px 0;
}

.collapsed-slider-wrapper {
  height: 90px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.collapsed-vertical-slider {
  writing-mode: vertical-lr;
  direction: rtl;
  width: 14px;
  height: 88px;
  -webkit-appearance: none;
  appearance: none;
  background: transparent;
  outline: none;
}

.collapsed-vertical-slider::-webkit-slider-runnable-track {
  width: 3px;
  height: 100%;
  background: rgba(0, 0, 0, 0.1);
  border-radius: 2px;
  border: 0.5px solid #999;
}

.collapsed-vertical-slider::-moz-range-track {
  width: 3px;
  height: 100%;
  background: rgba(0, 0, 0, 0.1);
  border-radius: 2px;
}

.collapsed-vertical-slider::-webkit-slider-thumb {
  -webkit-appearance: none;
  appearance: none;
  width: 10px;
  height: 7px;
  margin-left: -4px;
  background: var(--nav-bg);
  border-right: 1.5px solid var(--nav-active-bg);
  border-left: 1.5px solid var(--nav-active-bg);
  border-radius: 10%;
  cursor: pointer;
}

.collapsed-vertical-slider::-moz-range-thumb {
  width: 14px;
  height: 7px;
  background: var(--main-primary);
  border-radius: 10%;
  cursor: pointer;
  border: none;
}

/* 收合數位顯示面板 */
.collapsed-display-panel {
  display: flex;
  flex-direction: column;
  gap: 2px;
  font-family: 'VT323', monospace;
  font-size: 12px;
  color: #ffffff;
  background: #101010;
  padding: 2px 6px;
  border-radius: 3px;
  min-width: 40px;
  text-align: right;
  box-shadow: inset 0 2px 4px rgba(0, 0, 0, 0.6);
  border: 1px solid #222;
  letter-spacing: 1px;
}

.collapsed-display-panel .display-row {
  line-height: 1.3;
}

/* 收合分隔線 */
.collapsed-divider {
  width: 28px;
  height: 1px;
  background: rgba(var(--color-text-dark-rgb, 0, 0, 0), 0.12);
  margin: 4px 0;
}

/* 收合音訊控制群組 */
.collapsed-audio-controls {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 2px;
}

/* 收合圖標按鈕 */
.collapsed-icon-btn {
  width: 36px;
  height: 30px;
  border: none;
  border-radius: 15%;
  background: transparent;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--nav-text);
  transition: background 0.2s;
  flex-shrink: 0;
}

.collapsed-icon-btn:hover {
  background: rgba(var(--color-text-dark-rgb, 0, 0, 0), 0.08);
}

/* 收合側邊欄的共用元件樣式微調 */
.collapsed-shortcuts-wrapper :deep(.shortcuts-trigger-btn) {
  width: 36px;
  height: 30px;
  border-radius: 50%;
  color: var(--nav-text);
}

.collapsed-shortcuts-wrapper :deep(.shortcuts-trigger-btn) svg {
  width: 22px;
  height: 16px;
}

.collapsed-speed-wrapper :deep(.speed-trigger-btn) {
  width: 36px;
  height: 30px;
  border-radius: 50%;
}

.collapsed-speed-wrapper :deep(.speed-label) {
  font-size: 12px;
}

/* === 音訊播放器顯示控制 === */

/* 手機版播放器：桌面隱藏 */
.mobile-audio-player {
  display: none;
}

/* === 移動端底部抽屜 === */

/* 浮動切換按鈕 - 僅在移動端顯示 */
.mobile-drawer-toggle {
  display: none;
  position: fixed;
  bottom: calc(70px + env(safe-area-inset-bottom, 0px));
  right: 16px;
  width: 56px;
  height: 56px;
  border-radius: 50%;
  background: var(--main-primary);
  color: white;
  border: none;
  cursor: pointer;
  z-index: 100;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.2);
  transition: all 0.3s ease;
  align-items: center;
  justify-content: center;
}

.mobile-drawer-toggle:hover {
  transform: scale(1.05);
  box-shadow: 0 6px 16px rgba(0, 0, 0, 0.25);
}

.mobile-drawer-toggle.drawer-open {
  background: var(--main-text-light);
}

/* 背景遮罩 */
.mobile-drawer-backdrop {
  display: none;
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(0, 0, 0, 0.4);
  z-index: 199;
  animation: fadeIn 0.2s ease;
}

@keyframes fadeIn {
  from { opacity: 0; }
  to { opacity: 1; }
}

/* 平板以下響應式 */
@media (max-width: 768px) {
  .transcript-detail-container {
    --header-height: auto;
  }

  .transcript-layout {
    grid-template-columns: 1fr;
    height: auto;
    padding: 0 4px;
    position: relative;
  }

  /* 顯示浮動按鈕 */
  .mobile-drawer-toggle {
    display: flex;
  }

  /* 背景遮罩在抽屜開啟時顯示 */
  .mobile-drawer-backdrop {
    display: block;
  }

  /* 左側面板轉為底部抽屜 */
  .left-panel {
    position: fixed;
    bottom: 0;
    left: 0;
    right: 0;
    top: auto;
    margin-top: 0;
    max-height: 70vh;
    border-radius: 20px 20px 0 0;
    z-index: 200;
    transform: translateY(100%);
    transition: transform 0.3s ease, visibility 0.3s ease;
    overflow-y: auto;
    padding: 20px 16px;
    box-shadow: 0 -4px 20px rgba(0, 0, 0, 0.15);
    visibility: hidden;
  }

  .left-panel.drawer-open {
    transform: translateY(0);
    visibility: visible;
  }

  /* 抽屜頂部拖曳指示條 */
  .left-panel::before {
    content: '';
    position: absolute;
    top: 8px;
    left: 50%;
    transform: translateX(-50%);
    width: 40px;
    height: 4px;
    background: rgba(0, 0, 0, 0.2);
    border-radius: 2px;
  }

  /* 為底部固定播放器留空間 */
  .right-panel {
    height: calc(100vh - 60px);
    padding: 2px;
    padding-bottom: 120px;
    
  }

  /* 隱藏抽屜內的桌面版播放器 */
  .desktop-audio-player {
    display: none;
  }

  /* 顯示手機版播放器 */
  .mobile-audio-player {
    display: block;
  }

  /* 移動端：隱藏收合按鈕和收合側邊欄 */
  .panel-collapse-btn,
  .collapsed-sidebar {
    display: none !important;
  }

  /* 移動端：重設收合面板樣式 */
  .left-panel.collapsed {
    width: auto;
    padding: 20px 16px;
    align-items: stretch;
  }
}

/* 小手機進一步調整 */
@media (max-width: 480px) {
  .transcript-layout {
    padding: 0 2px;
    gap: 8px;
  }

  .mobile-drawer-toggle {
    width: 48px;
    height: 48px;
    bottom: calc(56px + env(safe-area-inset-bottom, 0px));
    right: 12px;
  }

  .mobile-drawer-toggle svg {
    width: 18px;
    height: 18px;
  }

  .left-panel {
    max-height: 75vh;
    padding: 16px 12px;
  }

  /* 為底部固定播放器留空間 */
  .right-panel {
    height: calc(100vh - 50px);
    padding: 2px;
    padding-bottom: 90px;
  }

  /* 文字顯示區域調整 */
  .transcript-display {
    padding: 12px;
    /* 保留使用者設定的字體大小 */
    line-height: 1.6;
  }
}
</style>
