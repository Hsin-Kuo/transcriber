<template>
  <div class="task-list">
    <div class="list-header">
      <h2>Transcription Tasks</h2>
      <button class="btn btn-secondary btn-icon" @click="emit('refresh')" title="Refresh">
        <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <path d="M21.5 2v6h-6M2.5 22v-6h6M2 11.5a10 10 0 0 1 18.8-4.3M22 12.5a10 10 0 0 1-18.8 4.2"/>
        </svg>
      </button>
    </div>

    <div v-if="tasks.length === 0" class="empty-state">
      <p>尚無轉錄任務</p>
      <p class="text-muted">上傳音訊檔案以開始轉錄</p>
    </div>

    <div v-else class="tasks">
      <div
        v-for="task in sortedTasks"
        :key="task.task_id"
        class="electric-card task-wrapper"
      >
        <div class="electric-inner">
          <div class="electric-border-outer">
            <div class="electric-main task-item" :class="{ 'animated': task.status === 'processing' }">
              <div class="task-main">
                <div class="task-info">
                  <div class="task-header">
                    <h3>{{ task.filename || task.file }}</h3>
                    <span :class="['badge', `badge-${task.status}`]">
                      {{ getStatusText(task.status) }}
                    </span>
                  </div>

                  <div class="task-meta">
                    <span v-if="task.file_size_mb">
                      📦 {{ task.file_size_mb }} MB
                    </span>
                    <span v-if="task.created_at">
                      🕒 {{ task.created_at }}
                    </span>
                    <span v-if="task.punct_provider">
                      ✨ {{ task.punct_provider }}
                    </span>
                    <span v-if="task.diarize" class="badge-diarize" :title="task.max_speakers ? `最多 ${task.max_speakers} 位講者` : '自動偵測講者人數'">
                      說話者辨識{{ task.max_speakers ? ` (≤${task.max_speakers}人)` : '' }}
                    </span>
                  </div>

                  <div v-if="task.progress" class="task-progress">
                    <div class="progress-bar">
                      <div
                        class="progress-fill"
                        :style="{ width: getProgressWidth(task) }"
                      ></div>
                    </div>
                    <p class="progress-text">
                      <span v-if="['pending', 'processing'].includes(task.status)" class="spinner"></span>
                      {{ task.progress }}
                      <span v-if="task.progress_percentage !== undefined && task.progress_percentage !== null" class="progress-percentage">
                        {{ Math.round(task.progress_percentage) }}%
                      </span>
                      <span v-if="task.estimated_completion_text && ['pending', 'processing'].includes(task.status)" class="estimate-time">
                        · 預計完成時間：{{ task.estimated_completion_text }}
                      </span>
                    </p>
                    <!-- 顯示說話者辨識狀態 -->
                    <p v-if="task.diarize && getDiarizationStatusText(task)" class="diarization-status" :class="`status-${task.diarization_status}`">
                      {{ getDiarizationStatusText(task) }}
                    </p>
                    <!-- 顯示正在處理的 chunks -->
                    <p v-if="getProcessingChunksText(task)" class="processing-chunks">
                      {{ getProcessingChunksText(task) }}
                    </p>
                  </div>

                  <div v-if="task.status === 'completed' && task.text_length" class="task-result">
                    <div>📝 已轉錄 {{ task.text_length }} 字</div>
                    <div v-if="task.duration_text" class="duration">
                      ⏱️ 處理時間：{{ task.duration_text }}
                    </div>
                  </div>

                  <div v-if="task.status === 'failed' && task.error" class="task-error">
                    ❌ {{ task.error }}
                  </div>
                </div>

                <div class="task-actions">
                  <button
                    v-if="task.status === 'completed'"
                    class="btn btn-primary"
                    @click="emit('download', task.task_id)"
                  >
                    下載
                  </button>
                  <button
                    v-if="['pending', 'processing'].includes(task.status)"
                    class="btn btn-warning"
                    @click="emit('cancel', task.task_id)"
                    :disabled="task.cancelling"
                    title="取消正在執行的任務"
                  >
                    <span v-if="task.cancelling" class="spinner"></span>
                    {{ task.cancelling ? '取消中...' : '取消' }}
                  </button>
                  <button
                    v-if="['completed', 'failed', 'cancelled'].includes(task.status)"
                    class="btn btn-danger"
                    @click="emit('delete', task.task_id)"
                    title="刪除任務及檔案"
                  >
                    刪除
                  </button>
                </div>
              </div>
            </div>
          </div>
          <!-- 光暈層 -->
          <div class="electric-glow-1"></div>
          <div class="electric-glow-2"></div>
        </div>
        <!-- 疊加效果 -->
        <div class="electric-overlay"></div>
        <div class="electric-bg-glow"></div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  tasks: {
    type: Array,
    required: true
  }
})

