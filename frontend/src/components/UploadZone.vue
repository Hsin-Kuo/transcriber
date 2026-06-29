<template>
  <div class="upload-zone-wrapper">
    <!-- 使用教學按鈕（三角形，嵌入左上角；與右下角合併鈕對稱） -->
    <button
      class="tour-triangle-btn"
      :class="{ disabled: disabled || uploading }"
      @click.stop="handleTourClick"
      :disabled="disabled || uploading"
      :title="$t('tour.replay')"
    >
      <div class="tour-content">
        <div class="tour-icon">
          <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <circle cx="12" cy="12" r="10" />
            <path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3" />
            <line x1="12" y1="17" x2="12.01" y2="17" />
          </svg>
        </div>
        <span class="tour-label">{{ $t('tour.replayShort') }}</span>
      </div>
    </button>

    <!-- 上傳區域 -->
    <div
      class="upload-zone"
      data-tour="upload"
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
        accept="audio/*,video/*,.m4a,.mp3,.wav,.mp4,.mov,.avi,.mkv,.webm,.flv,.wmv"
        multiple
        @change="handleFileChange"
        style="display: none"
      />

      <div v-if="!uploading" class="upload-content">
        <svg class="upload-icon" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
          <!-- 第一排：3個 -->
          <rect x="5.5" y="1" width="1.2" height="7" rx="0.5" fill="currentColor" />
          <rect x="11.5" y="0" width="1.2" height="5" rx="0.5" fill="currentColor" />
          <rect x="17.5" y="1" width="1.2" height="6" rx="0.5" stroke="currentColor" stroke-width="0.3" />

          <!-- 第二排：4個（與第一排交錯） -->
          <rect x="2.5" y="5" width="1.2" height="8" rx="0.5" stroke="currentColor" stroke-width="0.3" />
          <rect x="8.5" y="6" width="1.2" height="6" rx="0.5" fill="currentColor" />
          <rect x="14.5" y="5" width="1.2" height="5" rx="0.5" stroke="currentColor" stroke-width="0.3" />
          <rect x="20.5" y="4" width="1.2" height="7" rx="0.5" fill="currentColor" />

          <!-- 第三排：3個 -->
          <rect x="5.5" y="11" width="1.2" height="5" rx="0.5" stroke="currentColor" stroke-width="0.3" />
          <rect x="11.5" y="10" width="1.2" height="8" rx="0.5" fill="currentColor" />
          <rect x="17.5" y="12" width="1.2" height="6" rx="0.5" fill="currentColor" />

          <!-- 第四排：4個（與第三排交錯） -->
          <rect x="2.5" y="16" width="1.2" height="7" rx="0.5" fill="currentColor" />
          <rect x="8.5" y="17" width="1.2" height="5" rx="0.5" stroke="currentColor" stroke-width="0.3" />
          <rect x="14.5" y="15" width="1.2" height="8" rx="0.5" stroke="currentColor" stroke-width="0.3" />
          <rect x="20.5" y="17" width="1.2" height="6" rx="0.5" stroke="currentColor" stroke-width="0.3" />
        </svg>
        <h3>{{ $t('uploadZone.clickToUpload') }}</h3>
        <p>{{ $t('uploadZone.supportedFormats') }}</p>
        <p class="upload-outcome-hint">{{ $t('uploadZone.outcomeHint') }}</p>
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
      :title="$t('uploadZone.mergeMultiple')"
    >
      <div class="merge-icon">
        <svg width="36" height="24" viewBox="0 0 36 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round">
          <!-- 第一行（最右） -->
          <line x1="13" y1="4" x2="21" y2="4" />
          <line x1="26" y1="4" x2="34" y2="4" />
          <!-- 第二行 -->
          <line x1="11" y1="9" x2="19" y2="9" />
          <line x1="24" y1="9" x2="32" y2="9" />
          <!-- 第三行 -->
          <line x1="9" y1="14" x2="17" y2="14" />
          <line x1="22" y1="14" x2="30" y2="14" />
          <!-- 第四行（最左） -->
          <line x1="7" y1="19" x2="15" y2="19" />
          <line x1="20" y1="19" x2="28" y2="19" />
        </svg>
      </div>
      <span class="merge-label">{{ $t('uploadZone.mergeAudio') }}</span>
    </button>
  </div>
</template>

<script setup>
import { ref } from 'vue'

const props = defineProps({
  uploading: Boolean,
  disabled: Boolean
})

const emit = defineEmits(['file-selected', 'files-selected', 'open-merge', 'open-tour'])

const fileInput = ref(null)
const isDragOver = ref(false)

function triggerFileInput() {
  if (!props.uploading && !props.disabled) {
    fileInput.value?.click()
  }
}

