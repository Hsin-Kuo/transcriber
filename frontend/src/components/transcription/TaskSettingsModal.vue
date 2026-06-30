<template>
  <Teleport to="body">
    <!-- 點遮罩不關閉（檔案已選好，避免誤觸丟棄）；僅關閉鈕 / 取消 / Esc 可關 -->
    <div v-if="visible" class="modal-overlay">
      <div
        ref="modalContainerRef"
        class="modal-container"
        role="dialog"
        aria-modal="true"
        :aria-label="$t('transcription.settingsModalTitle')"
      >
        <!-- 標題列（sticky） -->
        <div class="modal-header">
          <h2>{{ $t('transcription.settingsModalTitle') }}</h2>
          <button class="close-btn" @click="emitClose" :title="$t('common.close')" :aria-label="$t('common.close')">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <line x1="18" y1="6" x2="6" y2="18"></line>
              <line x1="6" y1="6" x2="18" y2="18"></line>
            </svg>
          </button>
        </div>

        <!-- 內容區（單欄、可捲動） -->
        <div class="modal-body">
          <!-- 1. 檔案資訊 -->
          <div class="modal-section file-section">
            <label class="section-label">{{ $t('transcription.fileInfo') }}</label>

            <!-- 合併模式：顯示多檔案資訊 -->
            <template v-if="isMergeMode">
              <div class="merge-info-header">
                <span class="merge-badge">🔀 {{ $t('transcription.mergeMode') }}</span>
                <span class="file-count">{{ $t('transcription.fileCount', { count: mergeFiles.length }) }}</span>
              </div>
              <ul class="merge-file-list">
                <li v-for="(file, idx) in mergeFiles" :key="idx" class="merge-file-item">
                  <span class="file-number">{{ idx + 1 }}.</span>
                  <TruncatedFilename :name="file.name" class="file-name" />
                  <span class="file-size">({{ formatFileSize(file.size) }})</span>
                </li>
              </ul>
              <!-- 任務名稱欄位 -->
              <div class="task-name-section">
                <label class="sub-label">{{ $t('transcription.taskName') }}</label>
                <input
                  type="text"
                  v-model="mergeTaskNameModel"
                  :placeholder="defaultMergeTaskName"
                  class="text-input task-name-input"
                />
                <p class="hint">{{ $t('transcription.mergeTaskNameHint') }}</p>
              </div>
            </template>

            <!-- 單檔模式：顯示單檔資訊 -->
            <template v-else>
              <div class="file-info">
                <span class="label">{{ $t('transcription.fileName') }}</span>
                <span class="value">{{ pendingFile?.name }}</span>
              </div>
              <div class="file-info" v-if="pendingFile">
                <span class="label">{{ $t('transcription.fileSize') }}</span>
                <span class="value">{{ (pendingFile.size / 1024 / 1024).toFixed(2) }} MB</span>
              </div>
            </template>

            <!-- 音檔保留規則：併入檔案資訊區塊底部小字 -->
            <div class="file-note">
              {{ $t('transcription.audioRetentionNote', { days: audioRetentionDays }) }}
            </div>
          </div>

          <!-- 2. 任務類型（大圖示卡片） -->
          <div class="modal-section task-type-section" data-tour="task-type">
            <label class="section-label">{{ $t('transcription.taskType') }}</label>

            <div class="task-type-cards" role="radiogroup" :aria-label="$t('transcription.taskTypeSelectAria')">
              <label class="type-card" :class="{ selected: taskTypeModel === 'paragraph' }">
                <input type="radio" name="taskType" value="paragraph" v-model="taskTypeModel" class="type-card-input" />
                <span class="type-card-icon" aria-hidden="true">
                  <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
                    <path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7z"></path>
                    <polyline points="14 2 14 8 20 8"></polyline>
                    <line x1="8" y1="13" x2="16" y2="13"></line>
                    <line x1="8" y1="17" x2="13" y2="17"></line>
                  </svg>
                </span>
                <span class="type-card-title">{{ $t('transcription.paragraph') }}</span>
                <span class="type-card-desc">{{ $t('transcription.paragraphHint') }}</span>
                <span class="type-card-check" aria-hidden="true">
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round">
                    <polyline points="20 6 9 17 4 12"></polyline>
                  </svg>
                </span>
              </label>

              <label class="type-card" :class="{ selected: taskTypeModel === 'subtitle' }">
                <input type="radio" name="taskType" value="subtitle" v-model="taskTypeModel" class="type-card-input" />
                <span class="type-card-icon" aria-hidden="true">
                  <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
                    <rect x="2" y="5" width="20" height="14" rx="2"></rect>
                    <line x1="6" y1="15" x2="12" y2="15"></line>
                    <line x1="15" y1="15" x2="18" y2="15"></line>
                  </svg>
                </span>
                <span class="type-card-title">{{ $t('transcription.subtitle') }}</span>
                <span class="type-card-desc">{{ $t('transcription.subtitleHint') }}</span>
                <span class="type-card-check" aria-hidden="true">
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round">
                    <polyline points="20 6 9 17 4 12"></polyline>
                  </svg>
                </span>
              </label>
            </div>
          </div>

          <!-- 3. 語言 -->
          <div class="modal-section language-section" data-tour="language">
            <label class="section-label">{{ $t('transcription.language') }}</label>
            <select v-model="languageModel" class="language-select">
              <option value="auto">{{ $t('transcription.autoDetect') }}</option>
              <option value="zh-TW">繁體中文</option>
              <option value="zh-CN">简体中文</option>
              <option value="zh">{{ $t('transcription.langChineseGeneric') }}</option>
              <option value="en">English</option>
              <option value="ja">日本語</option>
              <option value="ko">한국어</option>
            </select>
          </div>

          <!-- 4. 說話者辨識 -->
          <div class="modal-section diarize-section" data-tour="diarize">
            <label class="section-label">{{ $t('transcription.speakerDiarization') }}</label>

            <label class="toggle-label">
              <div class="toggle-switch-wrapper">
                <input type="checkbox" id="modal-diarize" v-model="diarizeModel" class="toggle-input" />
                <span class="toggle-slider"></span>
              </div>
              <span class="toggle-text">{{ $t('transcription.enable') }}</span>
            </label>

            <div class="sub-setting" v-if="diarizeModel">
              <label for="modal-maxSpeakers" class="sub-label">
                {{ $t('transcription.maxSpeakers') }}
                <span class="hint">{{ $t('transcription.maxSpeakersHint') }}</span>
              </label>
              <input
                type="number"
                id="modal-maxSpeakers"
                v-model.number="maxSpeakersModel"
                min="2"
                max="10"
                :placeholder="$t('transcription.autoDetect')"
                class="number-input"
              />
            </div>
          </div>

          <!-- 5. 標籤 -->
          <div class="modal-section tag-section">
            <label class="section-label">{{ $t('transcription.tags') }}</label>
            <div class="tag-input-container">
              <div class="tag-input-wrapper">
                <input
                  type="text"
                  v-model="tagInputModel"
                  @keydown="onTagKeydown"
                  :placeholder="$t('transcription.tagPlaceholder')"
                  class="text-input"
                />
                <button
                  type="button"
                  class="btn-add-tag"
                  @click="addTag"
                  :disabled="!tagInputModel.trim()"
                >
                  {{ $t('transcription.add') }}
                </button>
              </div>

              <!-- 快速選擇現有標籤（限制兩排，超出可手動展開） -->
              <div v-if="availableQuickTags.length > 0" class="quick-tags-section">
                <div
                  class="quick-tags"
                  :ref="quickTagsContainerRef"
                  :style="quickTagsContentStyle"
                >
                  <button
                    v-for="tag in availableQuickTags"
                    :key="tag"
                    type="button"
                    class="quick-tag-btn"
                    @click="addQuickTag(tag)"
                    :title="$t('transcription.addTagTooltip', { tag })"
                  >
                    + {{ tag }}
                  </button>
                </div>
                <button
                  v-if="quickTagsOverflowing"
                  type="button"
                  class="btn-toggle-quick-tags"
                  :class="{ expanded: !quickTagsCollapsed }"
                  @click="toggleQuickTags"
                >
                  <span>{{ quickTagsCollapsed ? $t('taskList.showMore') : $t('taskList.collapse') }}</span>
                  <svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                    <polyline points="6 9 12 15 18 9"></polyline>
                  </svg>
                </button>
              </div>

              <div v-if="tagsModel.length > 0" class="selected-tags">
                <span
                  v-for="(tag, index) in tagsModel"
                  :key="index"
                  class="selected-tag"
                >
                  {{ tag }}
                  <button
                    type="button"
                    class="remove-tag"
                    @click="removeTag(index)"
                    :title="$t('transcription.removeTagTooltip')"
                  >
                    ×
                  </button>
                </span>
              </div>
            </div>
          </div>
        </div>

        <!-- 動作按鈕（sticky footer） -->
        <div class="modal-footer">
          <button class="btn btn-cancel" @click="emitClose">{{ $t('transcription.cancel') }}</button>
          <button
            class="btn btn-primary btn-start"
            data-tour="start"
            @click="emitConfirm"
          >
            {{ $t('transcription.startTranscription') }}
          </button>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<script setup>
