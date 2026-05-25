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
      :copyable-text="copyableText"
      :is-content-ready="currentTranscript.status === 'completed'"
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
      @share="handleShare"
      @edit-tags="showTagSheet = true"
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
    <div
class="transcript-layout"
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
                  <path d="M8 5v14l11-7z" />
                </svg>
                <svg v-else width="20" height="20" viewBox="0 0 24 24" fill="currentColor">
                  <path d="M6 4h4v16H6V4zm8 0h4v16h-4V4z" />
                </svg>
              </button>

              <!-- 倒退 10s -->
              <button class="collapsed-icon-btn" @click="skipBackward" :title="$t('audioPlayer.rewind10s')">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
                  <path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8" />
                  <path d="M3 3v5h5" />
                </svg>
              </button>

              <!-- 快進 10s -->
              <button class="collapsed-icon-btn" @click="skipForward" :title="$t('audioPlayer.fastForward10s')">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
                  <path d="M21 12a9 9 0 1 1-9-9c2.52 0 4.93 1 6.74 2.74L21 8" />
                  <path d="M21 3v5h-5" />
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

        <!-- C-alt) 音檔已過期時顯示提示 icon -->
        <div
          v-if="currentTranscript.audioExpired"
          v-show="!isEffectivelyCollapsed"
          class="audio-expired-info"
        >
          <div class="audio-expired-icon-wrapper">
            <svg class="audio-expired-icon" width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">
              <circle cx="12" cy="12" r="10" />
              <line x1="12" y1="8" x2="12" y2="12" />
              <line x1="12" y1="16" x2="12.01" y2="16" />
            </svg>
            <div class="audio-expired-tooltip">
              {{ $t('audioPlayer.audioExpiredTooltip', { days: currentTranscript.audioRetentionDays }) }}
            </div>
          </div>
        </div>

        <!-- C) AudioPlayer 始終掛載，收合時隱藏（保持 audio element 活躍） -->
        <AudioPlayer
          v-if="currentTranscript.hasAudio"
          v-show="!isEffectivelyCollapsed"
          ref="audioPlayerRef"
          class="desktop-audio-player"
          :has-audio-element="true"
          :audio-url="audioUrl"
          :audio-error="audioError"
          :is-playing="isPlaying"
          :volume="volume"
          :is-muted="isMuted"
          :playback-rate="playbackRate"
          :progress-percent="progressPercent"
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
          @seek="seekToTime"
          @audio-loaded="handleAudioLoaded"
          @audio-error="handleAudioError"
          @update-progress="updateProgress"
          @update-duration="updateDuration"
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
          :display-mode="displayMode"
          :is-content-ready="currentTranscript.status === 'completed'"
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
            <!-- 編輯模式：純文字 contenteditable;segment 視覺層由 CSS Highlight 與 overlay 提供 -->
            <div
              v-else-if="isEditing"
              class="transcript-display editing"
              :class="{ 'alt-segment-hover': hoverChipVisible }"
              contenteditable="true"
              :key="`transcript-editing-${contentVersion}`"
              ref="textareaRef"
              v-text="currentTranscript.content"
              @keydown="handleContentEditableKeyDown"
              @paste="handlePaste"
              @input="segOffsets.handleInput($event.currentTarget)"
              @compositionstart="segOffsets.handleCompositionStart()"
              @compositionend="handleCompositionEnd($event)"
              @mousemove="handleEditorMouseMove"
              @mousedown="handleEditorClickInEditing"
              @scroll="handleEditorScroll"
            ></div>
            <!-- 非編輯模式：使用 v-for 渲染高亮和標記 -->
            <div
              v-else
              class="transcript-display"
              :class="{ 'alt-pressed': isAltPressed && currentTranscript.hasAudio }"
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
                      <path d="M 4 6 L 1 2 L 7 2 Z" />
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
                      :data-segment-index="part.segmentIndex"
                      :data-start-time="part.start"
                      @click="handleTextClick(part.start, $event)"
                    >{{ subPart.text }}<span v-if="subIndex === 0" class="text-timecode-tooltip">
                        {{ formatTime(part.start) }}
                      </span></span>
                  </template>
                </span>
              </template>
            </div>
            <!-- Alt hover timecode chip (只在編輯模式 + Alt 按住 + hover 到 segment 時顯示) -->
            <div
              v-show="isEditing && hoverChipVisible"
              ref="hoverChipRef"
              class="segment-hover-chip"
              :style="hoverChipStyle"
            >{{ hoverChipTime }}</div>
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

    <!-- 手機版音檔過期提示 -->
    <div
      v-if="currentTranscript.audioExpired"
      class="mobile-audio-player mobile-audio-expired-info"
    >
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">
        <circle cx="12" cy="12" r="10" />
        <line x1="12" y1="8" x2="12" y2="12" />
        <line x1="12" y1="16" x2="12.01" y2="16" />
      </svg>
      <span>{{ $t('audioPlayer.audioExpiredTitle') }}</span>
    </div>

    <!-- 手機版音訊播放器（固定在底部，純 UI，無 <audio> 元素） -->
    <AudioPlayer
      v-if="currentTranscript.hasAudio"
      class="mobile-audio-player"
      :audio-url="audioUrl"
      :audio-error="audioError"
      :is-playing="isPlaying"
      :volume="volume"
      :is-muted="isMuted"
      :playback-rate="playbackRate"
      :progress-percent="progressPercent"
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
      @seek="seekToTime"
      @audio-loaded="handleAudioLoaded"
      @audio-error="handleAudioError"
      @update-progress="updateProgress"
      @update-duration="updateDuration"
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

    <!-- 分享對話框 -->
    <ShareDialog
      v-if="currentTranscript"
      v-model:show="showShareDialog"
      :task-id="currentTranscript.task_id"
      :initial-share-token="currentTranscript.share_token || null"
      :initial-share-expires-at="currentTranscript.share_token_expires || null"
    />

    <!-- 標籤編輯 BottomSheet -->
    <BottomSheet v-model="showTagSheet" :title="$t('taskList.editTags')">
      <div class="tag-sheet-body">
        <TaskTagsSection
          ref="tagSheetRef"
          :task-id="currentTranscript.task_id"
          :tags="currentTranscript.tags"
          :all-tags="allTags"
          :no-click-outside="true"
          @tags-updated="handleTagsUpdated"
        />
      </div>
    </BottomSheet>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted, watch, nextTick } from 'vue'
