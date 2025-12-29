<template>
  <div v-if="show" class="download-dialog-overlay" @click.self="$emit('close')">
    <div class="download-dialog">
      <div class="dialog-header">
        <h3>選擇下載格式</h3>
        <button @click="$emit('close')" class="btn-close" title="關閉">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <line x1="18" y1="6" x2="6" y2="18"></line>
            <line x1="6" y1="6" x2="18" y2="18"></line>
          </svg>
        </button>
      </div>

      <div class="dialog-body">
        <p class="dialog-description">
          將根據目前的設定生成字幕檔案：
        </p>
        <ul class="current-settings">
          <li><strong>時間格式：</strong>{{ timeFormat === 'start' ? '起始時間' : '時間範圍' }}</li>
          <li><strong>疏密度：</strong>{{ densityThreshold.toFixed(1) }}s</li>
        </ul>

        <!-- 講者資訊選項 -->
        <div v-if="hasSpeakerInfo" class="speaker-option">
          <label class="checkbox-label">
            <input
              type="checkbox"
              :checked="includeSpeaker"
              @change="$emit('update:includeSpeaker', $event.target.checked)"
              class="checkbox-input"
            />
            <span class="checkbox-text">講者資訊</span>
          </label>
          <p class="option-hint">檔案會包含講者名稱</p>
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
              <span class="format-name">TXT 文字檔</span>
              <span class="format-desc">純文字格式，包含時間戳和內容</span>
            </div>
          </label>

          <label class="format-option">
            <input
              type="radio"
              :value="'srt'"
              :checked="selectedFormat === 'srt'"
              @change="$emit('update:selectedFormat', 'srt')"
              name="downloadFormat"
            />
            <div class="format-info">
              <span class="format-name">SRT 字幕檔</span>
              <span class="format-desc">SubRip 字幕格式，適用於大多數播放器</span>
            </div>
          </label>

          <label class="format-option">
            <input
              type="radio"
              :value="'vtt'"
              :checked="selectedFormat === 'vtt'"
              @change="$emit('update:selectedFormat', 'vtt')"
              name="downloadFormat"
            />
            <div class="format-info">
              <span class="format-name">VTT 字幕檔</span>
              <span class="format-desc">WebVTT 字幕格式，適用於網頁播放器</span>
            </div>
          </label>
        </div>
      </div>

      <div class="dialog-footer">
        <button @click="$emit('close')" class="btn btn-secondary">
          取消
        </button>
        <button @click="$emit('download')" class="btn btn-primary">
          下載
        </button>
      </div>
    </div>
  </div>
</template>

<script setup>
defineProps({
  show: {
    type: Boolean,
    default: false
  },
  timeFormat: {
    type: String,
    required: true
  },
  densityThreshold: {
    type: Number,
    required: true
  },
  hasSpeakerInfo: {
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
  }
})

defineEmits(['close', 'download', 'update:selectedFormat', 'update:includeSpeaker'])
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
  background: var(--neu-bg);
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
  border-bottom: 1px solid rgba(163, 177, 198, 0.2);
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.dialog-header h3 {
  margin: 0;
  font-size: 20px;
  font-weight: 600;
  color: var(--neu-text);
}

.btn-close {
  background: transparent;
  border: none;
  cursor: pointer;
  padding: 8px;
  border-radius: 8px;
  color: var(--neu-text-light);
  transition: all 0.2s ease;
  display: flex;
  align-items: center;
  justify-content: center;
}

.btn-close:hover {
  background: rgba(163, 177, 198, 0.1);
  color: var(--neu-text);
}

.dialog-body {
  padding: 24px;
  overflow-y: auto;
  flex: 1;
}

.dialog-description {
  margin: 0 0 16px 0;
  color: var(--neu-text);
  font-size: 14px;
}

.current-settings {
  background: rgba(163, 177, 198, 0.1);
  border-radius: 8px;
  padding: 16px;
  margin: 0 0 24px 0;
  list-style: none;
}

.current-settings li {
  margin: 8px 0;
  font-size: 14px;
  color: var(--neu-text-light);
}

.current-settings strong {
  color: var(--neu-text);
  font-weight: 600;
}

/* 講者選項 */
.speaker-option {
  background: rgba(163, 177, 198, 0.05);
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
  accent-color: var(--neu-primary);
}

.checkbox-text {
  font-size: 15px;
  font-weight: 600;
  color: var(--neu-text);
}

.option-hint {
  margin: 8px 0 0 28px;
  font-size: 13px;
  color: var(--neu-text-light);
  line-height: 1.4;
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
  background: rgba(163, 177, 198, 0.05);
  cursor: pointer;
  transition: all 0.2s ease;
}

.format-option:hover {
  background: rgba(163, 177, 198, 0.1);
  border-color: rgba(163, 177, 198, 0.2);
}

.format-option input[type="radio"] {
  margin-top: 2px;
  cursor: pointer;
}

.format-option input[type="radio"]:checked + .format-info {
  color: var(--neu-primary);
}

.format-option:has(input[type="radio"]:checked) {
  border-color: var(--neu-primary);
  background: rgba(255, 145, 77, 0.05);
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
  color: var(--neu-text);
}

.format-desc {
  font-size: 13px;
  color: var(--neu-text-light);
}

.dialog-footer {
  padding: 20px 24px;
  border-top: 1px solid rgba(163, 177, 198, 0.2);
  display: flex;
  gap: 12px;
  justify-content: flex-end;
}
</style>
