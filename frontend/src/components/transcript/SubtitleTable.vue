<template>
  <div class="subtitle-table-wrapper" tabindex="-1">
    <table class="subtitle-table">
      <thead>
        <tr>
          <th class="col-time" :class="{ 'time-start': timeFormat === 'start', 'time-range': timeFormat === 'range' }">時間</th>
          <th v-if="hasSpeakerInfo" class="col-speaker">講者</th>
          <th class="col-content">內容</th>
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
            <span class="speaker-badge">{{ group.speaker || '-' }}</span>
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
defineProps({
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
  }
})

defineEmits(['seek-to-time', 'update-row-content'])
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