import { useRoute, useRouter, onBeforeRouteLeave } from 'vue-router'
import { useI18n } from 'vue-i18n'

const { t: $t } = useI18n()

// 子組件
import TranscriptHeader from '../components/transcript/TranscriptHeader.vue'
import ShareDialog from '../components/transcript/ShareDialog.vue'
import AudioPlayer from '../components/transcript/AudioPlayer.vue'
import SubtitleTable from '../components/transcript/SubtitleTable.vue'
import DownloadDialog from '../components/transcript/DownloadDialog.vue'
import TaskInfoCard from '../components/transcript/TaskInfoCard.vue'
import BottomSheet from '../components/common/BottomSheet.vue'
import TaskTagsSection from '../components/task/TaskTagsSection.vue'
import DisplaySettingsCard from '../components/transcript/DisplaySettingsCard.vue'
import AISummary from '../components/transcript/AISummary.vue'
import KeyboardShortcutsInfo from '../components/transcript/KeyboardShortcutsInfo.vue'
import PlaybackSpeedControl from '../components/transcript/PlaybackSpeedControl.vue'

// API 服務
import { taskService, summaryService } from '../api/services.js'
import api from '../utils/api'
import { NEW_ENDPOINTS } from '../api/endpoints'

// Composables
import { useDisplayPreferences } from '../composables/transcript/useDisplayPreferences'
import { useTranscriptData } from '../composables/transcript/useTranscriptData'
import { useAudioPlayer } from '../composables/transcript/useAudioPlayer'
import { formatTime } from '../utils/formatTime'
import { useSubtitleMode } from '../composables/transcript/useSubtitleMode'
import { useTranscriptEditor } from '../composables/transcript/useTranscriptEditor'
import { useSegmentMarkers } from '../composables/transcript/useSegmentMarkers'
import {
  extractText,
  useSegmentEditingOffsets,
} from '../composables/transcript/useSegmentEditingOffsets'
import { useKeyboardShortcuts } from '../composables/transcript/useKeyboardShortcuts'
import { useSegmentNavigation } from '../composables/transcript/useSegmentNavigation'
import { useTranscriptDownload } from '../composables/transcript/useTranscriptDownload'
import { useSearchReplace } from '../composables/transcript/useSearchReplace'
import { useTaskTags } from '../composables/task/useTaskTags'
import { isModifierPressed } from '../utils/platform'
import { useAuthStore } from '../stores/auth'

