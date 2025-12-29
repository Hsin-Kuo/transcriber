<template>
  <div class="subtitle-table-wrapper" tabindex="-1">
    <table class="subtitle-table">
      <thead>
        <tr>
          <th class="col-time" :class="{ 'time-start': timeFormat === 'start', 'time-range': timeFormat === 'range' }">時間</th>
          <th v-if="hasSpeakerInfo" class="col-speaker">講者</th>
          <th class="col-content">
            <div class="content-header">
              <span>內容</span>
              <div class="settings-container" ref="settingsContainerRef">
                <button
                  @click.stop="toggleSettings"
                  class="settings-btn"
                  :class="{ active: showSettings }"
                  title="顯示/隱藏設置"
                >
                  <svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor">
                    <circle cx="8" cy="3" r="1.5"/>
                    <circle cx="8" cy="8" r="1.5"/>
                    <circle cx="8" cy="13" r="1.5"/>
                  </svg>
                </button>

                <!-- 浮動設置面板 -->
                <div v-if="showSettings" class="settings-panel">
                  <!-- 時間格式切換 -->
                  <div class="setting-group">
                    <label class="setting-label">時間格式</label>
                    <div class="time-format-toggle">
                      <button
                        @click="$emit('update:timeFormat', 'start')"
                        :class="{ active: timeFormat === 'start' }"
                        class="format-btn"
                      >起始時間</button>
                      <button
                        @click="$emit('update:timeFormat', 'range')"
                        :class="{ active: timeFormat === 'range' }"
                        class="format-btn"
                      >時間範圍</button>
                    </div>
                  </div>

                  <!-- 疏密度滑桿 -->
                  <div class="setting-group">
                    <label class="setting-label">內容疏密度</label>
                    <input
                      type="range"
                      :value="densityThreshold"
                      @input="$emit('update:densityThreshold', Number($event.target.value))"
                      min="0.0"
                      max="120.0"
                      step="1.0"
                      class="density-slider"
                    />
                    <div class="slider-labels">
                      <span>疏鬆</span>
                      <span>密集</span>
                    </div>
                  </div>

                  <!-- 講者名稱設定 -->
                  <div v-if="hasSpeakerInfo && uniqueSpeakers.length > 0" class="setting-group">
                    <label class="setting-label">講者名稱</label>
                    <div class="speaker-mappings">
                      <div
                        v-for="speaker in uniqueSpeakers"
                        :key="speaker"
                        class="speaker-item"
                      >
                        <label class="speaker-code">{{ speaker }}</label>
                        <input
                          type="text"
                          :value="speakerNames[speaker] || ''"
                          @input="updateSpeakerName(speaker, $event.target.value)"
                          :placeholder="`講者 ${speaker.replace('SPEAKER_', '')}`"
                          class="speaker-input"
                        />
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </th>
        </tr>
      </thead>
      <tbody>
        <tr
          v-for="group in groupedSegments"
          :key="`${densityThreshold}-${group.id}`"
          class="subtitle-row"
        >
          <td
            class="col-time"
            :class="{
              'time-start': timeFormat === 'start',
              'time-range': timeFormat === 'range',
              'clickable': hasAudio
            }"
            @click="hasAudio && $emit('seek-to-time', group.startTime)"
            :title="hasAudio ? '點擊跳轉到此時間' : ''"
          >
            {{ formatTimestamp(group.startTime, timeFormat, group.endTime) }}
          </td>

          <td v-if="hasSpeakerInfo" class="col-speaker">
            <span class="speaker-badge">
              {{ getSpeakerDisplayName(group.speaker) }}
            </span>
          </td>

          <td
            class="col-content"
            :contenteditable="isEditing"
            @blur="$emit('update-row-content', group.id, $event)"
          >
            <span
              v-for="(segment, idx) in group.segments"
              :key="idx"
              :data-segment-index="idx"
              class="segment-span"
            >{{ segment.text }}</span>
          </td>
        </tr>
      </tbody>
    </table>
  </div>
</template>

<script setup>
import { ref, computed, onUnmounted, nextTick } from 'vue'

const showSettings = ref(false)
const settingsContainerRef = ref(null)

const props = defineProps({
  groupedSegments: {
    type: Array,
    required: true
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
    required: true
  },
  hasAudio: {
    type: Boolean,
    default: false
  },
  isEditing: {
    type: Boolean,
    default: false
  },
  formatTimestamp: {
    type: Function,
    required: true
  },
  speakerNames: {
    type: Object,
    default: () => ({})
  }
})

const emit = defineEmits(['seek-to-time', 'update-row-content', 'update:timeFormat', 'update:densityThreshold', 'update:speakerNames'])

// 獲取所有唯一的講者代號
const uniqueSpeakers = computed(() => {
  const speakers = new Set()
  props.groupedSegments.forEach(group => {
    if (group.speaker && group.speaker.startsWith('SPEAKER_')) {
      speakers.add(group.speaker)
    }
  })
  return Array.from(speakers).sort()
})

