<template>
  <div v-if="show" class="download-dialog-overlay" @click.self="$emit('close')">
    <div class="download-dialog">
      <div class="dialog-header">
        <h3>{{ $t('downloadDialog.title') }}</h3>
        <button @click="$emit('close')" class="btn-close" :title="$t('downloadDialog.cancel')">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <line x1="18" y1="6" x2="6" y2="18"></line>
            <line x1="6" y1="6" x2="18" y2="18"></line>
          </svg>
        </button>
      </div>

      <div class="dialog-body">
        <!-- 字幕模式設定（僅字幕模式顯示） -->
        <ul v-if="displayMode === 'subtitle' && (selectedFormat === 'txt' || selectedFormat === 'pdf')" class="current-settings">
          <li><strong>{{ $t('downloadDialog.timeFormat') }}</strong>{{ timeFormat === 'start' ? $t('subtitleTable.startTime') : $t('subtitleTable.timeRange') }}</li>
          <li><strong>{{ $t('downloadDialog.density') }}</strong>{{ densityThreshold.toFixed(0) }}s</li>
        </ul>

        <!-- 下載內容選項（僅 TXT/PDF 顯示） -->
        <div v-if="showContentOptions" class="content-options">
          <label class="section-label">{{ $t('downloadDialog.contentToDownload') }}</label>
          <div class="checkbox-group">
            <label v-if="hasSummary" class="checkbox-label">
              <input
                type="checkbox"
                :checked="includeSummary"
                @change="$emit('update:includeSummary', $event.target.checked)"
                class="checkbox-input"
              />
              <span class="checkbox-text">{{ $t('downloadDialog.includeSummary') }}</span>
            </label>
            <label class="checkbox-label">
              <input
                type="checkbox"
                :checked="includeTranscript"
                @change="$emit('update:includeTranscript', $event.target.checked)"
                class="checkbox-input"
              />
              <span class="checkbox-text">{{ $t('downloadDialog.includeTranscript') }}</span>
            </label>
          </div>
        </div>

        <!-- 講者資訊選項（僅字幕模式顯示） -->
        <div v-if="hasSpeakerInfo && displayMode === 'subtitle'" class="speaker-option">
          <label class="checkbox-label">
            <input
              type="checkbox"
              :checked="includeSpeaker"
              @change="$emit('update:includeSpeaker', $event.target.checked)"
              class="checkbox-input"
            />
            <span class="checkbox-text">{{ $t('downloadDialog.speakerInfo') }}</span>
          </label>
        </div>

        <div class="format-options">
          <label class="format-option">
            <input
              type="radio"
              :value="'txt'"
              :checked="selectedFormat === 'txt'"
              @change="$emit('update:selectedFormat', 'txt')"
              name="downloadFormat"
            />
            <div class="format-info">
              <span class="format-name">{{ $t('downloadDialog.txtFormat') }}</span>
            </div>
          </label>

          <!-- SRT/VTT 僅字幕模式顯示 -->
          <label v-if="displayMode === 'subtitle'" class="format-option">
            <input
              type="radio"
              :value="'srt'"
              :checked="selectedFormat === 'srt'"
              @change="$emit('update:selectedFormat', 'srt')"
              name="downloadFormat"
            />
            <div class="format-info">
              <span class="format-name">{{ $t('downloadDialog.srtFormat') }}</span>
            </div>
          </label>

          <label v-if="displayMode === 'subtitle'" class="format-option">
            <input
              type="radio"
              :value="'vtt'"
              :checked="selectedFormat === 'vtt'"
              @change="$emit('update:selectedFormat', 'vtt')"
              name="downloadFormat"
            />
            <div class="format-info">
              <span class="format-name">{{ $t('downloadDialog.vttFormat') }}</span>
            </div>
          </label>

          <label class="format-option">
            <input
              type="radio"
              :value="'pdf'"
              :checked="selectedFormat === 'pdf'"
              @change="$emit('update:selectedFormat', 'pdf')"
              name="downloadFormat"
            />
            <div class="format-info">
              <span class="format-name">{{ $t('downloadDialog.pdfFormat') }}</span>
            </div>
          </label>
        </div>
      </div>

      <div class="dialog-footer">
        <button @click="$emit('close')" class="btn btn-secondary">
          {{ $t('downloadDialog.cancel') }}
        </button>
        <button @click="$emit('download')" class="btn btn-primary" :disabled="!canDownload">
          {{ $t('downloadDialog.download') }}
        </button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

const { t: $t } = useI18n()

