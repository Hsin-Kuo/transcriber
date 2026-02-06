<template>
  <header class="detail-header">
    <div class="header-left">
      <!-- 返回按鈕 -->
      <button @click="$emit('go-back')" class="btn-back-icon">
        <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M19 12H5M12 19l-7-7 7-7"/>
        </svg>
      </button>

      <!-- 任務名稱 -->
      <div class="task-name-section">
        <input
          v-if="isEditingTitle"
          ref="titleInputRef"
          :value="editingTaskName"
          type="text"
          class="title-input"
          @input="$emit('update:editingTaskName', $event.target.value)"
          @blur="$emit('save-task-name')"
          @keyup.enter="$emit('save-task-name')"
          @keyup.esc="$emit('cancel-title-edit')"
        />
        <h1 v-else @click="$emit('start-title-edit')" class="editable-title">
          {{ taskDisplayName }}
        </h1>
      </div>

      <!-- 元數據 -->
      <TranscriptMetadata
        :created-at="createdAt"
        :duration-text="durationText"
        layout="horizontal"
        :show-date-icon="false"
      />
    </div>

    <div class="header-right">
      <!-- 搜尋按鈕 -->
      <div class="search-container">
        <button
          @click.stop="toggleSearch"
          class="btn btn-header btn-icon search-btn btn-expandable"
          :class="{ active: showSearchPopup }"
        >
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <circle cx="11" cy="11" r="8"/>
            <line x1="21" y1="21" x2="16.65" y2="16.65"/>
          </svg>
          <span class="btn-text">{{ $t('searchReplace.search') }}</span>
        </button>

        <!-- 搜尋/取代浮窗 -->
        <SearchReplacePopup
          v-if="showSearchPopup"
          :search-text="searchText"
          :replace-text="replaceText"
          :is-editing="isEditing"
          :total-matches="totalMatches"
          :current-match-index="currentMatchIndex"
          :match-case="matchCase"
          :match-whole-word="matchWholeWord"
          @update:search-text="$emit('update:searchText', $event)"
          @update:replace-text="$emit('update:replaceText', $event)"
          @update:match-case="$emit('update:matchCase', $event)"
          @update:match-whole-word="$emit('update:matchWholeWord', $event)"
          @search="$emit('search', $event)"
          @go-to-previous="$emit('go-to-previous')"
          @go-to-next="$emit('go-to-next')"
          @replace-current="$emit('replace-current', $event)"
          @replace-all="$emit('replace-all', $event)"
          @close="closeSearch"
        />
      </div>

      <!-- 編輯/儲存按鈕 -->
      <button v-if="!isEditing" @click="$emit('start-editing')" class="btn btn-header btn-expandable">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"></path>
          <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"></path>
        </svg>
        <span class="btn-text">{{ $t('transcriptDetail.edit') }}</span>
      </button>
      <button v-else @click="$emit('save-editing')" class="btn btn-header btn-primary btn-expandable">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <polyline points="20 6 9 17 4 12"></polyline>
        </svg>
        <span class="btn-text">{{ $t('transcriptDetail.save') }}</span>
      </button>
      <!-- 取消按鈕（編輯模式） -->
      <button v-if="isEditing" @click="$emit('cancel-editing')" class="btn btn-header btn-expandable">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <line x1="18" y1="6" x2="6" y2="18"></line>
          <line x1="6" y1="6" x2="18" y2="18"></line>
        </svg>
        <span class="btn-text">{{ $t('transcriptDetail.cancel') }}</span>
      </button>

      <!-- 講者設定按鈕（僅字幕模式且有講者資訊時顯示） -->
      <div
        v-if="displayMode === 'subtitle' && hasSpeakerInfo && uniqueSpeakers.length > 0"
        class="speaker-settings-container"
        ref="speakerSettingsRef"
      >
        <button
          @click.stop="toggleSpeakerSettings"
          class="btn btn-header btn-icon btn-expandable"
          :class="{ active: showSpeakerSettings }"
        >
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"></path>
            <circle cx="9" cy="7" r="4"></circle>
            <path d="M23 21v-2a4 4 0 0 0-3-3.87"></path>
            <path d="M16 3.13a4 4 0 0 1 0 7.75"></path>
          </svg>
          <span class="btn-text">{{ $t('subtitleTable.speakerNames') }}</span>
        </button>

        <!-- 講者設定下拉面板 -->
        <div v-if="showSpeakerSettings" class="speaker-settings-panel">
          <label class="panel-title">{{ $t('subtitleTable.speakerNames') }}</label>
          <div class="speaker-mappings">
            <div
              v-for="speaker in uniqueSpeakers"
              :key="speaker"
              class="speaker-item"
            >
              <label class="speaker-code">{{ speaker }}</label>
              <input
                type="text"
                :data-speaker="speaker"
                :value="speakerNames[speaker] || ''"
                @input="updateSpeakerName(speaker, $event.target.value)"
                :placeholder="$t('subtitleTable.speakerPlaceholder', { number: speaker.replace('SPEAKER_', '') })"
                class="speaker-input"
              />
            </div>
          </div>
        </div>
      </div>

      <!-- 更多選項按鈕 -->
      <div class="more-options-container" ref="moreOptionsRef">
        <button
          @click.stop="toggleMoreOptions"
          class="btn btn-header btn-icon"
          :class="{ active: showMoreOptions }"
        >
          <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor">
            <circle cx="12" cy="5" r="2"/>
            <circle cx="12" cy="12" r="2"/>
            <circle cx="12" cy="19" r="2"/>
          </svg>
        </button>

        <!-- 下拉選單 -->
        <div v-if="showMoreOptions" class="more-options-panel">
          <!-- 下載按鈕 -->
          <button class="action-btn" @click="handleDownload">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path>
              <polyline points="7 10 12 15 17 10"></polyline>
              <line x1="12" y1="15" x2="12" y2="3"></line>
            </svg>
            <span>{{ $t('transcriptDetail.download') }}</span>
          </button>

          <!-- 刪除按鈕 -->
          <button class="action-btn" @click="handleDeleteTask">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <polyline points="3 6 5 6 21 6"></polyline>
              <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path>
              <line x1="10" y1="11" x2="10" y2="17"></line>
              <line x1="14" y1="11" x2="14" y2="17"></line>
            </svg>
            <span>{{ $t('transcriptDetail.delete') }}</span>
          </button>
        </div>
      </div>
    </div>
  </header>
