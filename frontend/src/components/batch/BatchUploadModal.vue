<template>
  <Teleport to="body">
    <!-- 點遮罩不關閉（已選多檔，避免誤觸丟棄）；✕ / 取消 / Esc 才關 -->
    <div v-if="visible" class="modal-overlay">
      <div
        ref="modalContainerRef"
        class="modal-container"
        role="dialog"
        aria-modal="true"
        :aria-label="$t('batchUpload.title', { count: files.length })"
      >
        <!-- 標題列（sticky） -->
        <div class="modal-header">
          <h2>{{ $t('batchUpload.title', { count: files.length }) }}</h2>
          <button class="close-btn" @click="emitClose" :title="$t('batchUpload.close')" :aria-label="$t('batchUpload.close')">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <line x1="18" y1="6" x2="6" y2="18"></line>
              <line x1="6" y1="6" x2="18" y2="18"></line>
            </svg>
          </button>
        </div>

        <!-- 內容區（單欄、可捲動） -->
        <div class="modal-body">
          <!-- 1. 檔案清單（可展開逐檔覆蓋） -->
          <div class="modal-section">
            <div class="file-list">
              <div
                v-for="(file, index) in files"
                :key="file.id"
                class="file-item"
                :class="{ expanded: expandedIndex === index }"
              >
                <div class="file-main" @click="toggleExpand(index)">
                  <div class="file-icon">
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
                      <path d="M14,2H6A2,2 0 0,0 4,4V20A2,2 0 0,0 6,22H18A2,2 0 0,0 20,20V8L14,2M13,9V3.5L18.5,9H13Z" />
                    </svg>
                  </div>
                  <div class="file-info">
                    <TruncatedFilename :name="file.name" class="file-name" />
                    <span class="file-size">{{ formatFileSize(file.size) }}</span>
                  </div>
                  <div class="file-actions">
                    <button
                      class="btn-expand"
                      :class="{ active: expandedIndex === index }"
                      @click.stop="toggleExpand(index)"
                      :title="$t('batchUpload.expandSettings')"
                    >
                      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <polyline :points="expandedIndex === index ? '18 15 12 9 6 15' : '6 9 12 15 18 9'"></polyline>
                      </svg>
                    </button>
                    <button
                      class="btn-remove"
                      @click.stop="removeFile(index)"
                      :title="$t('batchUpload.removeFile')"
                    >
                      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <line x1="18" y1="6" x2="6" y2="18"></line>
                        <line x1="6" y1="6" x2="18" y2="18"></line>
                      </svg>
                    </button>
                  </div>
                </div>

                <!-- 展開的單檔覆蓋設定 -->
                <div v-if="expandedIndex === index" class="file-overrides">
                  <div class="override-field">
                    <label>{{ $t('batchUpload.customName') }}</label>
                    <input
                      type="text"
                      v-model="file.overrides.customName"
                      :placeholder="getDefaultName(file)"
                      class="text-input"
                    />
                  </div>
                  <div class="override-field">
                    <label>{{ $t('batchUpload.additionalTags') }}</label>
                    <div class="tag-input-row">
                      <input
                        type="text"
                        v-model="fileTagInput"
                        @keydown.enter.prevent="addFileTag(index)"
                        :placeholder="$t('batchUpload.tagPlaceholder')"
                        class="text-input"
                      />
                      <button class="btn-add-tag" @click="addFileTag(index)" :disabled="!fileTagInput.trim()">
                        {{ $t('batchUpload.add') }}
                      </button>
                    </div>
                    <div v-if="file.overrides.tags && file.overrides.tags.length > 0" class="override-tags">
                      <span
                        v-for="(tag, tagIndex) in file.overrides.tags"
                        :key="tagIndex"
                        class="tag-chip"
                      >
                        {{ tag }}
                        <button class="remove-tag" @click="removeFileTag(index, tagIndex)">×</button>
                      </span>
                    </div>
                  </div>
                </div>
              </div>
            </div>

            <!-- 檔案數量警告 -->
            <div v-if="files.length >= maxFiles" class="file-limit-warning">
              {{ $t('batchUpload.maxFilesReached', { max: maxFiles }) }}
            </div>

            <!-- 新增更多檔案（清單正下方） -->
            <button
              type="button"
              class="btn-add-files"
              @click="triggerAddFiles"
              :disabled="files.length >= maxFiles"
            >
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <line x1="12" y1="5" x2="12" y2="19"></line>
                <line x1="5" y1="12" x2="19" y2="12"></line>
              </svg>
              {{ $t('batchUpload.addMoreFiles') }}
            </button>
          </div>

          <!-- 2. 共用設定：任務類型 → 語言 → 說話者辨識 → 標籤 -->
          <div class="modal-section">
            <label class="section-label">{{ $t('batchUpload.commonSettings') }}</label>

            <!-- 任務類型（迷你預覽卡片） -->
            <div class="setting-block">
              <label class="setting-label">{{ $t('transcription.taskType') }}</label>
              <TaskTypeCards v-model="config.taskType" name="batchTaskType" />
            </div>

            <!-- 語言 -->
            <div class="setting-block">
              <label class="setting-label">{{ $t('transcription.language') }}</label>
              <select v-model="config.language" class="language-select">
                <option value="auto">{{ $t('transcription.autoDetect') }}</option>
                <option value="zh-TW">繁體中文</option>
                <option value="zh-CN">简体中文</option>
                <option value="zh">{{ $t('transcription.langChineseGeneric') }}</option>
                <option value="nan-TW">{{ $t('transcription.langTaiwanese') }}</option>
                <option value="en">English</option>
                <option value="ja">日本語</option>
                <option value="ko">한국어</option>
              </select>
            </div>

            <!-- 說話者辨識 -->
            <div class="setting-block">
              <label class="setting-label">{{ $t('transcription.speakerDiarization') }}</label>
              <div class="toggle-row">
                <label class="toggle-label">
                  <div class="toggle-switch-wrapper">
                    <input type="checkbox" v-model="config.diarize" class="toggle-input" />
                    <span class="toggle-slider"></span>
                  </div>
                  <span class="toggle-text">{{ $t('transcription.enable') }}</span>
                </label>

                <div v-if="config.diarize" class="speakers-input">
                  <label class="sub-label">{{ $t('transcription.maxSpeakers') }}</label>
                  <input
                    type="number"
                    v-model.number="config.maxSpeakers"
                    min="2"
                    max="10"
                    :placeholder="$t('transcription.autoDetect')"
                    class="number-input"
                  />
                </div>
              </div>
            </div>

            <!-- 統一標籤 -->
            <div class="setting-block">
              <label class="setting-label">{{ $t('transcription.tags') }}</label>
              <div class="tag-input-container">
                <div class="tag-input-row">
                  <input
                    type="text"
                    v-model="tagInput"
                    @keydown.enter.prevent="addTag"
                    :placeholder="$t('transcription.tagPlaceholder')"
                    class="text-input"
                  />
                  <button class="btn-add-tag" @click="addTag" :disabled="!tagInput.trim()">
                    {{ $t('batchUpload.add') }}
                  </button>
                </div>

                <!-- 快速標籤（限制兩排，超出可手動展開） -->
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

                <div v-if="config.tags.length > 0" class="selected-tags">
                  <span
                    v-for="(tag, index) in config.tags"
                    :key="index"
                    class="tag-chip"
                  >
                    {{ tag }}
                    <button class="remove-tag" @click="removeTag(index)">×</button>
                  </span>
                </div>
              </div>
            </div>
          </div>
        </div>

        <!-- 動作按鈕（sticky footer） -->
        <div class="modal-footer">
          <button class="btn btn-cancel" @click="emitClose">{{ $t('batchUpload.cancel') }}</button>
          <button
            class="btn btn-primary"
            @click="submitBatch"
            :disabled="files.length === 0 || submitting"
          >
            {{ $t('batchUpload.createTasks', { count: files.length }) }}
          </button>
        </div>

        <!-- 隱藏的檔案輸入 -->
        <input
          ref="additionalFileInput"
          type="file"
          accept="audio/*,video/*,.m4a,.mp3,.wav,.mp4"
          multiple
          @change="handleAdditionalFiles"
          style="display: none"
        />
      </div>
    </div>
  </Teleport>