const emit = defineEmits(['download', 'refresh', 'delete', 'cancel'])

const sortedTasks = computed(() => {
  return [...props.tasks].sort((a, b) => {
    const statusOrder = { processing: 0, pending: 1, completed: 2, failed: 3 }
    return statusOrder[a.status] - statusOrder[b.status]
  })
})

function getStatusText(status) {
  const statusMap = {
    pending: '等待中',
    processing: '處理中',
    completed: '已完成',
    failed: '失敗',
    cancelled: '已取消'
  }
  return statusMap[status] || status
}

function getProgressWidth(task) {
  if (task.status === 'completed') return '100%'
  if (task.status === 'failed') return '100%'

  // 優先使用基於時間權重的進度百分比
  if (task.progress_percentage !== undefined && task.progress_percentage !== null) {
    const percentage = Math.min(Math.max(task.progress_percentage, 2), 99)
    return `${percentage}%`
  }

  // 後備：如果有 chunk 資訊，根據完成數量計算簡單進度
  if (task.status === 'processing' && task.total_chunks && task.completed_chunks !== undefined) {
    const percentage = (task.completed_chunks / task.total_chunks) * 100
    return `${Math.min(Math.max(percentage, 5), 95)}%`
  }

  // 預設進度
  if (task.status === 'processing') return '30%'
  return '10%'
}

function getDiarizationStatusText(task) {
  if (!task.diarization_status) {
    return null
  }

  const status = task.diarization_status
  const numSpeakers = task.diarization_num_speakers
  const duration = task.diarization_duration_seconds

  if (status === 'running') {
    return '說話者辨識進行中...'
  } else if (status === 'completed') {
    const parts = ['說話者辨識完成']
    if (numSpeakers) {
      parts.push(`識別到 ${numSpeakers} 位說話者`)
    }
    if (duration) {
      const minutes = Math.floor(duration / 60)
      const seconds = Math.floor(duration % 60)
      if (minutes > 0) {
        parts.push(`耗時 ${minutes}分${seconds}秒`)
      } else {
        parts.push(`耗時 ${seconds}秒`)
      }
    }
    return parts.join(' · ')
  } else if (status === 'failed') {
    return '說話者辨識失敗'
  }

  return null
}

function getProcessingChunksText(task) {
  if (!task.chunks || task.chunks.length === 0 || task.status !== 'processing') {
    return null
  }

  const processingChunks = task.chunks.filter(c => c.status === 'processing').map(c => c.chunk_id)
  const completedChunks = task.chunks.filter(c => c.status === 'completed').map(c => c.chunk_id)

  if (processingChunks.length === 0) {
    return null
  }

  const parts = []

  if (completedChunks.length > 0) {
    parts.push(`✓ 已完成：Chunk ${completedChunks.join(', ')}`)
  }

  if (processingChunks.length > 0) {
    parts.push(`⏳ 處理中：Chunk ${processingChunks.join(', ')}`)
  }

  return parts.join(' · ')
}
</script>

<style scoped>
.task-list {
  margin-bottom: 20px;
}

.list-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 24px;
}

.list-header h2 {
  font-size: 24px;
  color: #2d2d2d;
  text-shadow: 0 2px 4px rgba(139, 69, 19, 0.2);
  font-weight: 700;
}

.btn-icon {
  padding: 10px;
  width: 40px;
  height: 40px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 8px;
}

.btn-icon:hover {
  transform: translateY(-1px) rotate(180deg);
}

.btn-icon svg {
  transition: transform 0.3s ease;
}