</template>

<script setup>
import { ref, watch, nextTick, onMounted, onUnmounted } from 'vue'
import TranscriptMetadata from './TranscriptMetadata.vue'
import SearchReplacePopup from './SearchReplacePopup.vue'

const props = defineProps({
  taskDisplayName: {
    type: String,
    default: ''
  },
  createdAt: [String, Number],
  durationText: String,
  isEditing: {
    type: Boolean,
    default: false
  },
  isEditingTitle: {
    type: Boolean,
    default: false
  },
  editingTaskName: {
    type: String,
    default: ''
  },
  displayMode: {
    type: String,
    default: 'paragraph'
  },
  showTimecodeMarkers: {
    type: Boolean,
    default: false
  },
  timeFormat: {
    type: String,
    default: 'start'
  },
  densityThreshold: {
    type: Number,
    default: 30
  },
  speakerNames: {
    type: Object,
    default: () => ({})
  },
  hasSpeakerInfo: {
    type: Boolean,
    default: false
  },
  uniqueSpeakers: {
    type: Array,
    default: () => []
  },
  // 搜尋相關 props
  searchText: {
    type: String,
    default: ''
  },
  replaceText: {
    type: String,
    default: ''
  },
  totalMatches: {
    type: Number,
    default: 0
  },
  currentMatchIndex: {
    type: Number,
    default: 0
  },
  matchCase: {
    type: Boolean,
    default: false
  },
  matchWholeWord: {
    type: Boolean,
    default: false
  }
})

const emit = defineEmits([
  'go-back',
  'start-title-edit',
  'save-task-name',
  'cancel-title-edit',
  'update:editingTaskName',
  'start-editing',
  'save-editing',
  'cancel-editing',
  'download',
  'delete-task',
  'update:showTimecodeMarkers',
  'update:timeFormat',
  'update:densityThreshold',
  'update:speakerNames',
  // 搜尋相關 emits
  'update:searchText',
  'update:replaceText',
  'update:matchCase',
  'update:matchWholeWord',
  'search',
  'go-to-previous',
  'go-to-next',
  'replace-current',
  'replace-all'
])

// Refs
const titleInputRef = ref(null)
const moreOptionsRef = ref(null)
const speakerSettingsRef = ref(null)
const showMoreOptions = ref(false)
const showSearchPopup = ref(false)
const showSpeakerSettings = ref(false)

// 切換搜尋浮窗
function toggleSearch() {
  if (showSearchPopup.value) {
    // 關閉時清空內容
    closeSearch()
  } else {
    // 打開時關閉更多選項
    showSearchPopup.value = true
    showMoreOptions.value = false
  }
}