import { ref, computed, toRef, watch, onUnmounted } from 'vue'
import { useFocusTrap } from '../../composables/useFocusTrap'
import { useCollapsibleRows } from '../../composables/useCollapsibleRows'
import TruncatedFilename from '../common/TruncatedFilename.vue'

const props = defineProps({
  visible: { type: Boolean, default: false },
  isMergeMode: { type: Boolean, default: false },
  pendingFile: { type: Object, default: null },
  mergeFiles: { type: Array, default: () => [] },
  defaultMergeTaskName: { type: String, default: '' },
  allTags: { type: Array, default: () => [] },
  audioRetentionDays: { type: Number, default: 3 },
  // 是否允許 Esc 關閉（導覽期間設 false：示範跳窗只能由 driver 的 ✕ 結束）
  dismissible: { type: Boolean, default: true },
  // v-model 綁定（狀態仍由 TranscriptionView 持有，本元件為受控元件）
  taskType: { type: String, default: 'paragraph' },
  language: { type: String, default: 'auto' },
  diarize: { type: Boolean, default: true },
  maxSpeakers: { type: Number, default: null },
  tags: { type: Array, default: () => [] },
  tagInput: { type: String, default: '' },
  mergeTaskName: { type: String, default: '' },
})

const emit = defineEmits([
  'close', 'confirm',
  'update:taskType', 'update:language', 'update:diarize', 'update:maxSpeakers',
  'update:tags', 'update:tagInput', 'update:mergeTaskName',
])

