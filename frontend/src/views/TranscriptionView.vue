<template>
  <div class="container">
    <!-- SVG 濾鏡定義 -->
    <ElectricBorder />

    <!-- 上傳區域 -->
    <UploadZone @file-selected="handleFileUpload" :uploading="uploading" :disabled="!!pendingFile" />

    <!-- 確認表單（在上傳區下方） -->
    <div v-if="pendingFile" class="confirm-section electric-card">
        <div class="electric-inner">
          <div class="electric-border-outer">
            <div class="electric-main modal-body">
              <!-- 第一排：任務類型 + 檔案資訊 + 說話者辨識 + 標籤 -->
              <div class="confirm-row">
                <!-- 任務類型 -->
                <div class="modal-section task-type-section">
                  <label class="section-label">{{ $t('transcription.taskType') }}</label>

                  <div class="radio-group">
                    <label class="radio-item">
                      <input type="radio" name="taskType" value="paragraph" v-model="taskType" />
                      <span class="radio-label">{{ $t('transcription.paragraph') }}</span>
                    </label>
                    <label class="radio-item">
                      <input type="radio" name="taskType" value="subtitle" v-model="taskType" />
                      <span class="radio-label">{{ $t('transcription.subtitle') }}</span>
                    </label>
                  </div>

                  <div class="task-type-hint">
                    <span v-if="taskType === 'paragraph'" class="hint">{{ $t('transcription.paragraphHint') }}</span>
                    <span v-else class="hint">{{ $t('transcription.subtitleHint') }}</span>
                  </div>
                </div>

                <!-- 檔案資訊 -->
                <div class="modal-section file-section">
                  <label class="section-label">{{ $t('transcription.fileInfo') }}</label>
                  <div class="file-info">
                    <span class="label">{{ $t('transcription.fileName') }}</span>
                    <span class="value">{{ pendingFile?.name }}</span>
                  </div>
                  <div class="file-info" v-if="pendingFile">
                    <span class="label">{{ $t('transcription.fileSize') }}</span>
                    <span class="value">{{ (pendingFile.size / 1024 / 1024).toFixed(2) }} MB</span>
                  </div>
                  <div class="file-note">
                    {{ $t('transcription.audioRetentionNote') }}
                  </div>
                </div>

                <!-- 說話者辨識 -->
                <div class="modal-section diarize-section">
                  <label class="section-label">{{ $t('transcription.speakerDiarization') }}</label>

                  <label class="toggle-item">
                    <div class="toggle-wrapper">
                      <input type="checkbox" id="modal-diarize" v-model="enableDiarization" class="toggle-input" />
                      <span class="toggle-track">
                        <span class="toggle-thumb"></span>
                      </span>
                    </div>
                    <span class="toggle-label-text">{{ $t('transcription.enable') }}</span>
                  </label>

                  <div class="sub-setting" v-if="enableDiarization">
                    <label for="modal-maxSpeakers" class="sub-label">
                      {{ $t('transcription.maxSpeakers') }}
                      <span class="hint">{{ $t('transcription.maxSpeakersHint') }}</span>
                    </label>
                    <input
                      type="number"
                      id="modal-maxSpeakers"
                      v-model.number="maxSpeakers"
                      min="2"
                      max="10"
                      :placeholder="$t('transcription.autoDetect')"
                      class="number-input"
                    />
                  </div>
                </div>

                <!-- 標籤 -->
                <div class="modal-section tag-section">
                <label class="section-label">{{ $t('transcription.tags') }}</label>
                <div class="tag-input-container">
                  <div class="tag-input-wrapper">
                    <input
                      type="text"
                      v-model="tagInput"
                      @keydown.enter.prevent="addTag"
                      @keydown.comma.prevent="addTag"
                      :placeholder="$t('transcription.tagPlaceholder')"
                      class="text-input"
                    />
                    <button
                      type="button"
                      class="btn-add-tag"
                      @click="addTag"
                      :disabled="!tagInput.trim()"
                    >
                      {{ $t('transcription.add') }}
                    </button>
                  </div>

                  <!-- 快速選擇現有標籤 -->
                  <div v-if="availableQuickTags.length > 0" class="quick-tags-section">
                    <div class="quick-tags">
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
                  </div>

                  <div v-if="selectedTags.length > 0" class="selected-tags">
                    <span
                      v-for="(tag, index) in selectedTags"
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

              <!-- 動作按鈕 -->
              <div class="modal-actions">
                <button class="btn btn-primary btn-start" @click="confirmAndUpload">{{ $t('transcription.startTranscription') }}</button>
                <button class="btn btn-secondary btn-cancel" @click="cancelUpload">{{ $t('transcription.cancel') }}</button>
              </div>
            </div>
          </div>
          <div class="electric-glow-1"></div>
          <div class="electric-glow-2"></div>
        </div>
        <div class="electric-overlay"></div>
        <div class="electric-bg-glow"></div>
    </div>

  </div>