// 關閉搜尋浮窗並清空內容
function closeSearch() {
  showSearchPopup.value = false
  emit('update:searchText', '')
  emit('update:replaceText', '')
  emit('search', '')  // 觸發搜尋以清除高亮
}

// 切換更多選項選單
function toggleMoreOptions() {
  showMoreOptions.value = !showMoreOptions.value
  // 關閉其他面板
  if (showMoreOptions.value) {
    showSearchPopup.value = false
    showSpeakerSettings.value = false
  }
}

// 切換講者設定面板
function toggleSpeakerSettings() {
  showSpeakerSettings.value = !showSpeakerSettings.value
  // 關閉其他面板
  if (showSpeakerSettings.value) {
    showSearchPopup.value = false
    showMoreOptions.value = false
  }
}

// 點擊外部關閉選單（僅關閉更多選項和講者設定，搜尋浮窗需手動關閉）
function handleClickOutside(event) {
  if (moreOptionsRef.value && !moreOptionsRef.value.contains(event.target)) {
    showMoreOptions.value = false
  }
  if (speakerSettingsRef.value && !speakerSettingsRef.value.contains(event.target)) {
    showSpeakerSettings.value = false
  }
}

// 滾輪滾動時關閉選單（如果滾動發生在面板外部）
function handleWheel(event) {
  // 處理更多選項面板
  if (showMoreOptions.value) {
    const panel = moreOptionsRef.value?.querySelector('.more-options-panel')
    if (panel && event.target !== panel && !panel.contains(event.target)) {
      showMoreOptions.value = false
    }
  }
  // 處理講者設定面板
  if (showSpeakerSettings.value) {
    const panel = speakerSettingsRef.value?.querySelector('.speaker-settings-panel')
    if (panel && event.target !== panel && !panel.contains(event.target)) {
      showSpeakerSettings.value = false
    }
  }
}

// 更新講者名稱
function updateSpeakerName(speaker, value) {
  const newSpeakerNames = { ...props.speakerNames, [speaker]: value }
  emit('update:speakerNames', newSpeakerNames)
}

// 監聽編輯標題狀態，自動聚焦輸入框
watch(() => props.isEditingTitle, (newVal) => {
  if (newVal) {
    nextTick(() => {
      titleInputRef.value?.focus()
      titleInputRef.value?.select()
    })
  }
})

// 要 focus 的講者代碼
const pendingFocusSpeaker = ref(null)

// 打開更多選項面板（供外部調用）
function openMoreOptions() {
  showMoreOptions.value = true
  showSearchPopup.value = false
  showSpeakerSettings.value = false
}

// 關閉更多選項面板
function closeMoreOptions() {
  showMoreOptions.value = false
}

// 打開講者設定面板（供外部調用）
// speakerCode: 可選，指定要 focus 的講者輸入框
function openSpeakerSettings(speakerCode = null) {
  showSpeakerSettings.value = true
  showSearchPopup.value = false
  showMoreOptions.value = false

  // 如果指定了講者代碼，等面板展開後 focus 到該輸入框
  if (speakerCode) {
    pendingFocusSpeaker.value = speakerCode
    nextTick(() => {
      const input = document.querySelector(`input[data-speaker="${speakerCode}"]`)
      if (input) {
        input.focus()
        input.select()
      }
      pendingFocusSpeaker.value = null
    })
  }
}

// 關閉講者設定面板
function closeSpeakerSettings() {
  showSpeakerSettings.value = false
}

// 下載
function handleDownload() {
  showMoreOptions.value = false
  emit('download')
}

// 刪除任務
function handleDeleteTask() {
  showMoreOptions.value = false
  emit('delete-task')
}

// 暴露方法給父組件
defineExpose({
  openMoreOptions,
  closeMoreOptions,
  openSpeakerSettings,
  closeSpeakerSettings
})

onMounted(() => {
  document.addEventListener('click', handleClickOutside)
  // 使用 capture: true 在捕獲階段監聽滾輪事件
  window.addEventListener('wheel', handleWheel, { capture: true, passive: true })
})

onUnmounted(() => {
  document.removeEventListener('click', handleClickOutside)
  window.removeEventListener('wheel', handleWheel, { capture: true })
})
</script>

<style scoped>
/* Header */
.detail-header {
  position: sticky;
  top: 0;
  z-index: 100;
  display: flex;
  align-items: center;
  justify-content: space-between;
  height: var(--header-height, 70px);
  padding: 0 12px;
  border-bottom: 1px solid rgba(163, 177, 198, 0.15);
}

.header-left {
  display: flex;
  align-items: center;
  gap: 12px;
  flex: 1;
  min-width: 0;
}

