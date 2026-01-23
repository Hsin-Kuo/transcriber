<template>
  <div class="subtitle-table-wrapper" ref="wrapperRef" tabindex="-1" @scroll="handleWrapperScroll">
    <table class="subtitle-table">
      <thead>
        <tr>
          <th class="col-time" :class="{ 'time-start': timeFormat === 'start', 'time-range': timeFormat === 'range' }">{{ $t('subtitleTable.time') }}</th>
          <th v-if="hasSpeakerInfo" class="col-speaker">{{ $t('subtitleTable.speaker') }}</th>
          <th class="col-content">{{ $t('subtitleTable.content') }}</th>
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
          <span class="speaker-name">{{ getSpeakerDisplayName(speaker) }}</span>
          <button
            v-if="currentEditingGroup?.speaker === speaker"
            class="btn-rename"
            @click.stop="handleRename(speaker)"
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"></path>
              <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"></path>
            </svg>
            <span class="btn-tooltip">{{ $t('subtitleTable.rename') }}</span>
          </button>
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

const emit = defineEmits(['seek-to-time', 'update-row-content', 'update:speakerNames', 'update-segment-speaker', 'open-speaker-settings'])

// 元素引用
const wrapperRef = ref(null)

// 講者選擇浮窗狀態
const showSpeakerPicker = ref(false)
const speakerPickerPosition = ref({ top: 0, left: 0 })
const currentEditingGroup = ref(null)
const newSpeakerName = ref('')
const speakerPickerRef = ref(null)

// 處理 wrapper 滾動事件（關閉講者選擇浮窗）
function handleWrapperScroll() {
  if (showSpeakerPicker.value) {
    closeSpeakerPicker()
  }
}

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

// 處理重新命名講者
function handleRename(speakerCode) {
  closeSpeakerPicker()
  // 通知父組件打開設置面板
  emit('open-speaker-settings', speakerCode)
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
  document.removeEventListener('click', handleSpeakerPickerClickOutside)
})
</script>

<style scoped>
/* 字幕表格容器 */
.subtitle-table-wrapper {
  width: 100%;
  height: 100%;
  display: flex;
  flex-direction: column;
  overflow-y: auto !important;
  overflow-x: hidden;
  border-radius: 12px;
  background: var(--main-bg);
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
  background: var(--main-bg);
  padding: 12px;
  text-align: left;
  font-size: 11px;
  font-weight: 700;
  color: var(--main-text-light);
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

.subtitle-table thead {
  position: relative;
  z-index: 10;
}

.subtitle-table tbody {
  position: relative;
  z-index: 1;
}

.subtitle-row {
  background: var(--main-bg);
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
  color: var(--main-text-light);
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
  color: var(--main-primary);
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
  background: var(--main-bg);
  border-radius: 8px;
  font-size: 11px;
  font-weight: 600;
  color: var(--main-primary);
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
  overflow-x: hidden;
  padding: 8px 0;
}

.speaker-option {
  width: 100%;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 10px 12px;
  background: transparent;
  border: none;
  cursor: pointer;
  transition: all 0.15s ease;
  text-align: left;
  color: var(--main-text);
  min-width: 0;
}

.speaker-option:hover {
  background: rgba(163, 177, 198, 0.08);
}

.speaker-option.current {
  background: var(--main-bg);
  color: var(--main-primary);
}

.speaker-code {
  font-size: 11px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  color: var(--main-text-light);
}

.speaker-option.current .speaker-code {
  color: var(--main-primary);
}

.speaker-option .speaker-name {
  font-size: 13px;
  font-weight: 500;
  flex: 1;
  min-width: 0;
  text-align: left;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* 重新命名按鈕 */
.btn-rename {
  position: relative;
  display: flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  padding: 0;
  border: none;
  border-radius: 4px;
  background: transparent;
  color: var(--main-text-light);
  cursor: pointer;
  transition: all 0.15s ease;
  flex-shrink: 0;
}

.btn-rename:hover {
  background: rgba(255, 145, 77, 0.15);
  color: var(--main-primary);
}

/* 重新命名按鈕 tooltip */
.btn-rename .btn-tooltip {
  position: absolute;
  top: calc(100% + 4px);
  left: 50%;
  transform: translateX(-50%);
  padding: 4px 8px;
  background: rgba(0, 0, 0, 0.85);
  color: white;
  border-radius: 4px;
  font-size: 12px;
  white-space: nowrap;
  opacity: 0;
  visibility: hidden;
  pointer-events: none;
  transition: opacity 0.15s ease, visibility 0.15s ease;
  z-index: 9999;
}

.btn-rename .btn-tooltip::before {
  content: '';
  position: absolute;
  bottom: 100%;
  left: 50%;
  transform: translateX(-50%);
  border: 5px solid transparent;
  border-bottom-color: rgba(0, 0, 0, 0.85);
}

.btn-rename:hover .btn-tooltip {
  opacity: 1;
  visibility: visible;
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
  background: var(--main-bg);
  font-size: 13px;
  color: var(--main-text);
  transition: all 0.2s ease;
}

.speaker-input:focus {
  outline: none;
  border-color: var(--main-primary);
  box-shadow: 0 0 0 2px rgba(255, 145, 77, 0.1);
}

.btn-add-speaker {
  padding: 6px 12px;
  background: var(--main-primary);
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
  color: var(--main-text);
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
  outline: 2px solid var(--main-primary);
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
