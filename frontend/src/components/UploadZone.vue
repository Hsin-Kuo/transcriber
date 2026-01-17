<template>
  <div class="upload-zone-wrapper">
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

    <!-- 合併按鈕（三角形，嵌入右下角） -->
    <button
      class="merge-triangle-btn"
      :class="{ disabled: disabled || uploading }"
      @click.stop="handleMergeClick"
      :disabled="disabled || uploading"
      title="合併多個音檔"
    >
      <div class="merge-icon">
        <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01"></path>
        </svg>
      </div>
      <span class="merge-label">合併音檔</span>
    </button>
  </div>
</template>

<script setup>
import { ref } from 'vue'

const props = defineProps({
  uploading: Boolean,
  disabled: Boolean
})

const emit = defineEmits(['file-selected', 'open-merge'])

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

function handleMergeClick() {
  if (!props.uploading && !props.disabled) {
    emit('open-merge')
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
    100% calc(100% - 140px),
    calc(100% - 140px) 100%,
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

/* Wrapper for positioning the triangle button */
.upload-zone-wrapper {
  position: relative;
  max-width: 800px;
  margin: 0 auto;
}

/* 三角形合併按鈕 - 嵌入右下角 */
.merge-triangle-btn {
  position: absolute;
  bottom: 0;
  right: 0;
  width: 140px;
  height: 140px;
  background: var(--neu-bg, #e0e5ec);
  border: none;
  cursor: pointer;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding-top: 40px;
  padding-left: 40px;
  clip-path: polygon(100% 0, 100% 100%, 0 100%);
  transition: all 0.3s ease;
  box-shadow:
    -3px -3px 6px var(--neu-shadow-light, rgba(255, 255, 255, 0.8)),
    3px 3px 6px var(--neu-shadow-dark, rgba(163, 177, 198, 0.6));
}

.merge-triangle-btn:hover:not(.disabled) {
  background: rgba(221, 132, 72, 0.1);
}

.merge-triangle-btn:hover:not(.disabled) .merge-icon svg {
  stroke: var(--electric-primary, #dd8448);
}

.merge-triangle-btn:hover:not(.disabled) .merge-label {
  color: var(--electric-primary, #dd8448);
}

.merge-triangle-btn.disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.merge-icon {
  display: flex;
  align-items: center;
  justify-content: center;
}

.merge-icon svg {
  stroke: rgba(45, 45, 45, 0.5);
  transition: stroke 0.3s ease;
}

.merge-label {
  font-size: 12px;
  font-weight: 500;
  color: rgba(45, 45, 45, 0.6);
  margin-top: 4px;
  transition: color 0.3s ease;
}

@media (max-width: 768px) {
  .merge-triangle-btn {
    width: 100px;
    height: 100px;
    padding-top: 30px;
    padding-left: 30px;
  }

  .merge-icon svg {
    width: 20px;
    height: 20px;
  }

  .merge-label {
    font-size: 10px;
  }
}
</style>