const props = defineProps({
  show: {
    type: Boolean,
    default: false
  },
  displayMode: {
    type: String,
    default: 'subtitle' // 'paragraph' | 'subtitle'
  },
  timeFormat: {
    type: String,
    default: 'start'
  },
  densityThreshold: {
    type: Number,
    default: 0
  },
  hasSpeakerInfo: {
    type: Boolean,
    default: false
  },
  hasSummary: {
    type: Boolean,
    default: false
  },
  selectedFormat: {
    type: String,
    default: 'txt'
  },
  includeSpeaker: {
    type: Boolean,
    default: true
  },
  includeSummary: {
    type: Boolean,
    default: true
  },
  includeTranscript: {
    type: Boolean,
    default: true
  }
})

defineEmits(['close', 'download', 'update:selectedFormat', 'update:includeSpeaker', 'update:includeSummary', 'update:includeTranscript'])

// 是否顯示內容選項（僅 TXT/PDF 顯示）
const showContentOptions = computed(() => {
  return (props.selectedFormat === 'txt' || props.selectedFormat === 'pdf') && props.hasSummary
})

// 是否可以下載（至少要選擇一個內容）
const canDownload = computed(() => {
  // SRT/VTT 格式不需要選擇內容
  if (props.selectedFormat === 'srt' || props.selectedFormat === 'vtt') {
    return true
  }
  // TXT/PDF 格式需要至少選擇一個內容
  return props.includeSummary || props.includeTranscript
})
</script>

<style scoped>
/* 下載對話框 */
.download-dialog-overlay {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(0, 0, 0, 0.5);
  backdrop-filter: blur(4px);
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

.download-dialog {
  background: var(--main-bg);
  border-radius: 16px;
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.2);
  max-width: 500px;
  width: 90%;
  max-height: 80vh;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  animation: slideUp 0.3s ease;
}

@keyframes slideUp {
  from {
    transform: translateY(20px);
    opacity: 0;
  }
  to {
    transform: translateY(0);
    opacity: 1;
  }
}

.dialog-header {
  padding: 24px;
  border-bottom: 1px solid rgba(160, 145, 124, 0.2);
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.dialog-header h3 {
  margin: 0;
  font-size: 20px;
  font-weight: 600;
  color: var(--main-text);
}

.btn-close {
  background: transparent;
  border: none;
  cursor: pointer;
  padding: 8px;
  border-radius: 8px;
  color: var(--main-text-light);
  transition: all 0.2s ease;
  display: flex;
  align-items: center;
  justify-content: center;
}

.btn-close:hover {
  background: rgba(160, 145, 124, 0.15);
  color: var(--main-text);
}

.dialog-body {
  padding: 24px;
  overflow-y: auto;
  flex: 1;
}

.current-settings {
  background: rgba(160, 145, 124, 0.15);
  border-radius: 8px;
  padding: 16px;
  margin: 0 0 24px 0;
  list-style: none;
}

.current-settings li {
  margin: 8px 0;
  font-size: 14px;
  color: var(--main-text-light);
}

.current-settings strong {
  color: var(--main-text);
  font-weight: 600;
}

/* 內容選項 */
.content-options {
  background: rgba(160, 145, 124, 0.08);
  border-radius: 8px;
  padding: 16px;
  margin: 0 0 16px 0;
}

.section-label {
  display: block;
  font-size: 14px;
  font-weight: 600;
  color: var(--main-text);
  margin-bottom: 12px;
}

.checkbox-group {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

/* 講者選項 */
.speaker-option {
  background: rgba(160, 145, 124, 0.08);
  border-radius: 8px;
  padding: 16px;
  margin: 0 0 24px 0;
}

.checkbox-label {
  display: flex;
  align-items: center;
  gap: 10px;
  cursor: pointer;
  user-select: none;
}

.checkbox-input {
  width: 18px;
  height: 18px;
  cursor: pointer;
  accent-color: var(--main-primary);
}

.checkbox-text {
  font-size: 15px;
  font-weight: 600;
  color: var(--main-text);
}

.format-options {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.format-option {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  padding: 16px;
  border-radius: 12px;
  border: 2px solid transparent;
  background: rgba(160, 145, 124, 0.08);
  cursor: pointer;
  transition: all 0.2s ease;
}

.format-option:hover {
  background: rgba(160, 145, 124, 0.15);
  border-color: rgba(160, 145, 124, 0.3);
}

.format-option input[type="radio"] {
  margin-top: 2px;
  cursor: pointer;
}

.format-option input[type="radio"]:checked + .format-info {
  color: var(--main-primary);
}

.format-option:has(input[type="radio"]:checked) {
  border-color: var(--main-primary);
  background: rgba(160, 145, 124, 0.2);
}

.format-info {
  display: flex;
  flex-direction: column;
  gap: 4px;
  flex: 1;
}

.format-name {
  font-weight: 600;
  font-size: 15px;
  color: var(--main-text);
}

.dialog-footer {
  padding: 20px 24px;
  border-top: 1px solid rgba(160, 145, 124, 0.2);
  display: flex;
  gap: 12px;
  justify-content: flex-end;
}
</style>