function handleFileChange(event) {
  if (props.disabled) return

  const fileList = event.target.files
  if (fileList && fileList.length > 0) {
    const filesArray = Array.from(fileList)
    if (filesArray.length === 1) {
      // 單檔：維持現有行為
      emit('file-selected', filesArray[0])
    } else {
      // 多檔：發送檔案陣列
      emit('files-selected', filesArray)
    }
    event.target.value = '' // Reset input
  }
}

function handleDrop(event) {
  isDragOver.value = false
  if (props.uploading || props.disabled) return

  const fileList = event.dataTransfer.files
  if (fileList && fileList.length > 0) {
    const filesArray = Array.from(fileList)
    if (filesArray.length === 1) {
      // 單檔：維持現有行為
      emit('file-selected', filesArray[0])
    } else {
      // 多檔：發送檔案陣列
      emit('files-selected', filesArray)
    }
  }
}

function handleMergeClick() {
  if (!props.uploading && !props.disabled) {
    emit('open-merge')
  }
}

function handleTourClick() {
  if (!props.uploading && !props.disabled) {
    emit('open-tour')
  }
}
</script>

<style scoped>
.upload-zone {
  margin: 24px auto;
  padding: 60px 20px;
  min-height: 240px;
  box-sizing: border-box;
  max-width: 800px;
  text-align: center;
  cursor: pointer;
  transition: all 0.3s ease;
  /* background: var(--upload-bg); */
  border: 1px solid var(--nav-text);
  /* 左上切角較小(110px)嵌「使用教學」、右下切角(140px)嵌「合併」三角鈕 */
  clip-path: polygon(
    110px 0,
    100% 0,
    100% calc(100% - 140px),
    calc(100% - 140px) 100%,
    0 100%,
    0 110px
  );
  position: relative;
}


.upload-zone.drag-over {
  box-shadow:
    inset 10px 10px 20px var(--main-shadow-dark),
    inset -10px -10px 20px var(--main-shadow-light);
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

.upload-content p.upload-outcome-hint {
  max-width: 460px;
  margin: -12px auto 0;
  font-size: 12px;
  line-height: 1.6;
  opacity: 0.75;
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
  border-top: 4px solid var(--main-primary);
  border-right: 4px solid var(--main-primary-light);
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
  color: var(--main-text);
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
  background: var(--main-bg, #e0e5ec);
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
    -3px -3px 6px var(--main-shadow-light, rgba(255, 255, 255, 0.8)),
    3px 3px 6px var(--main-shadow-dark, rgba(163, 177, 198, 0.6));
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
  stroke: rgba(var(--color-text-dark-rgb), 0.5);
  transition: stroke 0.3s ease;
}

.merge-label {
  font-size: 12px;
  font-weight: 500;
  color: rgba(var(--color-text-dark-rgb), 0.6);
  margin-top: 4px;
  transition: color 0.3s ease;
}

/* 三角形使用教學按鈕 - 嵌入左上角（比合併鈕小，內容貼左上外緣） */
.tour-triangle-btn {
  position: absolute;
  top: 0;
  left: 0;
  width: 110px;
  height: 110px;
  background: var(--main-bg, #e0e5ec);
  border: none;
  cursor: pointer;
  display: flex;
  flex-direction: column;
  /* 內容釘在左上角、貼近外側邊緣 */
  align-items: flex-start;
  justify-content: flex-start;
  padding: 12px 0 0 14px;
  clip-path: polygon(0 0, 100% 0, 0 100%);
  transition: all 0.3s ease;
  box-shadow:
    -3px -3px 6px var(--main-shadow-light, rgba(255, 255, 255, 0.8)),
    3px 3px 6px var(--main-shadow-dark, rgba(163, 177, 198, 0.6));
}

.tour-triangle-btn:hover:not(.disabled) {
  background: rgba(221, 132, 72, 0.1);
}

.tour-triangle-btn:hover:not(.disabled) .tour-icon svg {
  stroke: var(--electric-primary, #dd8448);
}

.tour-triangle-btn:hover:not(.disabled) .tour-label {
  color: var(--electric-primary, #dd8448);
}

.tour-triangle-btn.disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

/* shrink-wrap 容器：整塊靠左上(由按鈕 flex-start 決定)，內部 icon 置中於文字上方 */
.tour-content {
  display: flex;
  flex-direction: column;
  align-items: center;
}

.tour-icon {
  display: flex;
  align-items: center;
  justify-content: center;
}

.tour-icon svg {
  width: 16px;
  height: 16px;
  stroke: rgba(var(--color-text-dark-rgb), 0.5);
  transition: stroke 0.3s ease;
}

.tour-label {
  font-size: 11px;
  font-weight: 500;
  color: rgba(var(--color-text-dark-rgb), 0.6);
  margin-top: 3px;
  transition: color 0.3s ease;
}

@media (max-width: 768px) {
  .tour-triangle-btn {
    width: 88px;
    height: 88px;
    padding: 10px 0 0 11px;
  }

  .tour-icon svg {
    width: 14px;
    height: 14px;
  }

  .tour-label {
    font-size: 10px;
  }

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
