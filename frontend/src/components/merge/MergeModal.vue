<template>
  <Teleport to="body">
    <div v-if="visible" class="modal-overlay" @click.self="handleCancel">
      <div class="modal-container">
        <!-- 標題列 -->
        <div class="modal-header">
          <h2>音檔合併服務</h2>
          <button class="close-btn" @click="handleCancel" title="關閉">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <line x1="18" y1="6" x2="6" y2="18"></line>
              <line x1="6" y1="6" x2="18" y2="18"></line>
            </svg>
          </button>
        </div>

        <!-- 主要內容區 -->
        <div class="modal-body">
          <!-- 左側：上傳區 -->
          <div class="upload-section">
            <div class="section-title">上傳音檔</div>
            <div
              class="upload-zone"
              :class="{ 'drag-over': isDragOver }"
              @dragover.prevent="isDragOver = true"
              @dragleave.prevent="isDragOver = false"
              @drop.prevent="handleDrop"
              @click="triggerFileInput"
            >
              <input
                ref="fileInput"
                type="file"
                multiple
                accept="audio/*,video/*,.m4a,.mp3,.wav,.mp4"
                @change="handleFileChange"
                style="display: none"
              />
              <svg class="upload-icon" width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path>
                <polyline points="17 8 12 3 7 8"></polyline>
                <line x1="12" y1="3" x2="12" y2="15"></line>
              </svg>
              <p class="upload-text">拖放音檔到此處</p>
              <p class="upload-hint">或點擊選擇檔案</p>
              <p class="format-hint">支援 mp3, wav, m4a, mp4 等格式</p>
            </div>
          </div>

          <!-- 右側：檔案列表 -->
          <div class="files-section">
            <div class="section-title">
              已選擇的檔案
              <span class="file-count" v-if="files.length > 0">({{ files.length }})</span>
            </div>

            <div v-if="files.length === 0" class="empty-list">
              <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
                <path d="M13 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"></path>
                <polyline points="13 2 13 9 20 9"></polyline>
              </svg>
              <p>尚未選擇檔案</p>
              <p class="hint">從左側上傳音檔</p>
            </div>

            <draggable
              v-else
              :list="files"
              @change="handleOrderChange"
              class="file-list"
              handle=".drag-handle"
              item-key="id"
            >
              <div
                v-for="(file, index) in files"
                :key="file.id"
                class="file-item"
              >
                <div class="drag-handle" title="拖曳調整順序">
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <circle cx="9" cy="5" r="1"></circle>
                    <circle cx="9" cy="12" r="1"></circle>
                    <circle cx="9" cy="19" r="1"></circle>
                    <circle cx="15" cy="5" r="1"></circle>
                    <circle cx="15" cy="12" r="1"></circle>
                    <circle cx="15" cy="19" r="1"></circle>
                  </svg>
                </div>
                <div class="file-number">{{ index + 1 }}</div>
                <div class="file-info">
                  <span class="file-name" :title="file.name">{{ file.name }}</span>
                  <span class="file-size">{{ formatSize(file.size) }}</span>
                </div>
                <button class="remove-btn" @click="removeFile(index)" title="移除">
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <line x1="18" y1="6" x2="6" y2="18"></line>
                    <line x1="6" y1="6" x2="18" y2="18"></line>
                  </svg>
                </button>
              </div>
            </draggable>

            <!-- 總計資訊 -->
            <div v-if="files.length > 0" class="total-info">
              <span>合計大小：{{ totalSize }}</span>
            </div>
          </div>
        </div>

        <!-- 底部操作區 -->
        <div class="modal-footer">
          <div class="footer-hint" v-if="files.length < 2">
            請至少選擇 2 個檔案進行合併
          </div>
          <div class="footer-actions">
            <button class="btn btn-cancel" @click="handleCancel">取消</button>
            <button
              class="btn btn-primary"
              @click="handleConfirm"
              :disabled="files.length < 2"
            >
              下一步：轉錄設定
            </button>
          </div>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<script setup>
