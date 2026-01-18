<template>
  <div class="subtitle-table-wrapper" tabindex="-1">
    <table class="subtitle-table">
      <thead>
        <tr>
          <th class="col-time" :class="{ 'time-start': timeFormat === 'start', 'time-range': timeFormat === 'range' }">{{ $t('subtitleTable.time') }}</th>
          <th v-if="hasSpeakerInfo" class="col-speaker">{{ $t('subtitleTable.speaker') }}</th>
          <th class="col-content">
            <div class="content-header">
              <span>{{ $t('subtitleTable.content') }}</span>
              <div class="settings-container" ref="settingsContainerRef">
                <button
                  @click.stop="toggleSettings"
                  class="settings-btn"
                  :class="{ active: showSettings }"
                  :title="$t('subtitleTable.toggleSettings')"
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
                    <label class="setting-label">{{ $t('subtitleTable.timeFormat') }}</label>
                    <div class="time-format-toggle">
                      <button
                        @click="$emit('update:timeFormat', 'start')"
                        :class="{ active: timeFormat === 'start' }"
                        class="format-btn"
                      >{{ $t('subtitleTable.startTime') }}</button>
                      <button
                        @click="$emit('update:timeFormat', 'range')"
                        :class="{ active: timeFormat === 'range' }"
                        class="format-btn"
                      >{{ $t('subtitleTable.timeRange') }}</button>
                    </div>
                  </div>

                  <!-- 疏密度滑桿 -->
                  <div class="setting-group">
                    <label class="setting-label">{{ $t('subtitleTable.contentDensity') }}</label>
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
                      <span>{{ $t('subtitleTable.sparse') }}</span>
                      <span>{{ $t('subtitleTable.dense') }}</span>
                    </div>
                  </div>

                  <!-- 講者名稱設定 -->
                  <div v-if="hasSpeakerInfo && uniqueSpeakers.length > 0" class="setting-group">
                    <label class="setting-label">{{ $t('subtitleTable.speakerNames') }}</label>
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
                          :placeholder="$t('subtitleTable.speakerPlaceholder', { number: speaker.replace('SPEAKER_', '') })"
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
            :title="hasAudio ? $t('subtitleTable.clickToJumpToTime') : ''"
          >
            {{ formatTimestamp(group.startTime, timeFormat, group.endTime) }}
          </td>

          <td v-if="hasSpeakerInfo" class="col-speaker">
            <span
              class="speaker-badge"
              :class="{ 'clickable': !isEditing }"
              @click="!isEditing && openSpeakerPicker(group, $event)"
              :title="!isEditing ? $t('subtitleTable.clickToChangeSpeaker') : ''"
            >
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

    <!-- 講者選擇浮窗 -->
    <div
      v-if="showSpeakerPicker"
      ref="speakerPickerRef"
      class="speaker-picker"
      :style="{
        top: speakerPickerPosition.top + 'px',
        left: speakerPickerPosition.left + 'px'
      }"
      @click.stop
    >

      <!-- 現有講者列表 -->
      <div class="speaker-list">
        <button
          v-for="speaker in uniqueSpeakers"
          :key="speaker"
          class="speaker-option"
          :class="{ 'current': currentEditingGroup?.speaker === speaker }"
          @click="selectSpeaker(speaker)"
        >
          {{ getSpeakerDisplayName(speaker) }}
        </button>
      </div>

      <!-- 新增講者 -->
      <div class="speaker-new">
        <input
          v-model="newSpeakerName"
          type="text"
          :placeholder="$t('subtitleTable.newSpeaker')"
          class="speaker-input"
          @keyup.enter="addNewSpeaker"
        />
        <button
          class="btn-add-speaker"
          @click="addNewSpeaker"
          :disabled="!newSpeakerName.trim()"
        >
          {{ $t('subtitleTable.add') }}
        </button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onUnmounted, nextTick } from 'vue'
import { useI18n } from 'vue-i18n'

const { t: $t } = useI18n()

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

const emit = defineEmits(['seek-to-time', 'update-row-content', 'update:timeFormat', 'update:densityThreshold', 'update:speakerNames', 'update-segment-speaker'])

// 講者選擇浮窗狀態
const showSpeakerPicker = ref(false)
const speakerPickerPosition = ref({ top: 0, left: 0 })
const currentEditingGroup = ref(null)
const newSpeakerName = ref('')
const speakerPickerRef = ref(null)

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

// 開啟講者選擇浮窗
function openSpeakerPicker(group, event) {
  event.stopPropagation()

  currentEditingGroup.value = group
  newSpeakerName.value = ''

  // 計算浮窗位置（相對於點擊的 badge）
  const rect = event.target.getBoundingClientRect()
  speakerPickerPosition.value = {
    top: rect.bottom + 5,
    left: rect.left
  }

  showSpeakerPicker.value = true

  // 下一個 tick 添加點擊外部關閉的監聽器
  nextTick(() => {
    document.addEventListener('click', handleSpeakerPickerClickOutside)
  })
}

