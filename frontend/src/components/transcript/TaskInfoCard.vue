<template>
  <div class="task-info-card">
    <!-- 任務資訊區塊 -->
    <div class="info-section">
      <!-- 最後編輯時間 -->
      <div class="info-row has-tooltip">
        <span class="info-label">
          <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"></path>
            <path d="M3 3v5h5"></path>
            <path d="M12 7v5l4 2"></path>
          </svg>
          {{ formattedDate }}
        </span>
        <span class="tooltip-text">{{ $t('taskInfo.lastEdited') }}</span>
      </div>

      <!-- 總字數 -->
      <div class="info-row">
        <span class="info-label">
          <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path>
            <polyline points="14 2 14 8 20 8"></polyline>
            <line x1="16" y1="13" x2="8" y2="13"></line>
            <line x1="16" y1="17" x2="8" y2="17"></line>
            <polyline points="10 9 9 9 8 9"></polyline>
          </svg>
          {{ formattedWordCount }}
        </span>
      </div>
    </div>

    <!-- 標籤區塊 -->
    <div class="tags-section">
      <span class="tags-icon" :title="$t('taskInfo.tags')">
        <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <path d="M20.59 13.41l-7.17 7.17a2 2 0 0 1-2.83 0L2 12V2h10l8.59 8.59a2 2 0 0 1 0 2.82z"></path>
          <line x1="7" y1="7" x2="7.01" y2="7"></line>
        </svg>
      </span>
      <TaskTagsSection
        :task-id="taskId"
        :tags="tags"
        :all-tags="allTags"
        @tags-updated="handleTagsUpdated"
      />
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import TaskTagsSection from '../task/TaskTagsSection.vue'

const { t: $t, locale } = useI18n()

// Props
const props = defineProps({
  taskId: {
    type: String,
    default: ''
  },
  updatedAt: {
    type: [String, Number],
    default: null
  },
  content: {
    type: String,
    default: ''
  },
  tags: {
    type: Array,
    default: () => []
  },
  allTags: {
    type: Array,
    default: () => []
  }
})

// Emits
const emit = defineEmits(['tags-updated'])

// Computed
const formattedDate = computed(() => {
  if (!props.updatedAt) return '-'

  try {
    // 處理 Unix timestamp (秒) 或 ISO 字串
    let date
    if (typeof props.updatedAt === 'number') {
      date = new Date(props.updatedAt * 1000)
    } else {
      date = new Date(props.updatedAt)
    }

    if (isNaN(date.getTime())) return String(props.updatedAt)

    const localeCode = locale.value === 'zh-TW' ? 'zh-TW' : 'en-US'

    const datePart = date.toLocaleDateString(localeCode, {
      year: 'numeric',
      month: '2-digit',
      day: '2-digit'
    })

    const timePart = date.toLocaleTimeString(localeCode, {
      hour: '2-digit',
      minute: '2-digit'
    })

    return `${datePart} ${timePart}`
  } catch {
    return String(props.updatedAt)
  }
})

// 計算字詞數
const wordCount = computed(() => {
  if (!props.content) return 0

  const text = props.content.trim()
  if (!text) return 0

  // 中日韓字符的正則（CJK Unified Ideographs）
  const cjkRegex = /[\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff\u3040-\u309f\u30a0-\u30ff\uac00-\ud7af]/g

  // 計算 CJK 字符數
  const cjkMatches = text.match(cjkRegex)
  const cjkCount = cjkMatches ? cjkMatches.length : 0

  // 移除 CJK 字符後，計算英文單詞數
  const nonCjkText = text.replace(cjkRegex, ' ')
  const words = nonCjkText.split(/\s+/).filter(word => word.length > 0 && /[a-zA-Z0-9]/.test(word))
  const englishWordCount = words.length

  return cjkCount + englishWordCount
})

const formattedWordCount = computed(() => {
  if (!props.content) return '-'
  return `${wordCount.value.toLocaleString()} ${$t('taskInfo.words')}`
})

// Methods
function handleTagsUpdated(data) {
  emit('tags-updated', data)
}
</script>

<style scoped>
.task-info-card {
  display: flex;
  flex-direction: column;
  gap: 16px;
  padding: 16px;
  border-radius: 12px;
}

.info-section {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.info-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
}

.info-label {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  color: var(--main-text-light);
}

.info-label svg {
  opacity: 0.7;
  flex-shrink: 0;
}

.info-value {
  font-size: 13px;
  font-weight: 500;
  color: var(--main-text);
  text-align: right;
}

.tags-section {
  display: flex;
  flex-direction: row;
  align-items: center;
  gap: 8px;
  padding-top: 12px;
  border-top: 1px solid rgba(0, 0, 0, 0.06);
}

.tags-icon {
  display: flex;
  align-items: center;
  color: var(--main-text-light);
  flex-shrink: 0;
}

.tags-icon svg {
  opacity: 0.7;
}

/* Tooltip 效果 */
.info-row.has-tooltip {
  position: relative;
  cursor: default;
}

.tooltip-text {
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
  z-index: 100;
}

.tooltip-text::before {
  content: '';
  position: absolute;
  bottom: 100%;
  left: 50%;
  transform: translateX(-50%);
  border: 5px solid transparent;
  border-bottom-color: rgba(0, 0, 0, 0.85);
}

.info-row.has-tooltip:hover .tooltip-text {
  opacity: 1;
  visibility: visible;
}
</style>