// v-model proxy helper
function modelProxy(key) {
  return computed({
    get: () => props[key],
    set: (val) => emit(`update:${key}`, val),
  })
}

const taskTypeModel = modelProxy('taskType')
const languageModel = modelProxy('language')
const diarizeModel = modelProxy('diarize')
const maxSpeakersModel = modelProxy('maxSpeakers')
const tagsModel = modelProxy('tags')
const tagInputModel = modelProxy('tagInput')
const mergeTaskNameModel = modelProxy('mergeTaskName')

const modalContainerRef = ref(null)
useFocusTrap(modalContainerRef, toRef(props, 'visible'))

// Esc 關閉（useFocusTrap 刻意不處理 Esc，這裡自己掛）；dismissible=false 時不關（導覽中）
function onKeydown(e) {
  if (e.key === 'Escape' && props.dismissible) emitClose()
}
watch(() => props.visible, (open) => {
  if (open) document.addEventListener('keydown', onKeydown)
  else document.removeEventListener('keydown', onKeydown)
})
onUnmounted(() => document.removeEventListener('keydown', onKeydown))

function emitClose() { emit('close') }
function emitConfirm() { emit('confirm') }

function formatFileSize(bytes) {
  return (bytes / 1024 / 1024).toFixed(2) + ' MB'
}

// 可用的快速標籤（排除已選擇的）
const availableQuickTags = computed(() =>
  props.allTags.filter(tag => !tagsModel.value.includes(tag))
)

// 快速標籤區限制最多兩排，超出可手動展開
const {
  containerRef: quickTagsContainerRef,
  contentStyle: quickTagsContentStyle,
  overflowing: quickTagsOverflowing,
  isCollapsed: quickTagsCollapsed,
  toggle: toggleQuickTags,
} = useCollapsibleRows({
  itemSelector: '.quick-tag-btn',
  watchSources: [() => availableQuickTags.value.length],
})