// 更新講者名稱
function updateSpeakerName(speakerCode, name) {
  const updated = { ...props.speakerNames, [speakerCode]: name }
  emit('update:speakerNames', updated)
}

// 獲取講者顯示名稱
function getSpeakerDisplayName(speakerCode) {
  if (!speakerCode) return '-'
  // 如果有自定義名稱，使用自定義名稱
  if (props.speakerNames[speakerCode]) {
    return props.speakerNames[speakerCode]
  }
  // 否則返回原始代號
  return speakerCode
}

// 點擊外部關閉面板
function handleClickOutside(event) {
  if (settingsContainerRef.value && !settingsContainerRef.value.contains(event.target)) {
    showSettings.value = false
  }
}

// 切換設置面板
function toggleSettings() {
  showSettings.value = !showSettings.value

  if (showSettings.value) {
    // 打開時，下一個 tick 添加全局監聽器
    nextTick(() => {
      document.addEventListener('click', handleClickOutside)
    })
  } else {
    // 關閉時，移除監聽器
    document.removeEventListener('click', handleClickOutside)
  }
}

// 組件卸載時清理監聽器
onUnmounted(() => {
  document.removeEventListener('click', handleClickOutside)
})
</script>

<style scoped>
/* 設置容器 */
.settings-container {
  position: relative;
}

/* 浮動設置面板 */
.settings-panel {
  position: absolute;
  top: calc(100% + 8px);
  right: 0;
  min-width: 280px;
  background: var(--neu-bg);
  border-radius: 8px;
  padding: 16px;
  border: 1px solid rgba(163, 177, 198, 0.2);
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.15);
  z-index: 1000;
  animation: slideDown 0.2s ease;
}

