<template>
  <div class="ai-summary-card">
    <!-- 標題列（可點擊展開/收起） -->
    <div class="summary-header" @click="toggleExpanded">
      <div class="header-left">
        <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <path d="M12 3c.132 0 .263 0 .393 0a7.5 7.5 0 0 0 7.92 12.446a9 9 0 1 1 -8.313 -12.454z" />
          <path d="M17 4a2 2 0 0 0 2 2a2 2 0 0 0 -2 2a2 2 0 0 0 -2 -2a2 2 0 0 0 2 -2" />
          <path d="M19 11h2m-1 -1v2" />
        </svg>
        <span class="header-title">{{ $t('aiSummary.title') }}</span>
      </div>
      <div class="header-right">
        <!-- 狀態標籤 -->
        <span v-if="summaryStatus === 'processing'" class="status-badge processing">
          {{ $t('aiSummary.processing') }}
        </span>
        <span v-else-if="summaryStatus === 'completed'" class="status-badge completed">
          {{ $t('aiSummary.completed') }}
        </span>
        <!-- 展開/收起圖示 -->
        <svg
          class="expand-icon"
          :class="{ expanded: isExpanded }"
          xmlns="http://www.w3.org/2000/svg"
          width="16"
          height="16"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          stroke-width="2"
          stroke-linecap="round"
          stroke-linejoin="round"
        >
          <polyline points="6 9 12 15 18 9"></polyline>
        </svg>
      </div>
    </div>

    <!-- 展開內容 -->
    <div v-show="isExpanded" class="summary-content">
      <!-- 載入中狀態 -->
      <div v-if="isLoading" class="loading-state">
        <div class="spinner"></div>
        <span>{{ $t('aiSummary.generating') }}</span>
      </div>

      <!-- 錯誤狀態 -->
      <div v-else-if="error" class="error-state">
        <span class="error-message">{{ error }}</span>
        <button class="retry-btn" @click="generateSummary">
          {{ $t('aiSummary.retry') }}
        </button>
      </div>

      <!-- 已有摘要 -->
      <div v-else-if="summary" class="summary-display">
        <!-- 複製按鈕 -->
        <button class="copy-btn" :class="{ copied: isCopied }" @click="copySummaryText" :title="isCopied ? $t('aiSummary.copied') : $t('aiSummary.copySummary')">
          <svg v-if="!isCopied" xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <rect x="8" y="8" width="12" height="12" rx="2" ry="2"></rect>
            <path d="M16 8V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h2"></path>
          </svg>
          <svg v-else xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <polyline points="20 6 9 17 4 12"></polyline>
          </svg>
        </button>

        <!-- Meta 資訊區塊 -->
        <div v-if="summary.content.meta" class="meta-section">
          <div class="meta-badges">
            <span class="type-badge" :class="getTypeClass(summary.content.meta.type)">
              {{ getTypeLabel(summary.content.meta.type) }}
            </span>
            <span class="sentiment-badge" :class="getSentimentClass(summary.content.meta.sentiment)">
              {{ getSentimentLabel(summary.content.meta.sentiment) }}
            </span>
          </div>
          <h3 v-if="summary.content.meta.detected_topic" class="detected-topic">
            {{ summary.content.meta.detected_topic }}
          </h3>
        </div>

        <!-- 執行摘要 -->
        <div v-if="summary.content.summary" class="section summary-section">
          <h4 class="section-title">{{ $t('aiSummary.executiveSummary') }}</h4>
          <p class="summary-text">{{ summary.content.summary }}</p>
        </div>

        <!-- 重點列表 -->
        <div v-if="keyPoints.length > 0" class="section key-points-section">
          <h4 class="section-title">{{ $t('aiSummary.keyPoints') }}</h4>
          <ul class="key-points-list">
            <li v-for="(point, index) in keyPoints" :key="index">
              {{ point }}
            </li>
          </ul>
        </div>

        <!-- 內容段落 -->
        <div v-if="summary.content.segments && summary.content.segments.length > 0" class="section segments-section">
          <h4 class="section-title">{{ $t('aiSummary.contentSegments') }}</h4>
          <div class="segments-list">
            <div v-for="(segment, index) in summary.content.segments" :key="index" class="segment-item">
              <h5 class="segment-topic">{{ segment.topic }}</h5>
              <p class="segment-content">{{ segment.content }}</p>
              <div v-if="segment.keywords && segment.keywords.length > 0" class="segment-keywords">
                <span v-for="(keyword, kIndex) in segment.keywords" :key="kIndex" class="keyword-tag">
                  {{ keyword }}
                </span>
              </div>
            </div>
          </div>
        </div>

        <!-- 待辦事項（僅會議顯示） -->
        <div v-if="summary.content.action_items && summary.content.action_items.length > 0" class="section action-items-section">
          <h4 class="section-title">{{ $t('aiSummary.actionItems') }}</h4>
          <div class="action-items-list">
            <div v-for="(item, index) in summary.content.action_items" :key="index" class="action-item">
              <div class="action-task">
                <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                  <path d="M9 11l3 3l8 -8"></path>
                  <path d="M20 12v6a2 2 0 0 1 -2 2h-12a2 2 0 0 1 -2 -2v-12a2 2 0 0 1 2 -2h9"></path>
                </svg>
                <span>{{ item.task }}</span>
              </div>
              <div class="action-meta">
                <span v-if="item.owner" class="action-owner">
                  <svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                    <path d="M12 12m-9 0a9 9 0 1 0 18 0a9 9 0 1 0 -18 0"></path>
                    <path d="M12 10m-3 0a3 3 0 1 0 6 0a3 3 0 1 0 -6 0"></path>
                    <path d="M6.168 18.849a4 4 0 0 1 3.832 -2.849h4a4 4 0 0 1 3.834 2.855"></path>
                  </svg>
                  {{ item.owner }}
                </span>
                <span v-if="item.deadline" class="action-deadline">
                  <svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                    <path d="M4 7a2 2 0 0 1 2 -2h12a2 2 0 0 1 2 2v12a2 2 0 0 1 -2 2h-12a2 2 0 0 1 -2 -2v-12z"></path>
                    <path d="M16 3v4"></path>
                    <path d="M8 3v4"></path>
                    <path d="M4 11h16"></path>
                  </svg>
                  {{ item.deadline }}
                </span>
              </div>
            </div>
          </div>
        </div>

        <!-- 元數據 -->
        <div class="metadata">
          <span class="metadata-item">
            {{ $t('aiSummary.model') }}: {{ summary.metadata.model }}
          </span>
        </div>

        <!-- 重新生成按鈕 -->
        <button class="regenerate-btn" @click="generateSummary" :disabled="isLoading">
          <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M21.5 2v6h-6M2.5 22v-6h6M2 11.5a10 10 0 0 1 18.8-4.3M22 12.5a10 10 0 0 1-18.8 4.2"/>
          </svg>
          {{ $t('aiSummary.regenerate') }}
        </button>
      </div>

      <!-- 尚未生成 -->
      <div v-else class="empty-state">
        <p class="empty-hint">{{ $t('aiSummary.emptyHint') }}</p>
        <button class="generate-btn" @click="generateSummary" :disabled="isLoading">
          <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M12 3c.132 0 .263 0 .393 0a7.5 7.5 0 0 0 7.92 12.446a9 9 0 1 1 -8.313 -12.454z" />
            <path d="M17 4a2 2 0 0 0 2 2a2 2 0 0 0 -2 2a2 2 0 0 0 -2 -2a2 2 0 0 0 2 -2" />
          </svg>
          {{ $t('aiSummary.generate') }}
        </button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { summaryService } from '../../api/services.js'