</template>

<script setup>
import { ref, computed, onMounted, onUnmounted, inject } from 'vue'
import { useI18n } from 'vue-i18n'
import ElectricBorder from '../components/shared/ElectricBorder.vue'
import UploadZone from '../components/UploadZone.vue'

// 新 API 服務層
import { transcriptionService, taskService } from '../api/services'

const { t: $t } = useI18n()

const showNotification = inject('showNotification')
const uploading = ref(false)
const taskType = ref('paragraph')  // 任務類型：paragraph（段落）或 subtitle（字幕）
const enableDiarization = ref(true)
const maxSpeakers = ref(null)
const pendingFile = ref(null)
const selectedTags = ref([])
const tagInput = ref('')
const tasks = ref([])  // 任務列表，用於顯示快速標籤

// 獲取所有唯一標籤
const allTags = computed(() => {
  const tags = new Set()
  tasks.value.forEach(task => {
    if (task.tags && task.tags.length > 0) {
      task.tags.forEach(tag => tags.add(tag))
    }
  })
  return Array.from(tags).sort()
})

// 可用的快速標籤（排除已選擇的）
const availableQuickTags = computed(() => {
  return allTags.value.filter(tag => !selectedTags.value.includes(tag))
})

// 選擇檔案後顯示確認表單
function handleFileUpload(file) {
  pendingFile.value = file
}

// 標籤管理
function addTag() {
  const tag = tagInput.value.trim()
  if (tag && !selectedTags.value.includes(tag)) {
    selectedTags.value.push(tag)
    tagInput.value = ''
  } else if (selectedTags.value.includes(tag)) {
    tagInput.value = ''
  }
}

function addQuickTag(tag) {
  if (!selectedTags.value.includes(tag)) {
    selectedTags.value.push(tag)
  }
}

function removeTag(index) {
  selectedTags.value.splice(index, 1)
}

// 載入任務列表
async function refreshTasks() {
  try {
    const response = await taskService.list({ limit: 20 })
    tasks.value = response.tasks || response || []
  } catch (error) {
    console.error($t('transcription.errorLoadTasks') + ':', error)
  }
}

// 確認後開始上傳
async function confirmAndUpload() {
  if (!pendingFile.value) return

  uploading.value = true

  const formData = new FormData()
  formData.append('file', pendingFile.value)
  formData.append('task_type', taskType.value)
  formData.append('punct_provider', 'gemini')
  formData.append('chunk_audio', 'true')
  formData.append('language', 'auto')  // 使用 Whisper 自動偵測語言
  formData.append('diarize', enableDiarization.value ? 'true' : 'false')
  if (enableDiarization.value && maxSpeakers.value) {
    formData.append('max_speakers', maxSpeakers.value.toString())
  }
  if (selectedTags.value.length > 0) {
    formData.append('tags', JSON.stringify(selectedTags.value))
  }

  try {
    // 使用新 API 服務層
    const responseData = await transcriptionService.create(formData)

    const newTask = {
      ...responseData,
      file: pendingFile.value.name,
      uploadedAt: new Date().toLocaleString('zh-TW')
    }

    tasks.value.unshift(newTask)

    // 顯示轉錄中通知
    if (showNotification) {
      showNotification({
        title: $t('transcription.transcribing'),
        message: `正在轉錄「${pendingFile.value.name}」`,
        type: 'processing',
        duration: 5000  // 5秒後自動關閉
      })
    }
  } catch (error) {
    console.error($t('transcription.errorUpload') + ':', error)
    if (showNotification) {
      showNotification({
        title: $t('transcription.uploadFailed'),
        message: error.response?.data?.detail || error.message,
        type: 'error',
        duration: 5000
      })
    } else {
      alert($t('transcription.uploadFailedMessage', { message: error.response?.data?.detail || error.message }))
    }
  } finally {
    uploading.value = false
    pendingFile.value = null
    taskType.value = 'paragraph'  // 重置為預設值
    selectedTags.value = []
    tagInput.value = ''
  }
}

// 取消上傳
function cancelUpload() {
  pendingFile.value = null
  taskType.value = 'paragraph'  // 重置為預設值
  selectedTags.value = []
  tagInput.value = ''
}