import { ref, computed } from 'vue'
import { VueDraggableNext as draggable } from 'vue-draggable-next'

const props = defineProps({
  visible: {
    type: Boolean,
    default: false
  }
})

const emit = defineEmits(['close', 'confirm'])

const fileInput = ref(null)
const isDragOver = ref(false)
const files = ref([])

// 生成唯一 ID
function generateId() {
  return `file-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`
}

// 格式化檔案大小
function formatSize(bytes) {
  if (bytes < 1024) return bytes + ' B'
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB'
  return (bytes / 1024 / 1024).toFixed(2) + ' MB'
}

// 總大小
const totalSize = computed(() => {
  const bytes = files.value.reduce((sum, f) => sum + f.size, 0)
  return formatSize(bytes)
})

// 觸發檔案選擇
function triggerFileInput() {
  fileInput.value?.click()
}

// 處理檔案選擇
function handleFileChange(event) {
  const selectedFiles = Array.from(event.target.files || [])
  addFiles(selectedFiles)
  event.target.value = '' // 清空以允許重複選擇相同檔案
}

// 處理拖放
function handleDrop(event) {
  isDragOver.value = false
  const droppedFiles = Array.from(event.dataTransfer.files || [])

  // 過濾只保留音檔和視頻檔案
  const audioVideoFiles = droppedFiles.filter(file => {
    const type = file.type
    const name = file.name.toLowerCase()
    return type.startsWith('audio/') ||
           type.startsWith('video/') ||
           name.endsWith('.m4a') ||
           name.endsWith('.mp3') ||
           name.endsWith('.wav') ||
           name.endsWith('.mp4')
  })

  addFiles(audioVideoFiles)
}

// 添加檔案到列表
function addFiles(newFiles) {
  const wrappedFiles = newFiles.map(f => ({
    id: generateId(),
    file: f,
    name: f.name,
    size: f.size,
    type: f.type
  }))
  files.value = [...files.value, ...wrappedFiles]
}

// 處理順序變更
function handleOrderChange() {
  // draggable 會自動更新 files 陣列
}

// 移除檔案
function removeFile(index) {
  files.value.splice(index, 1)
}

// 取消
function handleCancel() {
  files.value = []
  emit('close')
}

// 確認進入下一步
function handleConfirm() {
  if (files.value.length < 2) return

  // 提取原始 File 物件
  const originalFiles = files.value.map(f => f.file)
  emit('confirm', originalFiles)
  files.value = []
}
</script>

<style scoped>
.modal-overlay {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
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
  max-width: 800px;
  max-height: 85vh;
  background: var(--neu-bg);
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
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 20px;
  padding: 20px 24px;
  overflow-y: auto;
  flex: 1;
}

@media (max-width: 600px) {
  .modal-body {
    grid-template-columns: 1fr;
  }
}

.section-title {
  font-size: 14px;
  font-weight: 600;
  color: rgba(var(--color-text-dark-rgb), 0.7);
  margin-bottom: 12px;
  display: flex;
  align-items: center;
  gap: 6px;
}

.file-count {
  font-weight: 500;
  color: var(--color-primary);
}

/* 上傳區 */
.upload-section {
  display: flex;
  flex-direction: column;
}

.upload-zone {
  flex: 1;
  min-height: 200px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 30px 20px;
  border: 3px dashed rgba(var(--color-primary-rgb), 0.3);
  border-radius: 16px;
  background: rgba(255, 255, 255, 0.5);
  cursor: pointer;
  transition: all 0.3s ease;
  text-align: center;
}

.upload-zone:hover {
  border-color: rgba(var(--color-primary-rgb), 0.5);
  background: rgba(255, 255, 255, 0.8);
}

.upload-zone.drag-over {
  border-color: var(--color-primary);
  border-style: solid;
  background: rgba(var(--color-primary-rgb), 0.1);
}