const { t: $t } = useI18n()

// Props
const props = defineProps({
  taskId: {
    type: String,
    required: true
  },
  initialSummaryStatus: {
    type: String,
    default: null
  }
})

// Emits
const emit = defineEmits(['summary-updated'])

// State
const isExpanded = ref(false)
const isLoading = ref(false)
const error = ref(null)
const summary = ref(null)
const summaryStatus = ref(props.initialSummaryStatus)
const isCopied = ref(false)

// Computed
const keyPoints = computed(() => {
  if (!summary.value?.content) return []
  // 優先使用 key_points，向後兼容 highlights
  const points = summary.value.content.key_points || summary.value.content.highlights || []
  return points.map(p => typeof p === 'string' ? p : (p.text || p.point || p.content || JSON.stringify(p)))
})

// 類型標籤樣式
function getTypeClass(type) {
  const classes = {
    'Meeting': 'type-meeting',
    'Lecture': 'type-lecture',
    'Interview': 'type-interview',
    'General': 'type-general'
  }
  return classes[type] || 'type-general'
}

function getTypeLabel(type) {
  const labels = {
    'Meeting': $t('aiSummary.typeMeeting'),
    'Lecture': $t('aiSummary.typeLecture'),
    'Interview': $t('aiSummary.typeInterview'),
    'General': $t('aiSummary.typeGeneral')
  }
  return labels[type] || $t('aiSummary.typeGeneral')
}