// 標籤管理：操作 tags v-model（不可變更新，確保 emit）
function addTag() {
  const tag = tagInputModel.value.trim()
  if (tag && !tagsModel.value.includes(tag)) {
    tagsModel.value = [...tagsModel.value, tag]
  }
  tagInputModel.value = ''
}

function onTagKeydown(e) {
  if (e.key === 'Enter' || e.key === ',') {
    e.preventDefault()
    addTag()
  }
}

function addQuickTag(tag) {
  if (!tagsModel.value.includes(tag)) {
    tagsModel.value = [...tagsModel.value, tag]
  }
}

function removeTag(index) {
  tagsModel.value = tagsModel.value.filter((_, i) => i !== index)
}
</script>

<style scoped>
/* === 跳窗框架（沿用 MergeModal 規範） === */
.modal-overlay {
  position: fixed;
  inset: 0;
  background: var(--color-overlay);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
  animation: fadeIn 0.2s ease;
}

@keyframes fadeIn {
  from { opacity: 0; }
  to { opacity: 1; }
}

.modal-container {
  width: 90%;
  max-width: 560px;
  max-height: 85vh;
  background: var(--main-bg);
  border-radius: 20px;
  box-shadow: 0 20px 60px var(--color-overlay-light);
  display: flex;
  flex-direction: column;
  animation: slideUp 0.3s ease;
}