const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()

// 組件引用
const audioPlayerRef = ref(null)
const headerRef = ref(null)

// 顯示偏好 + 面板版面（同步邏輯封裝在 composable 內）
const {
  isLeftPanelCollapsed,
  isMobileDrawerOpen,
  isMobileView,
  isEffectivelyCollapsed,
  isDarkMode,
  contentFontSize,
  contentFontWeight,
  contentFontFamily,
  showTimecodeMarkers,
  savedTimecodeMarkersState,
} = useDisplayPreferences()

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
  updateTags,
  cancelPendingRequests,
} = useTranscriptData()

// 動態更新頁面標題：任務名稱 - Sound Lite
watch(
  () => currentTranscript.value?.custom_name || currentTranscript.value?.filename,
  (name) => {
    document.title = name ? `${name} - Sound Lite` : 'Sound Lite'
  }
)

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
  currentTime: audioCurrentTime,
  duration,
  progressPercent,
  displayTime,
  volume,
  isMuted,
  playbackRate,
  audioUrl,
  audioError,
  getAudioUrl,
  initAudioUrl,
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
  cleanup: cleanupAudioPlayer
} = useAudioPlayer()

// Sync audioElement ref from the desktop AudioPlayer component (which owns the <audio> element)
watch(audioPlayerRef, (newRef) => {
  if (newRef?.audioElement) {
    audioElement.value = newRef.audioElement
  }
}, { immediate: true })

