<template>
  <!-- 上傳區域 -->
  <div
    class="upload-zone"
    :class="{
      'drag-over': isDragOver && !disabled,
      'uploading': uploading,
      'disabled': disabled
    }"
    @dragover.prevent="!disabled && (isDragOver = true)"
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
      <h3>{{ $t('uploadZone.clickToUpload') }}</h3>
      <p>{{ $t('uploadZone.supportedFormats') }}</p>
    </div>

    <div v-else class="uploading-content">
      <div class="spinner-large"></div>
      <p>{{ $t('uploadZone.uploadingFile') }}</p>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'

const props = defineProps({
  uploading: Boolean,
  disabled: Boolean
})

const emit = defineEmits(['file-selected'])

const fileInput = ref(null)
const isDragOver = ref(false)

function triggerFileInput() {
  if (!props.uploading && !props.disabled) {
    fileInput.value?.click()
  }
}

function handleFileChange(event) {
  if (props.disabled) return

  const file = event.target.files?.[0]
  if (file) {
    emit('file-selected', file)
    event.target.value = '' // Reset input
  }
}

function handleDrop(event) {
  isDragOver.value = false
  if (props.uploading || props.disabled) return

  const file = event.dataTransfer.files?.[0]
  if (file) {
    emit('file-selected', file)
  }
}
</script>

<style scoped>
.upload-zone {
  margin: 24px auto;
  padding: 60px 20px;
  max-width: 800px;
  text-align: center;
  cursor: pointer;
  transition: all 0.3s ease;
  background: var(--upload-bg);
  clip-path: polygon(
    60px 0,
    100% 0,
    100% calc(100% - 60px),
    calc(100% - 60px) 100%,
    0 100%,
    0 60px
  );
  position: relative;
}

.upload-zone:hover:not(.uploading) {
  box-shadow: var(--neu-shadow-inset-hover);
}

.upload-zone.drag-over {
  box-shadow:
    inset 10px 10px 20px var(--neu-shadow-dark),
    inset -10px -10px 20px var(--neu-shadow-light);
  transform: scale(0.99);
}

.upload-zone.uploading {
  cursor: not-allowed;
  opacity: 0.8;
}

.upload-zone.disabled {
  cursor: not-allowed;
  opacity: 0.5;
  pointer-events: none;
}

.upload-icon {
  width: 64px;
  height: 64px;
  margin: 0 auto 20px;
  color: var(--nav-recent-bg);
  filter: drop-shadow(0 2px 8px rgba(163, 177, 198, 0.3));
  position: relative;
  z-index: 1;
}

.upload-content h3 {
  font-size: 20px;
  color: var(--nav-text);
  margin-bottom: 10px;
  font-weight: 700;
  position: relative;
  z-index: 1;
}

.upload-content p {
  color: var(--nav-active-bg);
  margin-bottom: 24px;
  font-size: 14px;
  position: relative;
  z-index: 1;
}

.uploading-content {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 16px;
  position: relative;
  z-index: 1;
}

.spinner-large {
  width: 48px;
  height: 48px;
  border: 4px solid transparent;
  border-top: 4px solid var(--neu-primary);
  border-right: 4px solid var(--neu-primary-light);
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
  color: var(--neu-text);
  font-weight: 600;
}
</style>