.header-right {
  display: flex;
  align-items: center;
  gap: 16px;
  flex-shrink: 0;
  overflow: visible;
}

/* 返回按鈕 */
.btn-back-icon {
  width: 40px;
  height: 40px;
  border: none;
  background: var(--main-bg);
  border-radius: 10px;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.2s ease;
  color: var(--main-primary);
  flex-shrink: 0;
}

.btn-back-icon:hover {
  transform: translateY(-1px);
  background: var(--main-bg-hover, rgba(163, 177, 198, 0.15));
}

.btn-back-icon:active {
  transform: translateY(0);
}

/* Header 按鈕 */
.btn-header {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 14px;
  border: none;
  border-radius: 8px;
  background: #ffffff00;
  color: var(--main-text);
  cursor: pointer;
  font-size: 13px;
  font-weight: 500;
  transition: all 0.2s ease;
  white-space: nowrap;
}

.btn-header:hover {
  background: var(--main-bg-hover, rgba(163, 177, 198, 0.2));
  color: var(--main-primary);
}

.btn-header.btn-primary {
  background: var(--nav-active-bg);
  color: white;
}


.btn-header svg {
  stroke: currentColor;
  flex-shrink: 0;
}

.btn-header.btn-icon {
  padding: 8px;
}

.btn-header.btn-icon svg {
  stroke: none;
  fill: currentColor;
}

.btn-header.active {
  background: var(--main-bg-hover, rgba(163, 177, 198, 0.2));
  color: var(--main-primary);
}

/* 可展開按鈕：預設只顯示 icon，hover 時文字從下方出現 */
.btn-expandable {
  position: relative;
  padding: 8px;
  overflow: visible;
}

.btn-expandable .btn-text {
  position: absolute;
  top: calc(100% + 4px);
  left: 50%;
  transform: translateX(-50%);
  padding: 4px 8px;
  background: rgba(0, 0, 0, 0.85);
  color: white;
  border-radius: 4px;
  font-size: 12px;
  white-space: nowrap;
  opacity: 0;
  visibility: hidden;
  pointer-events: none;
  transition: opacity 0.15s ease, visibility 0.15s ease;
  z-index: 9999;
}

.btn-expandable .btn-text::before {
  content: '';
  position: absolute;
  bottom: 100%;
  left: 50%;
  transform: translateX(-50%);
  border: 5px solid transparent;
  border-bottom-color: rgba(0, 0, 0, 0.85);
}

.btn-expandable:hover .btn-text {
  opacity: 1;
  visibility: visible;
}

/* 任務名稱區域 */
.task-name-section {
  display: flex;
  flex-direction: column;
  min-width: 0;
  flex-shrink: 1;
}