// 語氣標籤樣式
function getSentimentClass(sentiment) {
  const classes = {
    'Positive': 'sentiment-positive',
    'Neutral': 'sentiment-neutral',
    'Negative': 'sentiment-negative'
  }
  return classes[sentiment] || 'sentiment-neutral'
}

function getSentimentLabel(sentiment) {
  const labels = {
    'Positive': $t('aiSummary.sentimentPositive'),
    'Neutral': $t('aiSummary.sentimentNeutral'),
    'Negative': $t('aiSummary.sentimentNegative')
  }
  return labels[sentiment] || $t('aiSummary.sentimentNeutral')
}

// 複製摘要為純文字
async function copySummaryText() {
  if (!summary.value?.content) return

  const content = summary.value.content
  const lines = []

  // 主題
  if (content.meta?.detected_topic) {
    lines.push(content.meta.detected_topic)
    lines.push('')
  }

  // 執行摘要
  if (content.summary) {
    lines.push(`【${$t('aiSummary.executiveSummary')}】`)
    lines.push(content.summary)
    lines.push('')
  }

  // 重點
  const points = content.key_points || content.highlights || []
  if (points.length > 0) {
    lines.push(`【${$t('aiSummary.keyPoints')}】`)
    points.forEach(point => {
      const text = typeof point === 'string' ? point : (point.text || point.point || point.content || JSON.stringify(point))
      lines.push(`• ${text}`)
    })
    lines.push('')
  }

  // 內容段落
  if (content.segments && content.segments.length > 0) {
    lines.push(`【${$t('aiSummary.contentSegments')}】`)
    content.segments.forEach(segment => {
      lines.push(`▎${segment.topic}`)
      lines.push(segment.content)
      if (segment.keywords && segment.keywords.length > 0) {
        lines.push(`${$t('aiSummary.keywords')}: ${segment.keywords.join(', ')}`)
      }
      lines.push('')
    })
  }

  // 待辦事項
  if (content.action_items && content.action_items.length > 0) {
    lines.push(`【${$t('aiSummary.actionItems')}】`)
    content.action_items.forEach(item => {
      let line = `☐ ${item.task}`
      const meta = []
      if (item.owner) meta.push(item.owner)
      if (item.deadline) meta.push(item.deadline)
      if (meta.length > 0) line += ` (${meta.join(' / ')})`
      lines.push(line)
    })
    lines.push('')
  }

  const text = lines.join('\n').trim()

  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text)
    } else {
      const textarea = document.createElement('textarea')
      textarea.value = text
      textarea.style.position = 'fixed'
      textarea.style.opacity = '0'
      document.body.appendChild(textarea)
      textarea.select()
      document.execCommand('copy')
      document.body.removeChild(textarea)
    }
    isCopied.value = true
    setTimeout(() => {
      isCopied.value = false
    }, 2000)
  } catch (err) {
    console.error('複製失敗:', err)
  }
}

