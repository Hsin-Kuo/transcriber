<template>
  <div class="metadata-section" :class="{ 'horizontal': layout === 'horizontal' }">
    <div v-if="createdAt" class="meta-item">
      <svg v-if="showDateIcon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <rect x="3" y="4" width="18" height="18" rx="2" ry="2"></rect>
        <line x1="16" y1="2" x2="16" y2="6"></line>
        <line x1="8" y1="2" x2="8" y2="6"></line>
        <line x1="3" y1="10" x2="21" y2="10"></line>
      </svg>
      {{ formatDate(createdAt) }}
    </div>
    <div v-if="textLength" class="meta-item">
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path>
        <polyline points="14 2 14 8 20 8"></polyline>
      </svg>
      {{ textLength }} {{ $t('transcriptMetadata.characters') }}
    </div>
    <div v-if="durationText" class="meta-item">
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <circle cx="12" cy="12" r="10"></circle>
        <polyline points="12 6 12 12 16 14"></polyline>
      </svg>
      {{ durationText }}
    </div>
  </div>
</template>

<script setup>
import { useI18n } from 'vue-i18n'

const { locale } = useI18n()

defineProps({
  createdAt: [String, Number],
  textLength: Number,
  durationText: String,
  layout: {
    type: String,
    default: 'vertical'
  },
  showDateIcon: {
    type: Boolean,
    default: true
  }
})

function formatDate(dateValue) {
  if (!dateValue) return ''
  try {
    // 處理 Unix timestamp (秒) 或 ISO 字串
    let date
    if (typeof dateValue === 'number') {
      date = new Date(dateValue * 1000)
    } else {
      date = new Date(dateValue)
    }

    if (isNaN(date.getTime())) return String(dateValue)

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
    return String(dateValue)
  }
}
</script>

<style scoped>
/* Metadata area */
.metadata-section {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 12px;
  background: var(--main-bg);
  border-radius: 12px;
}

.meta-item {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  color: var(--main-text);
}

.meta-item svg {
  stroke: var(--main-primary);
  flex-shrink: 0;
}

/* 水平佈局 */
.metadata-section.horizontal {
  flex-direction: row;
  background: transparent;
  padding: 0;
  gap: 16px;
}

.metadata-section.horizontal .meta-item {
  font-size: 12px;
  white-space: nowrap;
}
</style>
