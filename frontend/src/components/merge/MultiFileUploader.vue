<template>
  <div
    class="multi-file-uploader"
    :class="{ 'drag-over': isDragOver }"
    @dragover.prevent="handleDragOver"
    @dragleave.prevent="handleDragLeave"
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

    <div class="upload-hint">
      <svg class="upload-icon" width="64" height="64" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path>
        <polyline points="17 8 12 3 7 8"></polyline>
        <line x1="12" y1="3" x2="12" y2="15"></line>
      </svg>
      <h4>拖放多個音檔到此處</h4>
      <p>或點擊選擇檔案</p>
      <p class="hint">支援 mp3, wav, m4a, mp4 等格式</p>
      <p class="file-count-hint">⚠️ 至少需要 2 個檔案</p>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'

const emit = defineEmits(['files-added'])

const fileInput = ref(null)
const isDragOver = ref(false)

function triggerFileInput() {
  fileInput.value?.click()
}

function handleDragOver(event) {
  isDragOver.value = true
}

function handleDragLeave(event) {
  isDragOver.value = false
}

function handleFileChange(event) {
  const files = Array.from(event.target.files || [])
  if (files.length > 0) {
    emit('files-added', files)
  }
  // 清空input，允許重複選擇相同檔案
  event.target.value = ''
}

function handleDrop(event) {
  isDragOver.value = false
  const files = Array.from(event.dataTransfer.files || [])

  // 過濾只保留音檔和視頻檔案
  const audioVideoFiles = files.filter(file => {
    const type = file.type
    const name = file.name.toLowerCase()
    return type.startsWith('audio/') ||
           type.startsWith('video/') ||
           name.endsWith('.m4a') ||
           name.endsWith('.mp3') ||
           name.endsWith('.wav') ||
           name.endsWith('.mp4')
  })

  if (audioVideoFiles.length > 0) {
    emit('files-added', audioVideoFiles)
  }
}
</script>

<style scoped>
.multi-file-uploader {
  width: 100%;
  max-width: 600px;
  margin: 0 auto;
  padding: 40px;
  border: 3px dashed rgba(221, 132, 72, 0.3);
  border-radius: 16px;
  background: rgba(255, 255, 255, 0.5);
  cursor: pointer;
  transition: all 0.3s ease;
  text-align: center;
}

.multi-file-uploader:hover {
  border-color: rgba(221, 132, 72, 0.6);
  background: rgba(255, 255, 255, 0.8);
  transform: translateY(-2px);
}

.multi-file-uploader.drag-over {
  border-color: var(--electric-primary);
  background: rgba(221, 132, 72, 0.1);
  border-style: solid;
}

.upload-hint {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
  color: rgba(45, 45, 45, 0.8);
}

.upload-icon {
  color: var(--electric-primary);
  margin-bottom: 8px;
}

.upload-hint h4 {
  font-size: 18px;
  font-weight: 600;
  margin: 0;
  color: rgba(45, 45, 45, 0.9);
}

.upload-hint p {
  font-size: 14px;
  margin: 0;
  color: rgba(45, 45, 45, 0.7);
}

.upload-hint .hint {
  font-size: 12px;
  color: rgba(45, 45, 45, 0.5);
}

.upload-hint .file-count-hint {
  font-size: 12px;
  color: rgba(221, 132, 72, 0.8);
  font-weight: 500;
  margin-top: 4px;
}

@media (max-width: 768px) {
  .multi-file-uploader {
    padding: 30px 20px;
  }

  .upload-hint h4 {
    font-size: 16px;
  }

  .upload-hint p {
    font-size: 13px;
  }
}
</style>