@keyframes slideUp {
  from {
    opacity: 0;
    transform: translateY(20px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

/* sticky header */
.modal-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 20px 24px;
  border-bottom: 1px solid rgba(var(--color-divider-rgb), 0.3);
  flex-shrink: 0;
}

.modal-header h2 {
  margin: 0;
  font-size: 20px;
  font-weight: 600;
  color: rgba(var(--color-text-dark-rgb), 0.9);
}

.close-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 36px;
  height: 36px;
  padding: 0;
  background: transparent;
  border: none;
  border-radius: 10px;
  color: rgba(var(--color-text-dark-rgb), 0.5);
  cursor: pointer;
  transition: all 0.2s;
}

.close-btn:hover {
  background: color-mix(in srgb, var(--color-danger) 10%, transparent);
  color: var(--color-danger);
}

/* 可捲動內容區（單欄） */
.modal-body {
  padding: 20px 24px;
  overflow-y: auto;
  flex: 1;
}

/* sticky footer */
.modal-footer {
  display: flex;
  justify-content: flex-end;
  align-items: center;
  gap: 12px;
  padding: 16px 24px;
  border-top: 1px solid rgba(var(--color-divider-rgb), 0.3);
  flex-shrink: 0;
}

/* === Section 共用 === */
.modal-section {
  margin-bottom: 24px;
}

.modal-section:last-child {
  margin-bottom: 0;
}

.section-label {
  display: block;
  font-size: 13px;
  color: rgba(var(--color-text-dark-rgb), 0.6);
  font-weight: 600;
  margin-bottom: 10px;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

/* === 檔案資訊 === */
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
  color: rgba(var(--color-text-dark-rgb), 0.6);
  font-weight: 500;
}

.file-info .value {
  color: rgba(var(--color-text-dark-rgb), 0.95);
  font-weight: 600;
}

.file-note {
  margin-top: 12px;
  padding-top: 12px;
  border-top: 1px solid rgba(var(--color-divider-rgb), 0.2);
  font-size: 11px;
  line-height: 1.5;
  color: var(--main-text-light);
  font-style: italic;
}

/* === 任務類型卡片 === */
.task-type-cards {
  display: flex;
  gap: 12px;
}

.type-card {
  position: relative;
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  text-align: center;
  gap: 8px;
  padding: 18px 14px;
  border: 2px solid rgba(var(--color-primary-rgb), 0.2);
  border-radius: 14px;
  background: var(--color-bg-light);
  cursor: pointer;
  transition: border-color 0.2s, box-shadow 0.2s, transform 0.2s;
}

.type-card:hover {
  border-color: rgba(var(--color-primary-rgb), 0.45);
  transform: translateY(-1px);
}

.type-card.selected {
  border-color: var(--color-primary);
  box-shadow: 0 0 0 3px rgba(var(--color-primary-rgb), 0.12);
}

/* 真正的 radio 隱藏，保留鍵盤 / 無障礙 */
.type-card-input {
  position: absolute;
  opacity: 0;
  width: 0;
  height: 0;
}

.type-card-input:focus-visible + .type-card-icon {
  outline: 2px solid var(--color-primary);
  outline-offset: 4px;
  border-radius: 8px;
}

.type-card-icon {
  color: rgba(var(--color-text-dark-rgb), 0.55);
  transition: color 0.2s;
}

.type-card.selected .type-card-icon {
  color: var(--color-primary);
}

.type-card-title {
  font-size: 15px;
  font-weight: 600;
  color: rgba(var(--color-text-dark-rgb), 0.9);
}

.type-card-desc {
  font-size: 12px;
  line-height: 1.4;
  color: rgba(var(--color-text-dark-rgb), 0.6);
}

.type-card-check {
  position: absolute;
  top: 8px;
  right: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
  width: 22px;
  height: 22px;
  border-radius: 50%;
  background: var(--color-primary);
  color: var(--color-white);
  opacity: 0;
  transform: scale(0.6);
  transition: opacity 0.2s, transform 0.2s;
}

.type-card.selected .type-card-check {
  opacity: 1;
  transform: scale(1);
}

/* === Toggle 開關（沿用） === */
.toggle-label {
  display: flex;
  align-items: center;
  gap: 10px;
  cursor: pointer;
  user-select: none;
  padding-right: 5px;
  position: relative;
}

.toggle-switch-wrapper {
  position: relative;
  width: 44px;
  height: 24px;
  display: inline-block;
}

.toggle-input {
  opacity: 0;
  width: 0;
  height: 0;
  position: absolute;
}

.toggle-slider {
  position: absolute;
  cursor: pointer;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background-color: var(--color-gray-100);
  transition: transform 0.3s ease, box-shadow 0.3s ease, background 0.3s ease;
  border-radius: 24px;
  box-shadow: inset 0 1px 3px var(--color-overlay-light);
  display: flex;
  align-items: center;
  justify-content: center;
}

.toggle-slider:before {
  position: absolute;
  content: "";
  height: 18px;
  width: 18px;
  left: 3px;
  bottom: 3px;
  background-color: var(--color-white);
  transition: 0.3s;
  border-radius: 50%;
  box-shadow: 0 2px 4px rgba(var(--color-text-dark-rgb), 0.2);
}

.toggle-input:checked + .toggle-slider {
  background: linear-gradient(135deg, var(--color-primary) 0%, var(--color-primary-dark) 100%);
  box-shadow: inset 0 1px 3px rgba(var(--color-text-dark-rgb), 0.1), 0 0 8px rgba(var(--color-primary-rgb), 0.3);
}

.toggle-input:checked + .toggle-slider:before {
  transform: translateX(20px);
}

.toggle-label:hover .toggle-slider {
  transform: scale(1.05);
  box-shadow: inset 0 1px 3px rgba(var(--color-text-dark-rgb), 0.2), 0 0 4px rgba(var(--color-text-dark-rgb), 0.1);
}

.toggle-label:hover .toggle-input:checked + .toggle-slider {
  box-shadow: inset 0 1px 3px rgba(var(--color-text-dark-rgb), 0.1), 0 0 12px rgba(var(--color-primary-rgb), 0.4);
}

.toggle-text {
  font-size: 14px;
  color: var(--main-text);
  font-weight: 500;
}

/* === 子設定 / 數字輸入 === */
.sub-setting {
  margin-top: 14px;
  padding-left: 28px;
}

.sub-label {
  display: block;
  font-size: 13px;
  color: rgba(var(--color-text-dark-rgb), 0.8);
  font-weight: 500;
  margin-bottom: 8px;
}

.sub-label .hint {
  display: block;
  font-size: 12px;
  color: rgba(var(--color-text-dark-rgb), 0.6);
  font-weight: 400;
  margin-top: 4px;
}

.number-input {
  width: 120px;
  padding: 10px 12px;
  font-size: 14px;
  border: 2px solid rgba(var(--color-primary-rgb), 0.3);
  border-radius: 8px;
  background: var(--color-bg-light);
  color: var(--color-text-dark);
  transition: all 0.3s;
}

.number-input:focus {
  outline: none;
  border-color: var(--color-primary);
  box-shadow: 0 0 0 3px rgba(var(--color-primary-rgb), 0.1);
}

.number-input::placeholder {
  color: rgba(var(--color-text-dark-rgb), 0.4);
}

/* === 語言選擇 === */
.language-select {
  width: 100%;
  padding: 10px 12px;
  font-size: 14px;
  border: 2px solid rgba(var(--color-primary-rgb), 0.3);
  border-radius: 8px;
  background: var(--color-bg-light);
  color: var(--color-text-dark);
  cursor: pointer;
  transition: all 0.3s;
}

.language-select:focus {
  outline: none;
  border-color: var(--color-primary);
  box-shadow: 0 0 0 3px rgba(var(--color-primary-rgb), 0.1);
}

/* === 標籤 === */
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
  border: 2px solid rgba(var(--color-primary-rgb), 0.3);
  border-radius: 8px;
  background: var(--color-bg-light);
  color: var(--color-text-dark);
  transition: all 0.3s;
}