.editable-title {
  font-size: 1.25rem;
  font-weight: 600;
  color: var(--main-text);
  margin: 0;
  cursor: pointer;
  padding: 6px 10px;
  border-radius: 6px;
  transition: all 0.2s ease;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.editable-title:hover {
  background: rgba(163, 177, 198, 0.1);
  color: var(--main-primary);
}

.title-input {
  width: 100%;
  max-width: 400px;
  padding: 6px 10px;
  font-size: 1.1rem;
  font-weight: 500;
  border: 2px solid var(--main-primary);
  border-radius: 6px;
  background: var(--main-bg);
  color: var(--main-text);
}

/* 搜尋容器 */
.search-container {
  position: relative;
}

/* 搜尋按鈕 SVG 使用 stroke */
.btn-header.btn-icon.search-btn svg {
  stroke: currentColor !important;
  fill: none !important;
}

/* 講者設定容器 */
.speaker-settings-container {
  position: relative;
}

.speaker-settings-panel {
  position: absolute;
  top: calc(100% + 8px);
  right: 0;
  min-width: 280px;
  max-height: 400px;
  overflow-y: auto;
  overflow-x: hidden;
  padding: 12px;
  background: var(--color-white, #ffffff);
  border: 1px solid rgba(163, 177, 198, 0.2);
  border-radius: 12px;
  box-shadow: 0 4px 20px rgba(0, 0, 0, 0.15);
  z-index: 1000;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.panel-title {
  font-size: 12px;
  font-weight: 600;
  color: var(--main-text-light);
}

/* 更多選項容器 */
.more-options-container {
  position: relative;
}

.more-options-panel {
  position: absolute;
  top: calc(100% + 8px);
  right: 0;
  min-width: 120px;
  max-height: 400px;
  overflow-y: auto;
  overflow-x: hidden;
  padding: 8px;
  background: var(--color-white, #ffffff);
  border: 1px solid rgba(163, 177, 198, 0.2);
  border-radius: 12px;
  box-shadow: 0 4px 20px rgba(0, 0, 0, 0.15);
  z-index: 1000;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.option-group {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.option-label {
  font-size: 12px;
  font-weight: 600;
  color: var(--main-text-light);
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
  accent-color: var(--main-primary);
}

.toggle-checkbox:disabled {
  cursor: not-allowed;
}

/* 時間格式切換 */
.time-format-toggle {
  display: flex;
  gap: 4px;
  background: var(--main-bg);
  border-radius: 8px;
  padding: 4px;
}

.format-btn {
  flex: 1;
  padding: 6px 12px;
  border: none;
  border-radius: 6px;
  background: transparent;
  color: var(--main-text-light);
  font-size: 12px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s ease;
}

.format-btn:hover {
  color: var(--main-text);
}

.format-btn.active {
  background: var(--main-primary);
  color: white;
}

/* 疏密度滑桿 */
.density-slider {
  width: 100%;
  height: 4px;
  border-radius: 2px;
  appearance: none;
  background: var(--main-bg);
  cursor: pointer;
}

.density-slider::-webkit-slider-thumb {
  appearance: none;
  width: 16px;
  height: 16px;
  border-radius: 50%;
  background: var(--main-primary);
  cursor: pointer;
  transition: transform 0.2s ease;
}

.density-slider::-webkit-slider-thumb:hover {
  transform: scale(1.2);
}

.slider-labels {
  display: flex;
  justify-content: space-between;
  font-size: 11px;
  color: var(--main-text-light);
}

/* 講者名稱設定 */
.speaker-mappings {
  display: flex;
  flex-direction: column;
  gap: 8px;
  overflow: hidden;
}

.speaker-item {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.speaker-code {
  font-size: 11px;
  font-weight: 600;
  color: var(--main-text-light);
  min-width: 70px;
  flex-shrink: 0;
}

.speaker-input {
  flex: 1;
  min-width: 0;
  padding: 6px 10px;
  border: 1px solid rgba(163, 177, 198, 0.3);
  border-radius: 6px;
  background: var(--main-bg);
  color: var(--main-text);
  font-size: 12px;
}

.speaker-input:focus {
  outline: none;
  border-color: var(--main-primary);
}

/* 操作按鈕區塊 */
.action-section {
  border-top: 1px solid rgba(163, 177, 198, 0.2);
  padding-top: 12px;
  margin-top: 4px;
}

.action-btn {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  padding: 8px 12px;
  border: none;
  border-radius: 6px;
  background: transparent;
  color: var(--main-text);
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s ease;
}

.action-btn:hover {
  background: rgba(163, 177, 198, 0.15);
  color: var(--main-primary);
}

.action-btn svg {
  flex-shrink: 0;
}

/* 刪除任務區塊 */
.delete-section {
  padding-top: 8px;
}

.delete-task-btn {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  padding: 8px 12px;
  border: none;
  border-radius: 6px;
  background: transparent;
  color: var(--color-danger, #ef4444);
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s ease;
}

.delete-task-btn:hover {
  background: rgba(239, 68, 68, 0.1);
}

.delete-task-btn svg {
  flex-shrink: 0;
}

/* 響應式 */
@media (max-width: 768px) {
  .detail-header {
    flex-direction: row;
    flex-wrap: wrap;
    align-items: center;
    gap: 0px;
    height: auto;
    padding: 2px 0px;
  }

  .header-left {
    flex: 1;
    flex-wrap: wrap;
    gap: 0px;
    min-width: 0;
  }

  /* 讓標題區域佔滿剩餘空間，使 metadata 換行 */
  .task-name-section {
    flex: 1;
    min-width: calc(100% - 44px); /* 減去返回按鈕寬度，強制 metadata 換行 */
  }

  /* Metadata 在標題下方、縮小字體 */
  .header-left :deep(.metadata-section) {
    width: 100%;
    padding-left: 44px; /* 對齊標題 */
    margin-top: -0.25rem;
    margin-bottom: 0.25rem;
  }

  .header-left :deep(.metadata-section .meta-item) {
    font-size: var(--font-size-xs);
    gap: 0.25rem;
  }

  .header-left :deep(.metadata-section .meta-item svg) {
    width: 0.75rem;
    height: 0.75rem;
  }

  .header-right {
    flex-shrink: 0;
    gap: 0px;
  }

  .editable-title {
    font-size: 1.1rem;
  }

  .btn-header {
    padding: 6px 2px;
    font-size: 12px;
  }

  .btn-header span {
    display: none;
  }
}
</style>