@keyframes slideDown {
  from {
    opacity: 0;
    transform: translateY(-10px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

.setting-group {
  margin-bottom: 16px;
}

.setting-group:last-child {
  margin-bottom: 0;
}

.setting-label {
  display: block;
  font-size: 11px;
  font-weight: 600;
  color: var(--neu-text-light);
  text-transform: uppercase;
  letter-spacing: 0.5px;
  margin-bottom: 8px;
}

/* 時間格式切換 */
.time-format-toggle {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 6px;
}

.format-btn {
  padding: 8px 12px;
  border: none;
  border-radius: 6px;
  background: var(--neu-bg);
  color: var(--neu-text-light);
  font-size: 12px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s ease;
}

.format-btn.active {
  color: var(--neu-primary);
  background: rgba(255, 145, 77, 0.1);
}

.format-btn:hover {
  transform: translateY(-1px);
}

/* 疏密度滑桿 */
.density-slider {
  width: 100%;
  height: 6px;
  -webkit-appearance: none;
  appearance: none;
  background: rgba(163, 177, 198, 0.25);
  border-radius: 3px;
  outline: none;
  cursor: pointer;
}

.density-slider::-webkit-slider-thumb {
  -webkit-appearance: none;
  appearance: none;
  width: 16px;
  height: 16px;
  background: var(--neu-primary);
  border-radius: 50%;
  cursor: pointer;
  box-shadow: 0 2px 4px rgba(0, 0, 0, 0.2);
}

.density-slider::-moz-range-thumb {
  width: 16px;
  height: 16px;
  background: var(--neu-primary);
  border-radius: 50%;
  cursor: pointer;
  border: none;
  box-shadow: 0 2px 4px rgba(0, 0, 0, 0.2);
}

.slider-labels {
  display: flex;
  justify-content: space-between;
  font-size: 10px;
  color: var(--neu-text-light);
  margin-top: 4px;
}

/* 講者名稱設定 */
.speaker-mappings {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.speaker-item {
  display: grid;
  grid-template-columns: 100px 1fr;
  gap: 8px;
  align-items: center;
}

.speaker-code {
  font-size: 11px;
  font-weight: 600;
  color: var(--neu-text-light);
  font-family: 'Courier New', monospace;
}

.speaker-input {
  width: 100%;
  padding: 6px 10px;
  border: 1px solid rgba(163, 177, 198, 0.2);
  border-radius: 4px;
  background: var(--neu-bg);
  color: var(--neu-text);
  font-size: 12px;
  outline: none;
  transition: all 0.2s ease;
}

.speaker-input:focus {
  border-color: var(--neu-primary);
  background: var(--upload-bg);
}

.speaker-input::placeholder {
  color: var(--neu-text-light);
  opacity: 0.5;
}

/* 字幕表格容器 */
.subtitle-table-wrapper {
  width: 100%;
  height: 100%;
  display: flex;
  flex-direction: column;
  overflow-y: auto !important;
  overflow-x: hidden;
  border-radius: 12px;
  background: var(--neu-bg);
  padding: 12px;
  flex: 1;
  position: relative;
  -webkit-overflow-scrolling: touch;
  scroll-behavior: smooth;
  will-change: scroll-position;
}

.subtitle-table-wrapper:focus {
  outline: none;
}

/* 確保表格容器可以滾動 */
.subtitle-table-wrapper::-webkit-scrollbar {
  width: 8px;
}

.subtitle-table-wrapper::-webkit-scrollbar-track {
  background: rgba(163, 177, 198, 0.1);
  border-radius: 4px;
}

.subtitle-table-wrapper::-webkit-scrollbar-thumb {
  background: rgba(163, 177, 198, 0.3);
  border-radius: 4px;
}

.subtitle-table-wrapper::-webkit-scrollbar-thumb:hover {
  background: rgba(163, 177, 198, 0.5);
}

.subtitle-table {
  width: 100%;
  border-collapse: separate;
  border-spacing: 0 8px;
}

.subtitle-table thead th {
  position: sticky;
  top: -12px;
  background: var(--neu-bg);
  padding: 12px;
  text-align: left;
  font-size: 11px;
  font-weight: 700;
  color: var(--neu-text-light);
  text-transform: uppercase;
  letter-spacing: 0.5px;
  z-index: 10;
  border-bottom: 2px solid rgba(163, 177, 198, 0.2);
  box-shadow: 0 2px 4px rgba(0, 0, 0, 0.05);
}

.subtitle-table thead th:first-child {
  padding-left: 24px;
  margin-left: -12px;
}

.subtitle-table thead th:last-child {
  padding-right: 24px;
  margin-right: -12px;
}

/* 內容標題區 */
.content-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.settings-btn {
  width: 24px;
  height: 24px;
  border: none;
  background: transparent;
  border-radius: 6px;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--neu-text-light);
  transition: all 0.2s ease;
  flex-shrink: 0;
}

.settings-btn:hover {
  color: var(--neu-primary);
  background: rgba(255, 145, 77, 0.1);
}

.settings-btn.active {
  color: var(--neu-primary);
  background: rgba(255, 145, 77, 0.15);
}

.subtitle-table thead {
  position: relative;
  z-index: 10;
}

.subtitle-table tbody {
  position: relative;
  z-index: 1;
}

.subtitle-row {
  background: var(--neu-bg);
  transition: all 0.2s ease;
  position: relative;
  z-index: 1;
}

.subtitle-row:hover {
  background: rgba(163, 177, 198, 0.05);
}

/* 時間欄 */
.col-time {
  width: 120px;
  padding: 12px;
  text-align: right;
  font-family: 'Courier New', monospace;
  font-size: 13px;
  color: var(--neu-text-light);
  white-space: nowrap;
  vertical-align: top;
  transition: width 0.3s ease;
}

/* 時間格式：起始時間（較窄） */
.col-time.time-start {
  width: 80px;
}

/* 時間格式：時間範圍（較寬） */
.col-time.time-range {
  width: 140px;
}

/* 可點擊的時間欄（有音檔時） */
.col-time.clickable {
  cursor: pointer;
  transition: all 0.2s ease;
  border-radius: 6px;
}

.col-time.clickable:hover {
  background: rgba(255, 145, 77, 0.1);
  color: var(--neu-primary);
  transform: translateX(-2px);
}

.col-time.clickable:active {
  background: rgba(255, 145, 77, 0.2);
  transform: translateX(-1px);
}

/* 講者欄 */
.col-speaker {
  width: 100px;
  padding: 12px;
  text-align: center;
  vertical-align: top;
}

.speaker-badge {
  display: inline-block;
  padding: 4px 10px;
  background: var(--neu-bg);
  border-radius: 8px;
  font-size: 11px;
  font-weight: 600;
  color: var(--neu-primary);
}

/* 內容欄 */
.col-content {
  padding: 12px;
  font-size: 15px;
  line-height: 1.6;
  color: var(--neu-text);
  min-height: 48px;
  vertical-align: top;
}

.col-content[contenteditable="true"] {
  outline: 2px solid transparent;
  border-radius: 6px;
  transition: all 0.2s ease;
  cursor: text;
  user-select: text;
  -webkit-user-select: text;
  overflow: visible;
  touch-action: pan-y;
  background: var(--upload-bg);
}

.col-content[contenteditable="true"]:focus {
  outline: 2px solid var(--neu-primary);
  background: var(--upload-bg);
}

/* Segment span 樣式 */
.segment-span {
  display: inline;
}

.segment-span:not(:last-child)::after {
  content: ' ';
  white-space: pre;
}

/* 響應式設計 - 字幕模式 */
@media (max-width: 768px) {
  .subtitle-table .col-speaker {
    display: none;
  }

  .subtitle-table .col-time {
    width: 90px;
    font-size: 11px;
  }

  .subtitle-table {
    font-size: 14px;
  }

  .subtitle-table .col-content {
    font-size: 14px;
  }
}
</style>
