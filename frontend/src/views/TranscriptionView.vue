<template>
  <div class="container">
    <!-- SVG 濾鏡定義 -->
    <ElectricBorder />

    <!-- 上傳區域（含三角形合併按鈕） -->
    <UploadZone
      @file-selected="handleFileUpload"
      @open-merge="openMergeModal"
      :uploading="uploading"
      :disabled="!!pendingFile || mergeMode.isActive"
    />

    <!-- 合併對話窗 -->
    <MergeModal
      :visible="showMergeModal"
      @close="closeMergeModal"
      @confirm="handleMergeConfirm"
    />

    <!-- 確認表單（在上傳區下方） -->
    <div v-if="pendingFile || mergeMode.showForm" class="confirm-section">
      <div class="modal-body">
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

            <!-- 合併模式：顯示多檔案資訊 -->
            <template v-if="mergeMode.isActive">
              <div class="merge-info-header">
                <span class="merge-badge">🔀 合併模式</span>
                <span class="file-count">{{ mergeMode.files.length }} 個檔案</span>
              </div>
              <ul class="merge-file-list">
                <li v-for="(file, idx) in mergeMode.files" :key="idx" class="merge-file-item">
                  <span class="file-number">{{ idx + 1 }}.</span>
                  <span class="file-name">{{ file.name }}</span>
                  <span class="file-size">({{ formatFileSize(file.size) }})</span>
                </li>
              </ul>
              <!-- 任務名稱欄位 -->
              <div class="task-name-section">
                <label class="sub-label">任務名稱</label>
                <input
                  type="text"
                  v-model="mergeTaskName"
                  :placeholder="defaultMergeTaskName"
                  class="text-input task-name-input"
                />
                <p class="hint">此名稱將用於識別合併後的轉錄任務</p>
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

            <div class="file-note">
              {{ $t('transcription.audioRetentionNote') }}
            </div>
          </div>

          <!-- 說話者辨識 -->
          <div class="modal-section diarize-section">
            <label class="section-label">{{ $t('transcription.speakerDiarization') }}</label>

            <label class="toggle-label">
              <div class="toggle-switch-wrapper">
                <input type="checkbox" id="modal-diarize" v-model="enableDiarization" class="toggle-input" />
                <span class="toggle-slider"></span>
              </div>
              <span class="toggle-text">{{ $t('transcription.enable') }}</span>
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

  </div>

</template>

<script setup>
import { ref, reactive, computed, onMounted, onUnmounted, inject } from 'vue'
import { useI18n } from 'vue-i18n'
import ElectricBorder from '../components/shared/ElectricBorder.vue'
import UploadZone from '../components/UploadZone.vue'
import MergeModal from '../components/merge/MergeModal.vue'

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

// 合併模式狀態
const mergeMode = reactive({
  isActive: false,      // 是否處於合併模式
  showForm: false,      // 是否顯示轉錄設定表單
  files: []             // 待合併的檔案列表
})
const mergeTaskName = ref('')
const showMergeModal = ref(false)  // 合併對話窗顯示狀態

// 預設任務名稱（第一個檔案的檔名，去掉副檔名）
const defaultMergeTaskName = computed(() => {
  if (mergeMode.files.length > 0) {
    const firstName = mergeMode.files[0].name
    return firstName.replace(/\.[^/.]+$/, '')  // 去掉副檔名
  }
  return ''
})

// 格式化檔案大小
function formatFileSize(bytes) {
  return (bytes / 1024 / 1024).toFixed(2) + ' MB'
}

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
  }
  tagInput.value = ''
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
  // 判斷是合併模式還是單檔模式
  const isMergeMode = mergeMode.isActive && mergeMode.files.length > 0

  if (!isMergeMode && !pendingFile.value) return

  uploading.value = true

  const formData = new FormData()

  if (isMergeMode) {
    // 合併模式：添加所有檔案
    mergeMode.files.forEach((file) => {
      formData.append('files', file)
    })
    formData.append('merge_files', 'true')

    // 添加自訂任務名稱（如果有）
    const finalTaskName = mergeTaskName.value.trim() || defaultMergeTaskName.value
    if (finalTaskName) {
      formData.append('custom_name', finalTaskName)
    }
  } else {
    // 單檔模式
    formData.append('file', pendingFile.value)
  }

  // 共用的轉錄設定
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
      file: isMergeMode ? `合併 ${mergeMode.files.length} 個檔案` : pendingFile.value.name,
      uploadedAt: new Date().toLocaleString('zh-TW')
    }

    tasks.value.unshift(newTask)

    // 顯示轉錄中通知
    if (showNotification) {
      const message = isMergeMode
        ? `正在合併並轉錄 ${mergeMode.files.length} 個檔案`
        : `正在轉錄「${pendingFile.value.name}」`
      showNotification({
        title: $t('transcription.transcribing'),
        message: message,
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
    // 重置合併模式
    mergeMode.isActive = false
    mergeMode.showForm = false
    mergeMode.files = []
    mergeTaskName.value = ''
  }
}

// 取消上傳
function cancelUpload() {
  pendingFile.value = null
  taskType.value = 'paragraph'  // 重置為預設值
  selectedTags.value = []
  tagInput.value = ''
  // 也重置合併模式
  mergeMode.isActive = false
  mergeMode.showForm = false
  mergeMode.files = []
  mergeTaskName.value = ''
}

// 開啟合併對話窗
function openMergeModal() {
  showMergeModal.value = true
}

// 關閉合併對話窗
function closeMergeModal() {
  showMergeModal.value = false
}

// 處理合併對話窗確認（進入轉錄設定表單）
function handleMergeConfirm(files) {
  closeMergeModal()
  handleShowTranscriptionForm(files)
}

// 處理「進入轉錄設定」（合併模式）
function handleShowTranscriptionForm(files) {
  mergeMode.isActive = true
  mergeMode.showForm = true
  mergeMode.files = files
  mergeTaskName.value = ''  // 重置任務名稱
}




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
  --color-primary-rgb: 221, 132, 72;
  --electric-primary: #dd8448;
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
  padding: 0;
  border-radius: 20px;
  background: var(--neu-bg);
  box-shadow: var(--neu-shadow-raised);
  border: none;
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
  grid-template-columns: 1fr 1fr;
  gap: 20px;
  margin-bottom: 20px;
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
}