// 切換展開/收起
function toggleExpanded() {
  isExpanded.value = !isExpanded.value

  // 展開時嘗試載入摘要（如果還沒載入過）
  if (isExpanded.value && !summary.value && !isLoading.value) {
    loadSummary()
  }
}

// 載入摘要
async function loadSummary() {
  if (!props.taskId) return

  try {
    isLoading.value = true
    error.value = null

    const data = await summaryService.get(props.taskId)
    summary.value = data
    summaryStatus.value = 'completed'
  } catch (err) {
    // 404 表示尚未生成，不顯示錯誤
    if (err.response?.status !== 404) {
      console.error('載入摘要失敗:', err)
      error.value = err.response?.data?.detail || $t('aiSummary.loadError')
    }
  } finally {
    isLoading.value = false
  }
}

// 生成摘要
async function generateSummary() {
  if (!props.taskId || isLoading.value) return

  try {
    isLoading.value = true
    error.value = null
    summaryStatus.value = 'processing'

    const result = await summaryService.generate(props.taskId)

    if (result.status === 'completed') {
      summary.value = result.summary
      summaryStatus.value = 'completed'
      emit('summary-updated', { taskId: props.taskId, status: 'completed' })
    } else {
      error.value = result.error || $t('aiSummary.generateError')
      summaryStatus.value = 'failed'
      emit('summary-updated', { taskId: props.taskId, status: 'failed' })
    }
  } catch (err) {
    console.error('生成摘要失敗:', err)
    error.value = err.response?.data?.detail || $t('aiSummary.generateError')
    summaryStatus.value = 'failed'
    emit('summary-updated', { taskId: props.taskId, status: 'failed' })
  } finally {
    isLoading.value = false
  }
}

// 監聽 taskId 變化
watch(() => props.taskId, (newTaskId) => {
  if (newTaskId) {
    // 重置狀態
    summary.value = null
    error.value = null
    summaryStatus.value = props.initialSummaryStatus

    // 如果已展開，載入摘要
    if (isExpanded.value) {
      loadSummary()
    }
  }
})

// 監聽 initialSummaryStatus 變化
watch(() => props.initialSummaryStatus, (newStatus) => {
  summaryStatus.value = newStatus
})

// 初始載入
onMounted(() => {
  // 如果已展開或已有 completed 狀態，載入摘要
  if (isExpanded.value || summaryStatus.value === 'completed') {
    loadSummary()
  }
})
</script>

<style scoped>
.ai-summary-card {
  border-bottom: 1px solid rgba(0, 0, 0, 0.06);
  margin-bottom: 8px;
}

.summary-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 16px;
  cursor: pointer;
  border-radius: 8px;
  transition: background-color 0.2s ease;
}

.summary-header:hover {
  background-color: rgba(0, 0, 0, 0.03);
}

.header-left {
  display: flex;
  align-items: center;
  gap: 8px;
  color: var(--main-text);
}

.header-left svg {
  color: var(--main-primary);
}

.header-title {
  font-size: 14px;
  font-weight: 500;
}

.header-right {
  display: flex;
  align-items: center;
  gap: 8px;
}

.status-badge {
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 10px;
}

.status-badge.processing {
  background-color: rgba(255, 193, 7, 0.15);
  color: #f59e0b;
}

.status-badge.completed {
  background-color: rgba(76, 175, 80, 0.15);
  color: #4caf50;
}

.expand-icon {
  color: var(--main-text-light);
  transition: transform 0.2s ease;
}

.expand-icon.expanded {
  transform: rotate(180deg);
}