.upload-icon {
  color: var(--color-primary);
  margin-bottom: 12px;
}

.upload-text {
  font-size: 16px;
  font-weight: 600;
  color: rgba(var(--color-text-dark-rgb), 0.8);
  margin: 0 0 4px;
}

.upload-hint {
  font-size: 14px;
  color: rgba(var(--color-text-dark-rgb), 0.6);
  margin: 0 0 8px;
}

.format-hint {
  font-size: 12px;
  color: rgba(var(--color-text-dark-rgb), 0.4);
  margin: 0;
}

/* 檔案列表區 */
.files-section {
  display: flex;
  flex-direction: column;
}

.empty-list {
  flex: 1;
  min-height: 200px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  color: rgba(var(--color-text-dark-rgb), 0.4);
  text-align: center;
}

.empty-list svg {
  margin-bottom: 12px;
}

.empty-list p {
  margin: 0;
  font-size: 14px;
}

.empty-list .hint {
  font-size: 12px;
  margin-top: 4px;
}

.file-list {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 8px;
  max-height: 300px;
  overflow-y: auto;
  padding-right: 4px;
}

.file-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 12px;
  background: rgba(255, 255, 255, 0.8);
  border: 1px solid rgba(var(--color-divider-rgb), 0.3);
  border-radius: 10px;
  transition: all 0.2s;
}

.file-item:hover {
  background: var(--color-white);
  border-color: rgba(var(--color-primary-rgb), 0.3);
  box-shadow: 0 2px 8px rgba(var(--color-text-dark-rgb), 0.08);
}

.drag-handle {
  color: rgba(var(--color-text-dark-rgb), 0.3);
  cursor: grab;
  padding: 4px;
  display: flex;
  align-items: center;
}

.drag-handle:active {
  cursor: grabbing;
}

.drag-handle:hover {
  color: rgba(var(--color-text-dark-rgb), 0.6);
}

.file-number {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  background: rgba(var(--color-primary-rgb), 0.15);
  border-radius: 50%;
  font-size: 12px;
  font-weight: 600;
  color: var(--color-primary);
  flex-shrink: 0;
}

.file-info {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.file-name {
  font-size: 13px;
  font-weight: 500;
  color: rgba(var(--color-text-dark-rgb), 0.9);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.file-size {
  font-size: 11px;
  color: rgba(var(--color-text-dark-rgb), 0.5);
}

.remove-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  padding: 0;
  background: transparent;
  border: none;
  border-radius: 6px;
  color: color-mix(in srgb, var(--color-danger) 50%, transparent);
  cursor: pointer;
  transition: all 0.2s;
  flex-shrink: 0;
}

.remove-btn:hover {
  background: color-mix(in srgb, var(--color-danger) 10%, transparent);
  color: var(--color-danger);
}

.total-info {
  margin-top: 12px;
  padding-top: 12px;
  border-top: 1px solid rgba(var(--color-divider-rgb), 0.3);
  font-size: 13px;
  font-weight: 600;
  color: rgba(var(--color-text-dark-rgb), 0.7);
  text-align: right;
}

/* 底部 */
.modal-footer {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 16px 24px;
  border-top: 1px solid rgba(var(--color-divider-rgb), 0.3);
  gap: 16px;
}

.footer-hint {
  font-size: 13px;
  color: rgba(var(--color-primary-rgb), 0.8);
  font-weight: 500;
}

.footer-actions {
  display: flex;
  gap: 12px;
  margin-left: auto;
}

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

.btn-primary:active:not(:disabled) {
  transform: translateY(0);
}

@media (max-width: 600px) {
  .modal-container {
    width: 95%;
    max-height: 90vh;
  }

  .modal-header {
    padding: 16px 20px;
  }

  .modal-body {
    padding: 16px 20px;
  }

  .modal-footer {
    flex-direction: column;
    padding: 16px 20px;
  }

  .footer-actions {
    width: 100%;
    justify-content: flex-end;
  }
}
</style>