.empty-state {
  text-align: center;
  padding: 60px 20px;
  color: rgba(45, 45, 45, 0.5);
  background: rgba(255, 255, 255, 0.5);
  backdrop-filter: blur(15px);
  border-radius: 16px;
  border: 1px dashed rgba(255, 250, 235, 0.6);
}

.empty-state p:first-child {
  font-size: 18px;
  font-weight: 500;
  margin-bottom: 8px;
  color: rgba(45, 45, 45, 0.7);
}

.text-muted {
  font-size: 14px;
}

.tasks {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.task-wrapper {
  margin-bottom: 0;
}

.task-item {
  padding: 20px;
  transition: all 0.3s;
  position: relative;
  z-index: 1;
}

.task-wrapper:hover .task-item {
  box-shadow: 0 4px 12px rgba(221, 132, 72, 0.15);
  transform: translateY(-2px);
}

.task-main {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 20px;
}

.task-info {
  flex: 1;
}

.task-header {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 12px;
}

.task-header h3 {
  font-size: 16px;
  color: #2d2d2d;
  margin: 0;
}

.task-meta {
  display: flex;
  gap: 16px;
  font-size: 13px;
  color: rgba(45, 45, 45, 0.6);
  margin-bottom: 12px;
  flex-wrap: wrap;
  align-items: center;
}

.badge-diarize {
  padding: 2px 8px;
  background: rgba(139, 92, 246, 0.1);
  border: 1px solid rgba(139, 92, 246, 0.3);
  border-radius: 4px;
  color: rgba(109, 40, 217, 0.9);
  font-size: 12px;
  font-weight: 500;
  cursor: help;
  transition: all 0.2s;
}

.badge-diarize:hover {
  background: rgba(139, 92, 246, 0.15);
  border-color: rgba(139, 92, 246, 0.5);
  transform: translateY(-1px);
}

.task-progress {
  margin-top: 12px;
}

.progress-bar {
  height: 6px;
  background: #e2e8f0;
  border-radius: 3px;
  overflow: hidden;
  margin-bottom: 8px;
}

.progress-fill {
  height: 100%;
  background: linear-gradient(90deg, #dd8448 0%, #f59e42 100%);
  transition: width 0.5s ease;
  border-radius: 3px;
}

.progress-text {
  font-size: 13px;
  color: rgba(45, 45, 45, 0.8);
  display: flex;
  align-items: center;
  gap: 8px;
}

.estimate-time {
  color: #a0522d;
  font-weight: 500;
}

.progress-percentage {
  color: var(--electric-primary);
  font-weight: 600;
  margin-left: 8px;
}

.diarization-status {
  font-size: 12px;
  margin-top: 6px;
  padding: 6px 10px;
  border-radius: 4px;
  font-weight: 500;
  color: rgba(45, 45, 45, 0.7);
}

.diarization-status.status-running {
  background: rgba(59, 130, 246, 0.08);
  border: 1px solid rgba(59, 130, 246, 0.2);
}

.diarization-status.status-completed {
  background: rgba(221, 132, 72, 0.12);
  border: 1px solid rgba(221, 132, 72, 0.3);
}

.diarization-status.status-failed {
  background: rgba(221, 132, 72, 0.08);
  border: 1px solid rgba(221, 100, 50, 0.3);
}

.processing-chunks {
  font-size: 12px;
  color: rgba(45, 45, 45, 0.7);
  margin-top: 6px;
  padding: 6px 10px;
  background: rgba(59, 130, 246, 0.08);
  border-radius: 4px;
  border: 1px solid rgba(59, 130, 246, 0.15);
}

.task-result {
  margin-top: 8px;
  padding: 8px 12px;
  background: rgba(16, 185, 129, 0.15);
  border: 1px solid rgba(16, 185, 129, 0.3);
  border-radius: 6px;
  font-size: 14px;
  color: rgba(45, 45, 45, 0.7);
}

.task-result .duration {
  margin-top: 4px;
  font-size: 13px;
  opacity: 0.9;
}

.task-error {
  margin-top: 8px;
  padding: 8px 12px;
  background: rgba(239, 68, 68, 0.15);
  border: 1px solid rgba(239, 68, 68, 0.3);
  border-radius: 6px;
  font-size: 14px;
  color: #f87171;
}

.task-actions {
  display: flex;
  gap: 8px;
}
</style>