// 關閉講者選擇浮窗
function closeSpeakerPicker() {
  showSpeakerPicker.value = false
  currentEditingGroup.value = null
  newSpeakerName.value = ''
  document.removeEventListener('click', handleSpeakerPickerClickOutside)
}

// 點擊外部關閉講者選擇浮窗
function handleSpeakerPickerClickOutside(event) {
  if (speakerPickerRef.value && !speakerPickerRef.value.contains(event.target)) {
    closeSpeakerPicker()
  }
}

// 選擇現有講者
function selectSpeaker(speakerCode) {
  if (!currentEditingGroup.value) return

  // 更新該 group 中所有 segments 的 speaker
  emit('update-segment-speaker', {
    groupId: currentEditingGroup.value.id,
    newSpeaker: speakerCode
  })

  closeSpeakerPicker()
}

// 新增講者並設定名稱
function addNewSpeaker() {
  const name = newSpeakerName.value.trim()
  if (!name) return

  // 計算新的講者代號
  const existingSpeakers = uniqueSpeakers.value
  const maxNumber = existingSpeakers.reduce((max, speaker) => {
    const match = speaker.match(/SPEAKER_(\d+)/)
    return match ? Math.max(max, parseInt(match[1])) : max
  }, -1)

  const newSpeakerCode = `SPEAKER_${String(maxNumber + 1).padStart(2, '0')}`

  // 更新講者名稱對應
  const updatedNames = { ...props.speakerNames, [newSpeakerCode]: name }
  emit('update:speakerNames', updatedNames)

  // 更新該 group 的 speaker
  emit('update-segment-speaker', {
    groupId: currentEditingGroup.value.id,
    newSpeaker: newSpeakerCode
  })

  closeSpeakerPicker()
}

// 組件卸載時清理監聽器
onUnmounted(() => {
  document.removeEventListener('click', handleClickOutside)
  document.removeEventListener('click', handleSpeakerPickerClickOutside)
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
  background: var(--upload-bg);
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
  background: var(--upload-bg);
  color: var(--neu-text-light);
  font-size: 12px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s ease;
}

.format-btn.active {
  color: var(--neu-primary);
  background: var(--neu-bg);
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
  transition: all 0.2s ease;
}

.speaker-badge.clickable {
  cursor: pointer;
  user-select: none;
}

.speaker-badge.clickable:hover {
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
  transform: translateY(-1px);
  background: rgba(255, 145, 77, 0.1);
}

/* 講者選擇浮窗 */
.speaker-picker {
  position: fixed;
  background: var(--upload-bg);
  border-radius: 8px;
  box-shadow: 0 4px 20px rgba(0, 0, 0, 0.15);
  border: 1px solid rgba(0, 0, 0, 0.08);
  padding: 0;
  min-width: 160px;
  max-width: 200px;
  z-index: 1000;
  overflow: hidden;
  animation: fadeInScale 0.2s ease;
}

@keyframes fadeInScale {
  from {
    opacity: 0;
    transform: scale(0.95);
  }
  to {
    opacity: 1;
    transform: scale(1);
  }
}

.speaker-list {
  max-height: 240px;
  overflow-y: auto;
  padding: 8px 0;
}

.speaker-option {
  width: 100%;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 10px 16px;
  background: transparent;
  border: none;
  cursor: pointer;
  transition: all 0.15s ease;
  text-align: left;
  color: var(--neu-text);
}

.speaker-option:hover {
  background: rgba(163, 177, 198, 0.08);
}

.speaker-option.current {
  background: var(--neu-bg);
  color: var(--neu-primary);
}

.speaker-code {
  font-size: 11px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  color: var(--neu-text-light);
}

.speaker-option.current .speaker-code {
  color: var(--neu-primary);
}

.speaker-name {
  font-size: 13px;
  font-weight: 500;
  flex: 1;
  text-align: right;
}

.speaker-new {
  padding: 12px;
  border-top: 1px solid rgba(163, 177, 198, 0.15);
  background: rgba(163, 177, 198, 0.03);
  display: flex;
  gap: 8px;
}

.speaker-input {
  flex: 1;
  padding: 6px 10px;
  border: 1px solid rgba(163, 177, 198, 0.2);
  border-radius: 6px;
  background: var(--neu-bg);
  font-size: 13px;
  color: var(--neu-text);
  transition: all 0.2s ease;
}

.speaker-input:focus {
  outline: none;
  border-color: var(--neu-primary);
  box-shadow: 0 0 0 2px rgba(255, 145, 77, 0.1);
}

.btn-add-speaker {
  padding: 6px 12px;
  background: var(--neu-primary);
  color: white;
  border: none;
  border-radius: 6px;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s ease;
  white-space: nowrap;
}

.btn-add-speaker:hover:not(:disabled) {
  background: var(--color-orange);
  transform: translateY(-1px);
  box-shadow: 0 2px 8px rgba(255, 145, 77, 0.3);
}

.btn-add-speaker:disabled {
  opacity: 0.5;
  cursor: not-allowed;
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
