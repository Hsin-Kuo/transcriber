<template>
  <div class="uploader-container electric-card">
    <div class="electric-inner">
      <div class="electric-border-outer">
        <div class="electric-main uploader-content">
          <div class="upload-icon">
            <svg width="64" height="64" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path>
              <polyline points="17 8 12 3 7 8"></polyline>
              <line x1="12" y1="3" x2="12" y2="15"></line>
            </svg>
          </div>
          <h2>上傳音檔</h2>
          <p>選擇音訊文件開始編輯</p>
          <input
            type="file"
            ref="fileInput"
            @change="handleFileChange"
            accept="audio/*,video/*,.m4a,.mp3,.wav,.mp4,.flac,.ogg"
            style="display: none"
          />
          <button @click="triggerFileSelect" class="btn btn-upload">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path>
              <polyline points="17 8 12 3 7 8"></polyline>
              <line x1="12" y1="3" x2="12" y2="15"></line>
            </svg>
            選擇檔案
          </button>
          <p class="file-hint">支援 MP3, WAV, M4A, FLAC, OGG 等格式</p>
        </div>
      </div>
      <div class="electric-glow-1"></div>
      <div class="electric-glow-2"></div>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'

const emit = defineEmits(['audio-loaded'])

const fileInput = ref(null)

function triggerFileSelect() {
  fileInput.value?.click()
}

function handleFileChange(event) {
  const file = event.target.files[0]
  if (file) {
    emit('audio-loaded', file)
  }
}
</script>

<style scoped>
.uploader-container {
  min-height: 400px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.uploader-content {
  padding: 60px 40px;
  text-align: center;
  background: linear-gradient(135deg, rgba(28, 28, 28, 0.95) 0%, rgba(20, 20, 20, 0.95) 100%);
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 20px;
}

.upload-icon {
  color: #DD8448;
  opacity: 0.8;
}

.uploader-content h2 {
  font-size: 1.8rem;
  margin: 0;
  color: #fff;
}

.uploader-content p {
  color: #aaa;
  margin: 0;
}

.btn-upload {
  display: inline-flex;
  align-items: center;
  gap: 10px;
  padding: 14px 32px;
  border: none;
  border-radius: 8px;
  background: linear-gradient(135deg, #FF6B35 0%, #DD8448 100%);
  color: white;
  font-size: 1.1rem;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.3s ease;
  margin-top: 10px;
}

.btn-upload:hover {
  transform: translateY(-2px);
  box-shadow: 0 8px 20px rgba(255, 107, 53, 0.4);
}

.file-hint {
  font-size: 0.85rem !important;
  color: #777 !important;
}
</style>