</template>

<script setup>
import { ref, reactive, computed, toRef, watch, onUnmounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { useCollapsibleRows } from '../../composables/useCollapsibleRows'
import { useFocusTrap } from '../../composables/useFocusTrap'
import TruncatedFilename from '../common/TruncatedFilename.vue'
import TaskTypeCards from '../transcription/TaskTypeCards.vue'

const { t: $t, locale } = useI18n()

const props = defineProps({
  visible: { type: Boolean, default: false },
  initialFiles: { type: Array, required: true },
  existingTags: { type: Array, default: () => [] },
})

const emit = defineEmits(['close', 'submit'])

const modalContainerRef = ref(null)
useFocusTrap(modalContainerRef, toRef(props, 'visible'))

// Esc 關閉（useFocusTrap 刻意不處理 Esc）；batch 不在導覽範圍，恆可關
function onKeydown(e) {
  if (e.key === 'Escape') emitClose()
}
watch(() => props.visible, (open) => {
  if (open) document.addEventListener('keydown', onKeydown)
  else document.removeEventListener('keydown', onKeydown)
})
onUnmounted(() => document.removeEventListener('keydown', onKeydown))

function emitClose() { emit('close') }

const maxFiles = 10
const additionalFileInput = ref(null)
const expandedIndex = ref(null)
const tagInput = ref('')
const fileTagInput = ref('')
const submitting = ref(false)

// 將初始檔案轉換為帶有 ID 和覆蓋設定的物件
const files = ref(props.initialFiles.map((file, index) => ({
  id: `${Date.now()}-${index}`,
  file: file,
  name: file.name,
  size: file.size,
  overrides: {
    customName: '',
    tags: []
  }
})))

// 統一設定
const config = reactive({
  taskType: 'paragraph',
  diarize: true,
  maxSpeakers: null,
  language: 'auto',
  tags: []
})

// 可用的快速標籤（排除已選擇的）
const availableQuickTags = computed(() => {
  return props.existingTags.filter(tag => !config.tags.includes(tag))
})

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

// 格式化檔案大小
function formatFileSize(bytes) {
  if (bytes < 1024) return bytes + ' B'
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB'
  return (bytes / 1024 / 1024).toFixed(2) + ' MB'
}

// 獲取預設名稱（去掉副檔名）
function getDefaultName(file) {
  return file.name.replace(/\.[^/.]+$/, '')
}

// 展開/收合單檔設定
function toggleExpand(index) {
  if (expandedIndex.value === index) {
    expandedIndex.value = null
  } else {
    expandedIndex.value = index
    fileTagInput.value = ''
  }
}

// 移除檔案
function removeFile(index) {
  files.value.splice(index, 1)
  if (expandedIndex.value === index) {
    expandedIndex.value = null
  } else if (expandedIndex.value > index) {
    expandedIndex.value--
  }

  // 如果所有檔案都被移除，關閉跳窗
  if (files.value.length === 0) {
    emit('close')
  }
}

// 統一標籤管理
function addTag() {
  const tag = tagInput.value.trim()
  if (tag && !config.tags.includes(tag)) {
    config.tags.push(tag)
  }
  tagInput.value = ''
}

function addQuickTag(tag) {
  if (!config.tags.includes(tag)) {
    config.tags.push(tag)
  }
}

function removeTag(index) {
  config.tags.splice(index, 1)
}

// 單檔標籤管理
function addFileTag(fileIndex) {
  const tag = fileTagInput.value.trim()
  if (tag) {
    const file = files.value[fileIndex]
    if (!file.overrides.tags) {
      file.overrides.tags = []
    }
    if (!file.overrides.tags.includes(tag)) {
      file.overrides.tags.push(tag)
    }
    fileTagInput.value = ''
  }
}

function removeFileTag(fileIndex, tagIndex) {
  files.value[fileIndex].overrides.tags.splice(tagIndex, 1)
}

// 新增更多檔案
function triggerAddFiles() {
  additionalFileInput.value?.click()
}

function handleAdditionalFiles(event) {
  const newFiles = Array.from(event.target.files || [])
  const remainingSlots = maxFiles - files.value.length

  newFiles.slice(0, remainingSlots).forEach((file, index) => {
    files.value.push({
      id: `${Date.now()}-${files.value.length}-${index}`,
      file: file,
      name: file.name,
      size: file.size,
      overrides: {
        customName: '',
        tags: []
      }
    })
  })

  event.target.value = ''
}

// 提交批次（送出後由 parent 立刻關窗，進度交給全域上傳浮層）
async function submitBatch() {
  submitting.value = true

  try {
    const formData = new FormData()

    // 加入所有檔案
    files.value.forEach(fileObj => {
      formData.append('files', fileObj.file)
    })

    // 加入預設配置
    const defaultConfig = {
      taskType: config.taskType,
      diarize: config.diarize,
      maxSpeakers: config.maxSpeakers,
      language: config.language,
      tags: config.tags
    }
    formData.append('default_config', JSON.stringify(defaultConfig))
    formData.append('ui_language', locale.value)

    // 加入單檔覆蓋設定（僅有差異時）
    const overrides = {}
    files.value.forEach((fileObj, index) => {
      const hasOverride =
        fileObj.overrides.customName ||
        (fileObj.overrides.tags && fileObj.overrides.tags.length > 0)

      if (hasOverride) {
        overrides[index] = {}
        if (fileObj.overrides.customName) {
          overrides[index].customName = fileObj.overrides.customName
        }
        if (fileObj.overrides.tags && fileObj.overrides.tags.length > 0) {
          // 合併統一標籤和單檔額外標籤
          overrides[index].tags = [...config.tags, ...fileObj.overrides.tags]
        }
      }
    })
    formData.append('overrides', JSON.stringify(overrides))

    emit('submit', formData)
  } catch (error) {
    console.error('批次提交失敗:', error)
    submitting.value = false
  }
}

// 監聽初始檔案變化
watch(() => props.initialFiles, (newFiles) => {
  if (newFiles && newFiles.length > 0) {
    files.value = newFiles.map((file, index) => ({
      id: `${Date.now()}-${index}`,
      file: file,
      name: file.name,
      size: file.size,
      overrides: {
        customName: '',
        tags: []
      }
    }))
  }
}, { deep: true })
</script>

<style scoped>
/* === 跳窗框架（沿用 TaskSettingsModal / MergeModal 規範） === */
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
  max-width: 640px;
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

.modal-body {
  padding: 20px 24px;
  overflow-y: auto;
  flex: 1;
}

.modal-footer {
  display: flex;
  justify-content: flex-end;
  align-items: center;
  gap: 12px;
  padding: 16px 24px;
  border-top: 1px solid rgba(var(--color-divider-rgb), 0.3);
  flex-shrink: 0;
}

/* === Section === */
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

/* === 檔案列表 === */
.file-list {
  max-height: 260px;
  overflow-y: auto;
}

.file-item {
  background: rgba(var(--color-primary-rgb), 0.05);
  border-radius: 12px;
  margin-bottom: 8px;
  overflow: hidden;
  transition: all 0.2s;
}

.file-item:last-child {
  margin-bottom: 0;
}

.file-item.expanded {
  background: rgba(var(--color-primary-rgb), 0.1);
}

.file-main {
  display: flex;
  align-items: center;
  padding: 12px 16px;
  cursor: pointer;
  gap: 12px;
}

.file-main:hover {
  background: rgba(var(--color-primary-rgb), 0.08);
}

.file-icon {
  color: var(--color-primary);
  flex-shrink: 0;
}

.file-info {
  flex: 1;
  min-width: 0;
  display: flex;
  align-items: center;
  gap: 12px;
}

.file-name {
  font-size: 14px;
  font-weight: 500;
  color: var(--main-text);
}

.file-size {
  font-size: 12px;
  color: rgba(var(--color-text-dark-rgb), 0.5);
  flex-shrink: 0;
}

.file-actions {
  display: flex;
  align-items: center;
  gap: 4px;
  flex-shrink: 0;
}

.btn-expand,
.btn-remove {
  background: none;
  border: none;
  padding: 6px;
  cursor: pointer;
  color: rgba(var(--color-text-dark-rgb), 0.5);
  border-radius: 6px;
  transition: all 0.2s;
}

.btn-expand:hover,
.btn-remove:hover {
  background: rgba(var(--color-text-dark-rgb), 0.1);
  color: var(--main-text);
}

.btn-expand.active {
  color: var(--color-primary);
}

.btn-remove:hover {
  color: var(--color-danger);
}

/* 單檔覆蓋設定 */
.file-overrides {
  padding: 0 16px 16px;
  border-top: 1px dashed rgba(var(--color-divider-rgb), 0.3);
  animation: slideDownInner 0.2s ease;
}

@keyframes slideDownInner {
  from { opacity: 0; transform: translateY(-8px); }
  to { opacity: 1; transform: translateY(0); }
}

.override-field {
  margin-top: 12px;
}

.override-field label {
  display: block;
  font-size: 12px;
  font-weight: 500;
  color: rgba(var(--color-text-dark-rgb), 0.7);
  margin-bottom: 6px;
}

.override-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 8px;
}