.summary-content {
  padding: 0 16px 12px;
  max-height: 80vh;
  overflow-y: auto;
}

/* 載入狀態 */
.loading-state {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
  padding: 24px;
  color: var(--main-text-light);
}

.spinner {
  width: 20px;
  height: 20px;
  border: 2px solid rgba(163, 177, 198, 0.3);
  border-top-color: var(--main-primary);
  border-radius: 50%;
  animation: spin 1s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

/* 錯誤狀態 */
.error-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
  padding: 16px;
  text-align: center;
}

.error-message {
  color: #ef4444;
  font-size: 13px;
}

.retry-btn {
  padding: 6px 16px;
  background: var(--main-primary);
  color: white;
  border: none;
  border-radius: 6px;
  font-size: 13px;
  cursor: pointer;
  transition: background-color 0.2s ease;
}

.retry-btn:hover {
  background: var(--main-primary-dark);
}

/* 摘要顯示 */
.summary-display {
  position: relative;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

/* 複製按鈕 (右上角) */
.copy-btn {
  position: absolute;
  top: 0;
  right: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  padding: 0;
  background: transparent;
  color: var(--main-text-light);
  border: 1px solid rgba(0, 0, 0, 0.1);
  border-radius: 6px;
  cursor: pointer;
  transition: all 0.2s ease;
}

.copy-btn:hover {
  background: rgba(0, 0, 0, 0.03);
  color: var(--main-text);
  border-color: rgba(0, 0, 0, 0.2);
}

.copy-btn.copied {
  color: #22c55e;
  border-color: rgba(34, 197, 94, 0.3);
  background: rgba(34, 197, 94, 0.05);
}

/* Meta 區塊 */
.meta-section {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding-bottom: 12px;
  border-bottom: 1px solid rgba(0, 0, 0, 0.06);
}

.meta-badges {
  display: flex;
  gap: 8px;
}

.type-badge, .sentiment-badge {
  font-size: 11px;
  padding: 3px 10px;
  border-radius: 12px;
  font-weight: 500;
}

.type-meeting { background: rgba(59, 130, 246, 0.15); color: #3b82f6; }
.type-lecture { background: rgba(168, 85, 247, 0.15); color: #a855f7; }
.type-interview { background: rgba(236, 72, 153, 0.15); color: #ec4899; }
.type-general { background: rgba(107, 114, 128, 0.15); color: #6b7280; }

.sentiment-positive { background: rgba(34, 197, 94, 0.15); color: #22c55e; }
.sentiment-neutral { background: rgba(107, 114, 128, 0.15); color: #6b7280; }
.sentiment-negative { background: rgba(239, 68, 68, 0.15); color: #ef4444; }

.detected-topic {
  font-size: 16px;
  font-weight: 600;
  color: var(--main-text);
  margin: 0;
  line-height: 1.4;
}

.section {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.section-title {
  font-size: 12px;
  font-weight: 600;
  color: var(--main-text-light);
  text-transform: uppercase;
  letter-spacing: 0.5px;
  margin: 0;
}

/* 執行摘要 */
.summary-text {
  font-size: 13px;
  line-height: 1.7;
  color: var(--main-text);
  margin: 0;
}

/* 重點列表 */
.key-points-list {
  margin: 0;
  padding-left: 20px;
  list-style-type: disc;
}

.key-points-list li {
  font-size: 13px;
  line-height: 1.6;
  color: var(--main-text);
  margin-bottom: 4px;
}

/* 內容段落 */
.segments-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.segment-item {
  padding: 12px;
  background: rgba(0, 0, 0, 0.02);
  border-radius: 8px;
  border-left: 3px solid var(--main-primary);
}

.segment-topic {
  font-size: 13px;
  font-weight: 600;
  color: var(--main-text);
  margin: 0 0 6px 0;
}

.segment-content {
  font-size: 13px;
  line-height: 1.6;
  color: var(--main-text);
  margin: 0 0 8px 0;
}

.segment-keywords {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}

/* 關鍵詞標籤 */
.keyword-tag {
  display: inline-block;
  padding: 2px 8px;
  background: rgba(var(--main-primary-rgb), 0.1);
  color: var(--main-primary);
  border-radius: 10px;
  font-size: 11px;
}

/* 待辦事項 */
.action-items-section {
  background: rgba(59, 130, 246, 0.05);
  border-radius: 8px;
  padding: 12px;
}

.action-items-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.action-item {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 8px;
  background: white;
  border-radius: 6px;
  border: 1px solid rgba(0, 0, 0, 0.06);
}

.action-task {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  font-size: 13px;
  color: var(--main-text);
}

.action-task svg {
  color: #3b82f6;
  flex-shrink: 0;
  margin-top: 2px;
}

.action-meta {
  display: flex;
  gap: 12px;
  margin-left: 22px;
}

.action-owner, .action-deadline {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 11px;
  color: var(--main-text-light);
}

.action-owner svg, .action-deadline svg {
  opacity: 0.7;
}

/* 元數據 */
.metadata {
  display: flex;
  justify-content: flex-end;
  padding-top: 8px;
  border-top: 1px solid rgba(0, 0, 0, 0.06);
}

.metadata-item {
  font-size: 11px;
  color: var(--main-text-light);
}

/* 重新生成按鈕 */
.regenerate-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 8px 16px;
  background: transparent;
  color: var(--main-text-light);
  border: 1px solid rgba(0, 0, 0, 0.1);
  border-radius: 6px;
  font-size: 13px;
  cursor: pointer;
  transition: all 0.2s ease;
  margin-top: 8px;
}

.regenerate-btn:hover:not(:disabled) {
  background: rgba(0, 0, 0, 0.03);
  color: var(--main-text);
  border-color: rgba(0, 0, 0, 0.2);
}

.regenerate-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

/* 空狀態 */
.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
  padding: 16px;
  text-align: center;
}

.empty-hint {
  font-size: 13px;
  color: var(--main-text-light);
  margin: 0;
}

.generate-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 10px 20px;
  background: var(--main-primary);
  color: white;
  border: none;
  border-radius: 8px;
  font-size: 14px;
  font-weight: 500;
  cursor: pointer;
  transition: background-color 0.2s ease;
}

.generate-btn:hover:not(:disabled) {
  background: var(--main-primary-dark);
}

.generate-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

/* 深色模式 */
[data-theme="dark"] .ai-summary-card {
  border-bottom-color: rgba(255, 255, 255, 0.1);
}

[data-theme="dark"] .summary-header:hover {
  background-color: rgba(255, 255, 255, 0.05);
}

[data-theme="dark"] .meta-section {
  border-bottom-color: rgba(255, 255, 255, 0.1);
}

[data-theme="dark"] .segment-item {
  background: rgba(255, 255, 255, 0.03);
}

[data-theme="dark"] .action-items-section {
  background: rgba(59, 130, 246, 0.1);
}

[data-theme="dark"] .action-item {
  background: rgba(255, 255, 255, 0.05);
  border-color: rgba(255, 255, 255, 0.1);
}

[data-theme="dark"] .metadata {
  border-top-color: rgba(255, 255, 255, 0.1);
}

[data-theme="dark"] .copy-btn {
  border-color: rgba(255, 255, 255, 0.1);
}

[data-theme="dark"] .copy-btn:hover {
  background: rgba(255, 255, 255, 0.05);
  border-color: rgba(255, 255, 255, 0.2);
}

[data-theme="dark"] .regenerate-btn {
  border-color: rgba(255, 255, 255, 0.1);
}

[data-theme="dark"] .regenerate-btn:hover:not(:disabled) {
  background: rgba(255, 255, 255, 0.05);
  border-color: rgba(255, 255, 255, 0.2);
}
</style>