.tag-input-wrapper .text-input:focus {
  outline: none;
  border-color: var(--color-primary);
  box-shadow: 0 0 0 3px rgba(var(--color-primary-rgb), 0.1);
}

.btn-add-tag {
  padding: 10px 20px;
  font-size: 14px;
  font-weight: 500;
  color: white;
  background: var(--color-teal);
  border: none;
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.3s;
  white-space: nowrap;
}

.btn-add-tag:hover:not(:disabled) {
  background: var(--color-teal-dark);
  transform: translateY(-1px);
  box-shadow: 0 4px 12px rgba(var(--color-teal-rgb), 0.3);
}

.btn-add-tag:disabled {
  background: color-mix(in srgb, var(--color-teal) 40%, transparent);
  cursor: not-allowed;
}

.quick-tags-section {
  margin-bottom: 12px;
  padding: 10px;
  background: rgba(var(--color-teal-rgb), 0.05);
  border-radius: 8px;
  border: 1px dashed rgba(var(--color-teal-rgb), 0.2);
}

.quick-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 8px;
  transition: max-height 0.25s ease;
}

.quick-tag-btn {
  padding: 5px 12px;
  font-size: 12px;
  font-weight: 500;
  color: var(--color-teal);
  background: var(--color-white);
  border: 1.5px solid rgba(var(--color-teal-rgb), 0.3);
  border-radius: 10px;
  cursor: pointer;
  transition: all 0.2s;
}

.quick-tag-btn:hover {
  background: rgba(var(--color-teal-rgb), 0.1);
  border-color: var(--color-teal);
  transform: translateY(-1px);
  box-shadow: 0 2px 6px rgba(var(--color-teal-rgb), 0.15);
}

.quick-tag-btn:active {
  transform: translateY(0);
}

.btn-toggle-quick-tags {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  margin-top: 8px;
  padding: 3px 10px;
  font-size: 12px;
  font-weight: 500;
  color: rgba(var(--color-teal-rgb), 0.95);
  background: transparent;
  border: 1px dashed rgba(var(--color-teal-rgb), 0.4);
  border-radius: 6px;
  cursor: pointer;
  transition: all 0.2s;
}

.btn-toggle-quick-tags:hover {
  background: rgba(var(--color-teal-rgb), 0.1);
  border-color: rgba(var(--color-teal-rgb), 0.6);
}

.btn-toggle-quick-tags svg {
  transition: transform 0.2s;
}

.btn-toggle-quick-tags.expanded svg {
  transform: rotate(180deg);
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
  background: color-mix(in srgb, var(--color-purple) 15%, transparent);
  border: 1px solid color-mix(in srgb, var(--color-purple) 30%, transparent);
  border-radius: 12px;
  font-size: 13px;
  font-weight: 500;
  color: var(--color-purple);
  transition: all 0.2s;
}

.selected-tag:hover {
  background: color-mix(in srgb, var(--color-purple) 20%, transparent);
  border-color: color-mix(in srgb, var(--color-purple) 40%, transparent);
}

.remove-tag {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 18px;
  height: 18px;
  padding: 0;
  margin: 0;
  background: color-mix(in srgb, var(--color-purple) 20%, transparent);
  border: none;
  border-radius: 50%;
  color: var(--color-purple);
  font-size: 16px;
  line-height: 1;
  cursor: pointer;
  transition: all 0.2s;
}