.file-limit-warning {
  margin-top: 12px;
  padding: 10px 12px;
  background: rgba(var(--color-warning-rgb), 0.1);
  border: 1px solid rgba(var(--color-warning-rgb), 0.3);
  border-radius: 8px;
  font-size: 13px;
  color: var(--color-warning-dark);
}

/* 新增更多檔案 */
.btn-add-files {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  margin-top: 12px;
  padding: 8px 14px;
  font-size: 13px;
  font-weight: 500;
  color: var(--color-primary);
  background: transparent;
  border: 1.5px dashed rgba(var(--color-primary-rgb), 0.4);
  border-radius: 10px;
  cursor: pointer;
  transition: all 0.2s;
}

.btn-add-files:hover:not(:disabled) {
  background: rgba(var(--color-primary-rgb), 0.08);
  border-color: var(--color-primary);
}

.btn-add-files:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

/* === 共用設定 === */
.setting-block {
  margin-bottom: 18px;
}

.setting-block:last-child {
  margin-bottom: 0;
}

.setting-label {
  display: block;
  font-size: 13px;
  font-weight: 500;
  color: var(--main-text);
  margin-bottom: 8px;
}

/* 任務類型卡片樣式已抽至 TaskTypeCards.vue */

/* === Toggle 開關 === */
.toggle-row {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 16px;
}

