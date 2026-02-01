<template>
  <div class="batch-upload-panel">
    <!-- 標題列 -->
    <div class="panel-header">
      <h3>{{ $t('batchUpload.title', { count: files.length }) }}</h3>
      <button class="btn-close" @click="$emit('close')" :title="$t('batchUpload.close')">
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <line x1="18" y1="6" x2="6" y2="18"></line>
          <line x1="6" y1="6" x2="18" y2="18"></line>
        </svg>
      </button>
    </div>

    <!-- 檔案列表 -->
    <div class="file-list-section">
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
              <span class="file-name">{{ file.name }}</span>
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
    </div>

    <!-- 統一設定區 -->
    <div class="settings-section">
      <h4>{{ $t('batchUpload.commonSettings') }}</h4>

      <!-- 任務類型 -->
      <div class="setting-row">
        <label class="setting-label">{{ $t('transcription.taskType') }}</label>
        <div class="radio-group">
          <label class="radio-item">
            <input type="radio" name="taskType" value="paragraph" v-model="config.taskType" />
            <span class="radio-label">{{ $t('transcription.paragraph') }}</span>
          </label>
          <label class="radio-item">
            <input type="radio" name="taskType" value="subtitle" v-model="config.taskType" />
            <span class="radio-label">{{ $t('transcription.subtitle') }}</span>
          </label>
        </div>
      </div>

      <!-- 說話者辨識 -->
      <div class="setting-row">
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
      <div class="setting-row">
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

          <!-- 快速標籤 -->
          <div v-if="availableQuickTags.length > 0" class="quick-tags-section">
            <div class="quick-tags">
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

    <!-- 底部動作區 -->
    <div class="panel-actions">
      <button class="btn btn-secondary" @click="triggerAddFiles" :disabled="files.length >= maxFiles">
        {{ $t('batchUpload.addMoreFiles') }}
      </button>
      <button
        class="btn btn-primary"
        @click="submitBatch"
        :disabled="files.length === 0 || submitting"
      >
        <span v-if="submitting" class="spinner"></span>
        <span v-else>{{ $t('batchUpload.createTasks', { count: files.length }) }}</span>
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
</template>

<script setup>
import { ref, reactive, computed, watch } from 'vue'
import { useI18n } from 'vue-i18n'

const { t: $t } = useI18n()

const props = defineProps({
  initialFiles: {
    type: Array,
    required: true
  },
  existingTags: {
    type: Array,
    default: () => []
  }
})

const emit = defineEmits(['close', 'submit'])

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

  // 如果所有檔案都被移除，關閉面板
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

// 提交批次
async function submitBatch() {
  submitting.value = true

  try {
    // 準備提交資料
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

    // 加入單檔覆蓋設定
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
.batch-upload-panel {
  width: 100%;
  max-width: 800px;
  margin: 20px auto;
  background: var(--main-bg);
  border-radius: 20px;
  overflow: hidden;
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

/* 標題列 */
.panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px 20px;
  border-bottom: 1px solid rgba(var(--color-divider-rgb), 0.2);
}

.panel-header h3 {
  margin: 0;
  font-size: 16px;
  font-weight: 600;
  color: var(--main-text);
}

.btn-close {
  background: none;
  border: none;
  padding: 8px;
  cursor: pointer;
  color: rgba(var(--color-text-dark-rgb), 0.6);
  border-radius: 8px;
  transition: all 0.2s;
}

.btn-close:hover {
  background: rgba(var(--color-text-dark-rgb), 0.1);
  color: var(--main-text);
}

/* 檔案列表 */
.file-list-section {
  padding: 16px 20px;
  border-bottom: 1px solid rgba(var(--color-divider-rgb), 0.2);
}

.file-list {
  max-height: 240px;
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
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
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
  margin-top: 0;
  animation: slideDown 0.2s ease;
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

/* 統一設定區 */
.settings-section {
  padding: 16px 20px;
}

.settings-section h4 {
  margin: 0 0 16px 0;
  font-size: 13px;
  font-weight: 600;
  color: rgba(var(--color-text-dark-rgb), 0.6);
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.setting-row {
  margin-bottom: 16px;
}

.setting-row:last-child {
  margin-bottom: 0;
}

.setting-label {
  display: block;
  font-size: 13px;
  font-weight: 500;
  color: var(--main-text);
  margin-bottom: 8px;
}

/* Radio 群組 */
.radio-group {
  display: flex;
  gap: 16px;
}

.radio-item {
  display: flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
}

.radio-item input[type="radio"] {
  width: 18px;
  height: 18px;
  cursor: pointer;
  accent-color: var(--electric-primary);
}

.radio-label {
  font-size: 14px;
  color: var(--main-text);
}

/* Toggle 開關 */
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
  background: rgba(255, 255, 255, 0.9);
  color: var(--color-text-dark);
}

.number-input:focus {
  outline: none;
  border-color: var(--color-primary);
}

/* 標籤輸入 */
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
  background: rgba(255, 255, 255, 0.9);
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

/* 快速標籤 */
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

/* 已選標籤 */
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

/* 底部動作區 */
.panel-actions {
  display: flex;
  justify-content: flex-end;
  gap: 12px;
  padding: 16px 20px;
  border-top: 1px solid rgba(var(--color-divider-rgb), 0.2);
}

.btn {
  padding: 12px 24px;
  font-size: 14px;
  font-weight: 600;
  border: none;
  border-radius: 10px;
  cursor: pointer;
  transition: all 0.3s;
}

.btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.btn-secondary {
  background: rgba(var(--color-text-dark-rgb), 0.1);
  color: var(--main-text);
}

.btn-secondary:hover:not(:disabled) {
  background: rgba(var(--color-text-dark-rgb), 0.15);
}

.btn-primary {
  background: var(--main-bg);
  color: var(--main-primary);
  display: flex;
  align-items: center;
  gap: 8px;
}

.btn-primary:hover:not(:disabled) {
  color: var(--main-primary-dark);
}

.spinner {
  width: 16px;
  height: 16px;
  border: 2px solid transparent;
  border-top-color: currentColor;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

/* 響應式設計 */
@media (max-width: 600px) {
  .batch-upload-panel {
    margin: 12px;
    border-radius: 16px;
  }

  .panel-header,
  .file-list-section,
  .settings-section,
  .panel-actions {
    padding: 12px 16px;
  }

  .file-info {
    flex-direction: column;
    align-items: flex-start;
    gap: 2px;
  }

  .radio-group {
    flex-direction: column;
    gap: 10px;
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

  .panel-actions {
    flex-direction: column;
  }

  .btn {
    width: 100%;
    justify-content: center;
  }
}
</style>