.remove-tag:hover {
  background: color-mix(in srgb, var(--color-danger) 20%, transparent);
  color: var(--color-danger);
}

/* === 合併模式檔案清單 === */
.merge-info-header {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 12px;
}

.merge-badge {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 4px 10px;
  background: rgba(var(--color-primary-rgb), 0.15);
  color: var(--color-primary);
  border-radius: 12px;
  font-size: 12px;
  font-weight: 600;
}

.file-count {
  font-size: 13px;
  color: rgba(var(--color-text-dark-rgb), 0.7);
  font-weight: 500;
}

.merge-file-list {
  list-style: none;
  padding: 0;
  margin: 0 0 16px 0;
  max-height: 120px;
  overflow-y: auto;
}

.merge-file-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 0;
  font-size: 13px;
  border-bottom: 1px solid rgba(var(--color-primary-rgb), 0.1);
}

.merge-file-item:last-child {
  border-bottom: none;
}

.merge-file-item .file-number {
  color: var(--color-primary);
  font-weight: 600;
  min-width: 20px;
}

.merge-file-item .file-name {
  flex: 1;
  color: rgba(var(--color-text-dark-rgb), 0.9);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.merge-file-item .file-size {
  color: rgba(var(--color-text-dark-rgb), 0.5);
  font-size: 12px;
}

.task-name-section {
  margin-top: 12px;
  padding-top: 12px;
  border-top: 1px solid rgba(var(--color-primary-rgb), 0.15);
}

.task-name-input {
  width: 100%;
  max-width: 100%;
  padding: 10px 12px;
  font-size: 14px;
  border: 2px solid rgba(var(--color-primary-rgb), 0.3);
  border-radius: 8px;
  background: var(--color-bg-light);
  color: var(--color-text-dark);
  transition: all 0.3s;
  margin-top: 6px;
}

.task-name-input:focus {
  outline: none;
  border-color: var(--color-primary);
  box-shadow: 0 0 0 3px rgba(var(--color-primary-rgb), 0.1);
}

.task-name-input::placeholder {
  color: rgba(var(--color-text-dark-rgb), 0.4);
}

.task-name-section .hint {
  margin-top: 6px;
  font-size: 11px;
  color: rgba(var(--color-text-dark-rgb), 0.5);
}

/* === Footer 按鈕 === */
.btn {
  padding: 10px 24px;
  font-size: 14px;
  font-weight: 600;
  border: none;
  border-radius: 10px;
  cursor: pointer;
  transition: all 0.2s;
}

.btn:disabled {
  opacity: 0.7;
  cursor: not-allowed;
}

.btn-cancel {
  background: transparent;
  color: rgba(var(--color-text-dark-rgb), 0.6);
  border: 1px solid rgba(var(--color-text-dark-rgb), 0.2);
}

.btn-cancel:hover:not(:disabled) {
  background: rgba(var(--color-text-dark-rgb), 0.05);
  border-color: rgba(var(--color-text-dark-rgb), 0.3);
}

.btn-primary {
  background: var(--color-primary);
  color: var(--color-white);
}

.btn-primary:hover:not(:disabled) {
  background: var(--color-primary-darker);
  transform: translateY(-1px);
  box-shadow: 0 4px 12px rgba(var(--color-primary-rgb), 0.3);
}

.btn-start {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
}

/* === 響應式 === */
@media (max-width: 600px) {
  .modal-container {
    width: 95%;
    max-height: 90vh;
  }

  .modal-header,
  .modal-body,
  .modal-footer {
    padding-left: 16px;
    padding-right: 16px;
  }

  /* 任務類型卡片：手機改上下堆疊 */
  .task-type-cards {
    flex-direction: column;
  }

  .file-info {
    flex-direction: column;
    align-items: flex-start;
    gap: 4px;
  }

  .tag-input-wrapper {
    flex-direction: column;
  }

  .tag-input-wrapper .text-input,
  .btn-add-tag {
    width: 100%;
    min-height: 44px;
    font-size: 16px; /* 防止 iOS 縮放 */
  }

  .number-input {
    width: 100%;
    min-height: 44px;
    font-size: 16px;
  }

  .modal-footer {
    flex-direction: column-reverse;
  }

  .modal-footer .btn {
    width: 100%;
    min-height: 48px;
  }
}
</style>