// 改進的 timecode 匹配：結合位置和內容匹配
// 生命週期
onMounted(() => {
  refreshTasks()
  // 限制視窗高度
  document.body.classList.add('upload-page')
})

onUnmounted(() => {
  // 清理：移除視窗高度限制
  document.body.classList.remove('upload-page')
})
</script>

<style scoped>
.container {
  animation: fadeIn 0.5s ease-in;
}

@keyframes fadeIn {
  from {
    opacity: 0;
    transform: translateY(20px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

/* 確認表單區域（在上傳區下方） */
.confirm-section {
  width: 100%;
  max-width: 800px;
  margin: 20px auto 0;
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

.modal-body {
  padding: 20px;
  overflow-y: auto;
  /* max-height 由 flex 布局自動處理，移除以避免衝突 */
}

/* 確認區響應式排版 */
.confirm-row {
  display: grid;
  grid-template-columns: 1fr 1fr 1fr 1fr;
  gap: 20px;
  margin-bottom: 20px;
}

/* 平板版：兩欄 */
@media (max-width: 1024px) {
  .confirm-row {
    grid-template-columns: 1fr 1fr;
  }
}

/* 移動版：垂直排列 */
@media (max-width: 768px) {
  .confirm-row {
    grid-template-columns: 1fr;
    gap: 0;
  }

  .confirm-row .modal-section {
    margin-bottom: 20px;
  }
}

.modal-section {
  margin-bottom: 20px;
  padding-bottom: 16px;
  border-bottom: 1px solid rgba(221, 132, 72, 0.15);
}

.modal-section:last-of-type {
  border-bottom: none;
  padding-bottom: 0;
}

/* 確認區的 section 不需要底部邊框 */
.confirm-row .modal-section {
  border-bottom: none;
  padding-bottom: 0;
}

.section-label {
  display: block;
  font-size: 13px;
  color: rgba(45, 45, 45, 0.6);
  font-weight: 600;
  margin-bottom: 10px;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

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
  color: rgba(45, 45, 45, 0.6);
  font-weight: 500;
}

.file-info .value {
  color: rgba(45, 45, 45, 0.95);
  font-weight: 600;
}

.file-note {
  margin-top: 12px;
  padding-top: 12px;
  border-top: 1px solid rgba(163, 177, 198, 0.2);
  font-size: 11px;
  line-height: 1.5;
  color: var(--neu-text-light);
  font-style: italic;
}

/* Neumorphism Toggle 開關 */
.toggle-item {
  display: flex;
  align-items: center;
  gap: 12px;
  cursor: pointer;
  user-select: none;
}

.toggle-wrapper {
  position: relative;
  width: 40px;
  height: 22px;
}

.toggle-input {
  opacity: 0;
  width: 0;
  height: 0;
  position: absolute;
}

.toggle-track {
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: var(--neu-bg);
  border-radius: 11px;
  transition: all 0.3s ease;
  box-shadow: var(--neu-shadow-inset);
}

.toggle-thumb {
  position: absolute;
  top: 3px;
  left: 3px;
  width: 16px;
  height: 16px;
  background: var(--neu-bg);
  border-radius: 50%;
  transition: all 0.3s ease;
  box-shadow: var(--neu-shadow-btn-sm);
}

.toggle-input:checked + .toggle-track {
  background: linear-gradient(145deg, #c8e6c9, #a5d6a7);
}

.toggle-input:checked + .toggle-track .toggle-thumb {
  transform: translateX(18px);
  box-shadow: var(--neu-shadow-btn-hover-sm);
}

.toggle-item:hover .toggle-track {
  box-shadow: var(--neu-shadow-inset-hover);
}

.toggle-item:hover .toggle-input:checked + .toggle-track {
  background: linear-gradient(145deg, #b8d6b9, #95c697);
}

.toggle-label-text {
  font-size: 14px;
  color: var(--neu-text);
  font-weight: 500;
}

/* Radio 群組 */
.radio-group {
  display: flex;
  gap: 16px;
  margin-bottom: 10px;
}

.radio-item {
  display: flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
  user-select: none;
}

.radio-item input[type="radio"] {
  width: 18px;
  height: 18px;
  cursor: pointer;
  accent-color: var(--electric-primary);
}

.radio-label {
  font-size: 14px;
  color: var(--neu-text);
  font-weight: 500;
}

.task-type-hint {
  margin-top: 8px;
}

.task-type-hint .hint {
  font-size: 12px;
  color: rgba(45, 45, 45, 0.6);
  font-weight: 400;
  line-height: 1.4;
}

.sub-setting {
  margin-top: 14px;
  padding-left: 28px;
  animation: slideDown 0.2s ease;
}

.sub-label {
  display: block;
  font-size: 13px;
  color: rgba(45, 45, 45, 0.8);
  font-weight: 500;
  margin-bottom: 8px;
}

.sub-label .hint {
  display: block;
  font-size: 12px;
  color: rgba(45, 45, 45, 0.6);
  font-weight: 400;
  margin-top: 4px;
}

.number-input {
  width: 100%;
  padding: 10px 12px;
  font-size: 14px;
  border: 2px solid rgba(221, 132, 72, 0.3);
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.9);
  color: #2d2d2d;
  transition: all 0.3s;
}

.number-input:focus {
  outline: none;
  border-color: var(--electric-primary);
  box-shadow: 0 0 0 3px rgba(221, 132, 72, 0.1);
}

.number-input::placeholder {
  color: rgba(45, 45, 45, 0.4);
}

/* 標籤輸入樣式 */
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
  border: 2px solid rgba(221, 132, 72, 0.3);
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.9);
  color: #2d2d2d;
  transition: all 0.3s;
}

.tag-input-wrapper .text-input:focus {
  outline: none;
  border-color: var(--electric-primary);
  box-shadow: 0 0 0 3px rgba(221, 132, 72, 0.1);
}

.btn-add-tag {
  padding: 10px 20px;
  font-size: 14px;
  font-weight: 500;
  color: white;
  background: #77969A;
  border: none;
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.3s;
  white-space: nowrap;
}

.btn-add-tag:hover:not(:disabled) {
  background: #336774;
  transform: translateY(-1px);
  box-shadow: 0 4px 12px rgba(119, 150, 154, 0.3);
}

.btn-add-tag:disabled {
  background: rgba(119, 150, 154, 0.4);
  cursor: not-allowed;
}

/* 快速標籤選擇區 */
.quick-tags-section {
  margin-bottom: 12px;
  padding: 10px;
  background: rgba(119, 150, 154, 0.05);
  border-radius: 8px;
  border: 1px dashed rgba(119, 150, 154, 0.2);
}

.quick-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 8px;
}

.quick-tag-btn {
  padding: 5px 12px;
  font-size: 12px;
  font-weight: 500;
  color: #77969A;
  background: white;
  border: 1.5px solid rgba(119, 150, 154, 0.3);
  border-radius: 10px;
  cursor: pointer;
  transition: all 0.2s;
}

.quick-tag-btn:hover {
  background: rgba(119, 150, 154, 0.1);
  border-color: #77969A;
  transform: translateY(-1px);
  box-shadow: 0 2px 6px rgba(119, 150, 154, 0.15);
}

.quick-tag-btn:active {
  transform: translateY(0);
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
  background: rgba(102, 126, 234, 0.15);
  border: 1px solid rgba(102, 126, 234, 0.3);
  border-radius: 12px;
  font-size: 13px;
  font-weight: 500;
  color: #667eea;
  transition: all 0.2s;
}

.selected-tag:hover {
  background: rgba(102, 126, 234, 0.2);
  border-color: rgba(102, 126, 234, 0.4);
}

.remove-tag {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 18px;
  height: 18px;
  padding: 0;
  margin: 0;
  background: rgba(102, 126, 234, 0.2);
  border: none;
  border-radius: 50%;
  color: #667eea;
  font-size: 16px;
  line-height: 1;
  cursor: pointer;
  transition: all 0.2s;
}

.remove-tag:hover {
  background: rgba(239, 68, 68, 0.2);
  color: #ef4444;
}

.modal-actions {
  display: flex;
  gap: 12px;
  margin-top: 24px;
  justify-content: center;
  align-items: center;
}

.modal-actions .btn {
  padding: 12px 32px;
  font-size: 15px;
  font-weight: 600;
}

.modal-actions .btn-cancel {
  padding: 8px 20px;
  font-size: 13px;
}

/* 開始轉錄按鈕 - 使用者頭貼風格 */
.modal-actions .btn-start {
  background: var(--neu-bg);
  color: var(--neu-primary);
  box-shadow: var(--neu-shadow-btn);
}

.modal-actions .btn-start:hover {
  box-shadow: var(--neu-shadow-btn-hover);
  color: var(--neu-primary-dark);
}

.modal-actions .btn-start:active {
  box-shadow: var(--neu-shadow-btn-active);
}

</style>