/* 確認區的 section 不需要底部邊框和額外 padding */
.confirm-row .modal-section {
  margin-bottom: 20px;
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

/* Toggle 開關 */
.toggle-label {
  display: flex;
  align-items: center;
  gap: 10px;
  cursor: pointer;
  user-select: none;
  padding-right: 5px;
  position: relative;
}

.toggle-label:hover .toggle-slider {
  transform: scale(1.05);
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
  background-color: #ccc;
  transition: transform 0.3s ease, box-shadow 0.3s ease, background 0.3s ease;
  border-radius: 24px;
  box-shadow: inset 0 1px 3px rgba(0, 0, 0, 0.2);
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
  background-color: white;
  transition: 0.3s;
  border-radius: 50%;
  box-shadow: 0 2px 4px rgba(0, 0, 0, 0.2);
}

.toggle-input:checked + .toggle-slider {
  background: linear-gradient(135deg, var(--electric-primary) 0%, #b8762d 100%);
  box-shadow: inset 0 1px 3px rgba(0, 0, 0, 0.1), 0 0 8px rgba(var(--color-primary-rgb), 0.3);
}

.toggle-input:checked + .toggle-slider:before {
  transform: translateX(20px);
}

.toggle-label:hover .toggle-slider {
  box-shadow: inset 0 1px 3px rgba(0, 0, 0, 0.2), 0 0 4px rgba(0, 0, 0, 0.1);
}

.toggle-label:hover .toggle-input:checked + .toggle-slider {
  box-shadow: inset 0 1px 3px rgba(0, 0, 0, 0.1), 0 0 12px rgba(var(--color-primary-rgb), 0.4);
}

.toggle-label:active .toggle-slider {
  transform: scale(0.98);
  background-color: #ccc !important;
}

.toggle-label:active .toggle-input:checked + .toggle-slider {
  background: linear-gradient(135deg, var(--electric-primary) 0%, #b8762d 100%) !important;
}

.toggle-slider:active {
  background-color: #ccc !important;
}

.toggle-input:checked + .toggle-slider:active {
  background: linear-gradient(135deg, var(--electric-primary) 0%, #b8762d 100%) !important;
}

.toggle-label:active .toggle-slider:before {
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.2);
}

.toggle-text {
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
  width: 120px;
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
  max-width: 300px;
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

/* 合併模式樣式 */
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
  background: rgba(221, 132, 72, 0.15);
  color: var(--electric-primary);
  border-radius: 12px;
  font-size: 12px;
  font-weight: 600;
}

.file-count {
  font-size: 13px;
  color: rgba(45, 45, 45, 0.7);
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
  border-bottom: 1px solid rgba(221, 132, 72, 0.1);
}

.merge-file-item:last-child {
  border-bottom: none;
}

.merge-file-item .file-number {
  color: var(--electric-primary);
  font-weight: 600;
  min-width: 20px;
}

.merge-file-item .file-name {
  flex: 1;
  color: rgba(45, 45, 45, 0.9);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.merge-file-item .file-size {
  color: rgba(45, 45, 45, 0.5);
  font-size: 12px;
}

.task-name-section {
  margin-top: 12px;
  padding-top: 12px;
  border-top: 1px solid rgba(221, 132, 72, 0.15);
}

.task-name-input {
  width: 100%;
  max-width: 100%;
  padding: 10px 12px;
  font-size: 14px;
  border: 2px solid rgba(221, 132, 72, 0.3);
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.9);
  color: #2d2d2d;
  transition: all 0.3s;
  margin-top: 6px;
}

.task-name-input:focus {
  outline: none;
  border-color: var(--electric-primary);
  box-shadow: 0 0 0 3px rgba(221, 132, 72, 0.1);
}

.task-name-input::placeholder {
  color: rgba(45, 45, 45, 0.4);
}

.task-name-section .hint {
  margin-top: 6px;
  font-size: 11px;
  color: rgba(45, 45, 45, 0.5);
}

</style>
