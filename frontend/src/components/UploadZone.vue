<template>
  <!-- 電流邊框上傳區域 -->
  <div class="electric-card upload-zone">
    <div class="electric-inner">
      <!-- 主要邊框層 -->
      <div class="electric-border-outer">
        <div
          class="electric-main drop-area"
          :class="{
            'drag-over': isDragOver,
            'uploading': uploading,
            'animated': !uploading
          }"
          @dragover.prevent="isDragOver = true"
          @dragleave.prevent="isDragOver = false"
          @drop.prevent="handleDrop"
          @click="triggerFileInput"
        >
          <input
            ref="fileInput"
            type="file"
            accept="audio/*,video/*,.m4a,.mp3,.wav,.mp4"
            @change="handleFileChange"
            style="display: none"
          />

          <div v-if="!uploading" class="upload-content">
            <svg class="upload-icon" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path
                stroke-linecap="round"
                stroke-linejoin="round"
                stroke-width="2"
                d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12"
              />
            </svg>
            <h3>Click to upload or drag and drop</h3>
            <p>Support M4A, MP3, WAV, MP4 and other audio formats</p>
            <button class="btn btn-primary glass-btn" @click.stop="triggerFileInput">
              Choose File
            </button>
          </div>

          <div v-else class="uploading-content">
            <div class="spinner-large"></div>
            <p>Uploading file...</p>
          </div>
        </div>
      </div>

      <!-- 光暈層 -->
      <div class="electric-glow-1"></div>
      <div class="electric-glow-2"></div>
    </div>

    <!-- 疊加效果 -->
    <div class="electric-overlay"></div>
    <div class="electric-bg-glow"></div>
  </div>
</template>

<script setup>
import { ref } from 'vue'

const props = defineProps({
  uploading: Boolean
})

const emit = defineEmits(['file-selected'])

const fileInput = ref(null)
const isDragOver = ref(false)

function triggerFileInput() {
  if (!props.uploading) {
    fileInput.value?.click()
  }
}

function handleFileChange(event) {
  const file = event.target.files?.[0]
  if (file) {
    emit('file-selected', file)
    event.target.value = '' // 重置 input
  }
}

function handleDrop(event) {
  isDragOver.value = false
  if (props.uploading) return

  const file = event.dataTransfer.files?.[0]
  if (file) {
    emit('file-selected', file)
  }
}
</script>

<style scoped>
.upload-zone {
  margin-bottom: 24px;
}

.drop-area {
  padding: 60px 20px;
  text-align: center;
  cursor: pointer;
  transition: all 0.3s;
  position: relative;
  z-index: 1;
}

.drop-area:hover:not(.uploading) {
  transform: translateY(-2px);
  box-shadow: 0 8px 24px rgba(221, 132, 72, 0.2);
}

.drop-area.drag-over {
  background: rgba(221, 132, 72, 0.05);
  transform: scale(1.01);
}

.drop-area.uploading {
  cursor: not-allowed;
  opacity: 0.8;
}

.upload-icon {
  width: 64px;
  height: 64px;
  margin: 0 auto 20px;
  color: var(--electric-primary);
  filter: drop-shadow(0 2px 8px rgba(221, 132, 72, 0.5));
}

.upload-content h3 {
  font-size: 20px;
  color: #2d2d2d;
  margin-bottom: 10px;
  font-weight: 600;
}

.upload-content p {
  color: rgba(45, 45, 45, 0.7);
  margin-bottom: 24px;
  font-size: 14px;
}

/* 玻璃態按鈕 */
.glass-btn {
  position: relative;
  background: var(--electric-primary) !important;
  backdrop-filter: blur(8px);
  box-shadow: 0 4px 16px rgba(221, 132, 72, 0.4);
}

.glass-btn:hover {
  box-shadow: 0 6px 20px rgba(221, 132, 72, 0.6);
  transform: translateY(-2px);
}

.uploading-content {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 16px;
}

.spinner-large {
  width: 48px;
  height: 48px;
  border: 4px solid rgba(221, 132, 72, 0.15);
  border-top: 4px solid var(--electric-primary);
  border-radius: 50%;
  animation: spin 1s linear infinite;
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}

.uploading-content p {
  font-size: 16px;
  color: rgba(45, 45, 45, 0.9);
  font-weight: 500;
}
</style>