.toggle-label {
  display: flex;
  align-items: center;
  gap: 10px;
  cursor: pointer;
}

.toggle-switch-wrapper {
  position: relative;
  width: 44px;
  height: 24px;
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
  transition: all 0.3s ease;
  border-radius: 24px;
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
}

.toggle-input:checked + .toggle-slider:before {
  transform: translateX(20px);
}

.toggle-text {
  font-size: 14px;
  color: var(--main-text);
}

.speakers-input {
  display: flex;
  align-items: center;
  gap: 8px;
}

.sub-label {
  font-size: 13px;
  color: rgba(var(--color-text-dark-rgb), 0.7);
}

.number-input {
  width: 100px;
  padding: 8px 10px;
  font-size: 14px;
  border: 2px solid rgba(var(--color-primary-rgb), 0.3);
  border-radius: 8px;
  background: var(--color-bg-light);
  color: var(--color-text-dark);
}

.number-input:focus {
  outline: none;
  border-color: var(--color-primary);
}

/* === 語言 === */
.language-select {
  width: 100%;
  padding: 10px 12px;
  font-size: 14px;
  border: 2px solid rgba(var(--color-primary-rgb), 0.3);
  border-radius: 8px;
  background: var(--color-bg-light);
  color: var(--color-text-dark);
  cursor: pointer;
}