onMounted(() => {
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

// kebab「複製文字」用：純文字，不含時間碼與講者標籤
const copyableText = computed(() => {
  if (displayMode.value === 'paragraph') {
    return currentTranscript.value?.content || ''
  }
  return groupedSegments.value
    .map(group => group.combinedText.trim())
    .filter(Boolean)
    .join('\n\n')
})

// 重新定義 hasUnsavedChanges，檢查實際的 DOM 內容
const hasUnsavedChanges = computed(() => {
  if (!isEditing.value) return false

  if (displayMode.value === 'paragraph') {
    if (!textareaRef.value) return false
    const currentContent = extractText(textareaRef.value)
    return currentContent !== originalContent.value
  } else if (displayMode.value === 'subtitle') {
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
} = useSegmentMarkers()

// 編輯期 segment offset 追蹤（純文字編輯模式下的 segment 對應）
const segOffsets = useSegmentEditingOffsets()

// ========== 搜尋/取代 ==========
const {
  searchText,
  replaceText,
  searchMatches,
  currentMatchIndex,
  matchCase,
  matchWholeWord,
  isReplacing,
  contentVersion,
  handleSearch,
  goToPreviousMatch,
  goToNextMatch,
  handleReplaceCurrent,
  handleReplaceAllNew,
  getContentPartsWithHighlight,
  splitTextWithHighlight,
  clearHighlights,
  reSearch,
  reapplyHighlightsIfNeeded,
  applySearchHighlightsWithCSS,
} = useSearchReplace({
  textareaRef,
  currentTranscript,
  displayMode,
  isEditing,
  segments,
  groupedSegments,
  segmentMarkers,
  generateSegmentMarkers,
  segOffsets,
})

// ========== Segment Navigation (Alt+Click seek, hover chip, highlight) ==========
const {
  isAltPressed,
  hoverChipVisible,
  hoverChipTime,
  hoverChipStyle,
  handleEditorMouseMove,
  handleEditorClickInEditing,
  handleEditorScroll,
  handleMarkerClick,
  handleTextClick,
} = useSegmentNavigation({
  textareaRef,
  segOffsets,
  isEditing,
  displayMode,
  hasAudio: computed(() => currentTranscript.value.hasAudio),
  seekToTime,
  headerRef,
  isModifierPressed,
})

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
// Safari IME 守衛：compositionend 在 Safari 先於 keydown 觸發，
// 導致確認選字的 Enter 的 isComposing 已是 false，需自行追蹤
let compositionJustEnded = false

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

// Expose audio controls via a ref-like interface for useKeyboardShortcuts
const audioControls = computed(() => {
  if (!hasAudio.value) return null
  return {
    togglePlayPause,
    skipBackward,
    skipForward,
    toggleMute,
    setPlaybackRate,
    playbackRate,
  }
})
useKeyboardShortcuts(audioControls, { isEditing, isEditingTitle })

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
    // 初始化音訊 URL 及 token 自動刷新
    if (result.audioUrl) {
      initAudioUrl(taskId)
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

  // 段落模式：初始化編輯期 segment offset 追蹤（等 contenteditable 掛載）
  if (displayMode.value === 'paragraph') {
    nextTick(() => {
      if (textareaRef.value) {
        // 防禦：若 segmentMarkers 為空（例如儲存後 content 與 segments 不同步導致 match 失敗），
        // 在 initEditing 前用當前 DOM 內容重產一次
        if (!segmentMarkers.value?.length && segments.value?.length) {
          const content = textareaRef.value.textContent || currentTranscript.value?.content || ''
          if (content) generateSegmentMarkers(segments.value, content)
        }
        segOffsets.initEditing(textareaRef.value, segmentMarkers.value)
      }
    })
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

  reapplyHighlightsIfNeeded()
}

// 取消編輯的包裝函數（保存滾動位置）
function handleCancelEditing() {
  clearHighlights()

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

  // 清空編輯期 segment offset 追蹤
  segOffsets.resetEditing()

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

  reSearch()
}

// 儲存編輯的包裝函數
async function saveEditing() {
  clearHighlights()

  let contentToSave = ''
  let segmentsToSave = null

  // 保存滾動位置（段落模式）
  let savedScrollTop = 0
  if (displayMode.value === 'paragraph' && textareaRef.value) {
    // 滾動發生在 .transcript-display 元素本身
    savedScrollTop = textareaRef.value.scrollTop
  }

  if (displayMode.value === 'paragraph') {
    // 從 contenteditable div 提取純文字 + 用 editSegmentRanges 切出每段新文字
    if (textareaRef.value) {
      const { fullText, updatedSegments, hasChanges: segOffsetsHasChanges } =
        segOffsets.extractForSave(textareaRef.value, segments.value)
      contentToSave = fullText
      currentTranscript.value.content = contentToSave

      // segOffsets 內部只比對 slice 跟當下 segments.value;若搜尋取代已經先把
      // segments.value 改過,內部會偵測不到變更。額外跟編輯前快照比對,確保
      // 取代後馬上存檔也能正確把 segments 送到後端。
      let hasChanges = segOffsetsHasChanges
      if (
        !hasChanges &&
        originalSegments.value.length > 0 &&
        originalSegments.value.length === segments.value.length
      ) {
        for (let i = 0; i < segments.value.length; i++) {
          const a = (segments.value[i].text ?? '').trim()
          const b = (originalSegments.value[i]?.text ?? '').trim()
          if (a !== b) {
            hasChanges = true
            break
          }
        }
      }
      if (hasChanges) {
        segmentsToSave = updatedSegments
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

    // 清空編輯期 segment offset 追蹤
    segOffsets.resetEditing()

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

    reSearch()
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

// ========== 分享功能 ==========
// 邏輯封裝在 components/transcript/ShareDialog.vue
// Parent 只需控制可見性；taskId 與初始 share 狀態用 props 傳入
const showShareDialog = ref(false)

function handleShare() {
  showShareDialog.value = true
}

const hoverChipRef = ref(null)

// 處理貼上事件，只允許純文字
function handlePaste(e) {
  e.preventDefault()
  const text = e.clipboardData?.getData('text/plain') || ''
  if (text) {
    document.execCommand('insertText', false, text)
  }
}

// Safari IME 守衛：compositionend 在 Safari 先於 keydown 觸發，
// setTimeout(0) 確保 flag 在同一批 keydown 事件處理後才清掉
function handleCompositionEnd(e) {
  compositionJustEnded = true
  segOffsets.handleCompositionEnd(e.currentTarget)
  setTimeout(() => { compositionJustEnded = false }, 0)
}

// 處理 contenteditable 區域的按鍵事件（使用 Alt 作為修飾鍵）
function handleContentEditableKeyDown(e) {
  // Intercept Enter to insert a literal '\n' into the text node so the DOM stays
  // flat and CSS Custom Highlight Ranges survive (AltHL + search highlight).
  //
  // 關鍵守衛 e.isComposing：注音/拼音 IME 確認選字時 key 也是 'Enter'，
  // 若在 composition 中 preventDefault + 改 DOM，會把 IME commit 流程攪爛。
  // handleInput 在 isComposing.value=true 期間被 short-circuit，
  // 到 compositionend 才看到「IME 字 + 亂塞的 \n」混合 DOM，diffSingleRegion
  // 把中間整段標為「替換」，applyAnchorRule 把落在區段內的 segment 全部 drop
  // → editSegmentRanges 變空 → AltHL 完全失效。
  //
  // 不用 document.execCommand('insertText', '\n')：實測 Chrome 仍會產生 <div>
  // 包裝（不是註解宣稱的「flat text node」）；改用 Range API 直接插入字面 \n
  // 的 text node，DOM 真正保持 flat。Range mutation 不會自動 fire input event，
  // 手動呼叫 segOffsets.handleInput 同步狀態。
  if (e.key === 'Enter' && !e.isComposing && !compositionJustEnded) {
    e.preventDefault()
    const sel = window.getSelection()
    if (sel && sel.rangeCount > 0) {
      const range = sel.getRangeAt(0)
      range.deleteContents()
      const nl = document.createTextNode('\n')
      range.insertNode(nl)
      range.setStartAfter(nl)
      range.setEndAfter(nl)
      sel.removeAllRanges()
      sel.addRange(range)
      segOffsets.handleInput(e.currentTarget)
    }
    return
  }

  if (!e.altKey) return

  // Alt + ArrowUp: 加速播放
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

// 標籤編輯 BottomSheet
const showTagSheet = ref(false)
const tagSheetRef = ref(null)

watch(showTagSheet, (val) => {
  if (val) {
    nextTick(() => tagSheetRef.value?.startEditing())
  }
})

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
  // Alt key listeners + segment nav listeners: managed by useSegmentNavigation()
  // resize listener: 由 useDisplayPreferences() 內部 onMounted 註冊

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

  // segment-highlight cleanup: managed by useSegmentNavigation() onUnmounted
  clearHighlights()

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
  // Alt key listeners: managed by useSegmentNavigation() onUnmounted
  // resize listener: 由 useDisplayPreferences() 內部 onUnmounted 移除

  document.body.classList.remove('editing-transcript')
  document.body.classList.remove('transcript-detail-page')

  // 清理音訊播放器資源（停止 token 自動刷新定時器）
  cleanupAudioPlayer()

  // 取消所有尚未完成的 API 請求
  cancelPendingRequests()
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
    // 切換任務前先離開編輯狀態
    if (isEditing.value) {
      handleCancelEditing()
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
/* 標籤編輯 BottomSheet */
.tag-sheet-body {
  width: 100%;
}
.tag-sheet-body :deep(.task-tags-section) {
  display: flex;
  width: 100%;
}
.tag-sheet-body :deep(.tag-edit-mode) {
  width: 100%;
  box-sizing: border-box;
}

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
}

/* Alt 鍵按下時的可點擊文字樣式（透過 parent .alt-pressed 切換，
   避免一次 patch 數百個 span 的 class —— Safari 上會明顯卡頓）
   只套用到 .marker-wrapper 內的 .text-part：原本只有這些 span 有 click handler */
.transcript-display.alt-pressed .marker-wrapper .text-part {
  background-color: rgba(229, 179, 133, 0.25);
  cursor: pointer;
}

.transcript-display.alt-pressed .marker-wrapper .text-part:hover {
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

/* A+ 編輯模式 Alt segment 高亮 */
::highlight(segment-highlight) {
  background-color: rgba(196, 140, 226, 0.175);
}

/* A+ Alt + hover 到 segment 時,游標改為 pointer */
.transcript-display.editing.alt-segment-hover,
.transcript-display.editing.alt-segment-hover * {
  cursor: pointer !important;
}

/* A+ 編輯模式 Alt hover timecode chip */
.segment-hover-chip {
  position: absolute;
  transform: translate(-50%, calc(-100% - 4px));
  padding: 4px 8px;
  background: rgba(0, 0, 0, 0.85);
  color: white;
  border-radius: 4px;
  font-size: 11px;
  font-weight: 500;
  white-space: nowrap;
  pointer-events: none;
  z-index: 1000;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.2);
}

.segment-hover-chip::after {
  content: '';
  position: absolute;
  top: 100%;
  left: 50%;
  transform: translateX(-50%);
  border: 4px solid transparent;
  border-top-color: rgba(0, 0, 0, 0.85);
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
  display: none;
}

.transcript-display.alt-pressed .text-timecode-tooltip {
  display: inline-block;
}

.transcript-display.alt-pressed .text-part:hover .text-timecode-tooltip {
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

/* === 音訊過期提示 === */
.audio-expired-info {
  display: flex;
  justify-content: center;
  align-items: center;
  padding: 16px 8px;
}

.audio-expired-icon-wrapper {
  position: relative;
  display: inline-flex;
  align-items: center;
  cursor: default;
}

.audio-expired-icon {
  color: var(--main-text);
  opacity: 0.45;
  transition: opacity 0.2s ease;
}

.audio-expired-icon-wrapper:hover .audio-expired-icon {
  opacity: 0.75;
}

.audio-expired-tooltip {
  display: none;
  position: absolute;
  left: 50%;
  bottom: calc(100% + 8px);
  transform: translateX(-50%);
  background: var(--nav-bg);
  color: var(--main-text);
  font-size: 0.78rem;
  line-height: 1.5;
  padding: 8px 12px;
  border-radius: 8px;
  width: 220px;
  text-align: center;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
  pointer-events: none;
  z-index: 200;
  white-space: normal;
}

.audio-expired-tooltip::after {
  content: '';
  position: absolute;
  top: 100%;
  left: 50%;
  transform: translateX(-50%);
  border: 6px solid transparent;
  border-top-color: var(--nav-bg);
}

.audio-expired-icon-wrapper:hover .audio-expired-tooltip {
  display: block;
}

/* 手機版過期提示 */
.mobile-audio-expired-info {
  display: none;
  align-items: center;
  gap: 8px;
  color: var(--main-text);
  opacity: 0.55;
  font-size: 0.8rem;
  padding: 8px 12px;
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
  bottom: calc(90px + env(safe-area-inset-bottom, 0px));
  right: calc(16px + env(safe-area-inset-right, 0px));
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

  /* 顯示手機版過期提示 */
  .mobile-audio-expired-info {
    display: flex;
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
    bottom: calc(76px + env(safe-area-inset-bottom, 0px));
    right: calc(12px + env(safe-area-inset-right, 0px));
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