.language-select:focus {
  outline: none;
  border-color: var(--color-primary);
}

/* === 標籤 === */
.tag-input-container {
  margin-top: 4px;
}

.tag-input-row {
  display: flex;
  gap: 8px;
}

.text-input {
  flex: 1;
  padding: 10px 12px;
  font-size: 14px;
  border: 2px solid rgba(var(--color-primary-rgb), 0.3);
  border-radius: 8px;
  background: var(--color-bg-light);
  color: var(--color-text-dark);
  transition: all 0.3s;
}

.text-input:focus {
  outline: none;
  border-color: var(--color-primary);
}

.btn-add-tag {
  padding: 10px 16px;
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
}

.btn-add-tag:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.quick-tags-section {
  margin-top: 10px;
  padding: 8px 10px;
  background: rgba(var(--color-teal-rgb), 0.05);
  border-radius: 8px;
  border: 1px dashed rgba(var(--color-teal-rgb), 0.2);
}

.quick-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  transition: max-height 0.25s ease;
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

.quick-tag-btn {
  padding: 5px 10px;
  font-size: 12px;
  font-weight: 500;
  color: var(--color-teal);
  background: var(--color-white);
  border: 1.5px solid rgba(var(--color-teal-rgb), 0.3);
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.2s;
}

.quick-tag-btn:hover {
  background: rgba(var(--color-teal-rgb), 0.1);
  border-color: var(--color-teal);
}

.selected-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 10px;
}

.tag-chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 6px 10px;
  background: color-mix(in srgb, var(--color-purple) 15%, transparent);
  border: 1px solid color-mix(in srgb, var(--color-purple) 30%, transparent);
  border-radius: 12px;
  font-size: 13px;
  font-weight: 500;
  color: var(--color-purple);
}

.remove-tag {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 16px;
  height: 16px;
  padding: 0;
  margin-left: 2px;
  background: none;
  border: none;
  border-radius: 50%;
  color: var(--color-purple);
  font-size: 14px;
  cursor: pointer;
  transition: all 0.2s;
}

.remove-tag:hover {
  background: color-mix(in srgb, var(--color-danger) 20%, transparent);
  color: var(--color-danger);
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
  opacity: 0.5;
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

  .file-info {
    flex-direction: column;
    align-items: flex-start;
    gap: 2px;
  }

  .toggle-row {
    flex-direction: column;
    align-items: flex-start;
  }

  .speakers-input {
    margin-top: 10px;
    width: 100%;
  }

  .speakers-input .number-input {
    flex: 1;
  }

  .tag-input-row {
    flex-direction: column;
  }

  .text-input,
  .btn-add-tag {
    min-height: 44px;
    font-size: 16px; /* 防止 iOS 縮放 */
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
