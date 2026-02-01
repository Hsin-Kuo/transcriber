<template>
  <div class="task-detail-container">
    <!-- 導航 -->
    <AdminNav />

    <!-- 返回按鈕 -->
    <div class="back-link">
      <router-link to="/tasks">← 返回任務列表</router-link>
    </div>

    <!-- 載入中 -->
    <div v-if="loading" class="loading">
      <div class="spinner"></div>
      <p>載入任務資料中...</p>
    </div>

    <!-- 錯誤訊息 -->
    <div v-else-if="error" class="error-message">
      {{ error }}
    </div>

    <!-- 任務詳情 -->
    <div v-else-if="task" class="task-detail">
      <div class="task-header">
        <h1 class="page-title">
          {{ task.file?.filename || '任務詳情' }}
        </h1>
        <span class="status-badge large" :class="`status-${task.status}`">
          {{ getStatusName(task.status) }}
        </span>
      </div>

      <div class="detail-grid">
        <!-- 基本資訊 -->
        <div class="detail-card">
          <h2>基本資訊</h2>
          <div class="info-row">
            <span class="label">Task ID：</span>
            <code class="value">{{ task.task_id }}</code>
          </div>
          <div class="info-row">
            <span class="label">用戶：</span>
            <router-link
              v-if="task.user?.user_id"
              :to="`/users/${task.user.user_id}`"
              class="user-link"
            >
              {{ task.user?.user_email || task.user?.user_id }}
            </router-link>
            <span v-else>-</span>
          </div>
          <div class="info-row">
            <span class="label">檔名：</span>
            <span class="value">{{ task.file?.filename || '-' }}</span>
          </div>
          <div class="info-row">
            <span class="label">檔案大小：</span>
            <span class="value">{{ task.file?.size_mb?.toFixed(2) || '-' }} MB</span>
          </div>
          <div class="info-row">
            <span class="label">自訂名稱：</span>
            <span class="value">{{ task.custom_name || '-' }}</span>
          </div>
          <div class="info-row">
            <span class="label">標籤：</span>
            <div class="tags" v-if="task.tags?.length">
              <span v-for="tag in task.tags" :key="tag" class="tag">{{ tag }}</span>
            </div>
            <span v-else class="value">-</span>
          </div>
        </div>

        <!-- 轉錄配置 -->
        <div class="detail-card">
          <h2>轉錄配置</h2>
          <div class="info-row">
            <span class="label">標點模型：</span>
            <span class="value">{{ task.config?.punct_provider || '-' }}</span>
          </div>
          <div class="info-row">
            <span class="label">分段處理：</span>
            <span :class="task.config?.chunk_audio ? 'enabled' : 'disabled'">
              {{ task.config?.chunk_audio ? '是' : '否' }}
            </span>
          </div>
          <div class="info-row" v-if="task.config?.chunk_audio">
            <span class="label">分段長度：</span>
            <span class="value">{{ task.config?.chunk_minutes }} 分鐘</span>
          </div>
          <div class="info-row">
            <span class="label">說話者辨識：</span>
            <span :class="task.config?.diarize ? 'enabled' : 'disabled'">
              {{ task.config?.diarize ? '是' : '否' }}
            </span>
          </div>
          <div class="info-row" v-if="task.config?.diarize">
            <span class="label">最大說話者：</span>
            <span class="value">{{ task.config?.max_speakers || '自動' }}</span>
          </div>
          <div class="info-row">
            <span class="label">語言：</span>
            <span class="value">{{ task.config?.language || '自動偵測' }}</span>
          </div>
        </div>

        <!-- 使用模型 -->
        <div class="detail-card">
          <h2>使用模型</h2>
          <div class="info-row">
            <span class="label">轉錄模型：</span>
            <span class="value">{{ task.models?.transcription || '-' }}</span>
          </div>
          <div class="info-row">
            <span class="label">標點模型：</span>
            <span class="value">{{ task.models?.punctuation || '-' }}</span>
          </div>
          <div class="info-row">
            <span class="label">說話者辨識：</span>
            <span class="value">{{ task.models?.diarization || '-' }}</span>
          </div>
        </div>

        <!-- 統計資訊 -->
        <div class="detail-card">
          <h2>統計資訊</h2>
          <div class="info-row">
            <span class="label">音檔時長：</span>
            <span class="value">{{ formatDuration(task.stats?.audio_duration_seconds) }}</span>
          </div>
          <div class="info-row">
            <span class="label">處理時間：</span>
            <span class="value">{{ formatDuration(task.stats?.duration_seconds) }}</span>
          </div>
          <div class="info-row">
            <span class="label">文字長度：</span>
            <span class="value">{{ task.result?.text_length?.toLocaleString() || '-' }} 字</span>
          </div>
          <div class="info-row" v-if="task.stats?.token_usage">
            <span class="label">Token 使用：</span>
            <span class="value">{{ task.stats.token_usage.total?.toLocaleString() || '-' }}</span>
          </div>
          <div class="info-row" v-if="task.stats?.diarization">
            <span class="label">說話者數：</span>
            <span class="value">{{ task.stats.diarization.num_speakers || '-' }}</span>
          </div>
        </div>

        <!-- 時間線 -->
        <div class="detail-card wide">
          <h2>時間線</h2>
          <div class="timeline">
            <div class="timeline-item" :class="{ active: true }">
              <div class="timeline-dot"></div>
              <div class="timeline-content">
                <span class="timeline-label">建立</span>
                <span class="timeline-time">{{ formatTimestamp(task.timestamps?.created_at) }}</span>
              </div>
            </div>
            <div class="timeline-item" :class="{ active: task.timestamps?.started_at }">
              <div class="timeline-dot"></div>
              <div class="timeline-content">
                <span class="timeline-label">開始處理</span>
                <span class="timeline-time">{{ formatTimestamp(task.timestamps?.started_at) || '-' }}</span>
              </div>
            </div>
            <div class="timeline-item" :class="{ active: task.timestamps?.completed_at, success: task.status === 'completed', error: task.status === 'failed' }">
              <div class="timeline-dot"></div>
              <div class="timeline-content">
                <span class="timeline-label">{{ task.status === 'completed' ? '完成' : task.status === 'failed' ? '失敗' : '完成' }}</span>
                <span class="timeline-time">{{ formatTimestamp(task.timestamps?.completed_at) || '-' }}</span>
              </div>
            </div>
          </div>
        </div>

        <!-- 錯誤訊息 -->
        <div v-if="task.error_message" class="detail-card wide error-card">
          <h2>錯誤訊息</h2>
          <div class="error-content">
            {{ task.error_message }}
          </div>
        </div>
      </div>

      <!-- 操作按鈕 -->
      <div class="action-buttons">
        <button
          v-if="['pending', 'processing'].includes(task.status)"
          @click="cancelTask"
          class="action-btn cancel"
        >
          取消任務
        </button>
        <button
          v-else
          @click="deleteTask"
          class="action-btn delete"
        >
          刪除任務
        </button>
        <router-link
          v-if="task.user?.user_id"
          :to="`/users/${task.user.user_id}`"
          class="action-btn view"
        >
          查看用戶
        </router-link>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import api from '../utils/api'
import AdminNav from '../components/shared/AdminNav.vue'

const route = useRoute()
const router = useRouter()

const task = ref(null)
const loading = ref(true)
const error = ref(null)

async function fetchTask() {
  loading.value = true
  error.value = null

  try {
    const response = await api.get(`/api/admin/tasks/${route.params.id}`)
    task.value = response.data
  } catch (err) {
    error.value = err.response?.data?.detail || err.message || '載入失敗'
  } finally {
    loading.value = false
  }
}

async function cancelTask() {
  if (!confirm('確定要取消此任務嗎？')) return

  try {
    await api.post(`/api/admin/tasks/${task.value.task_id}/cancel`)
    task.value.status = 'cancelled'
    alert('任務已取消')
  } catch (err) {
    alert(err.response?.data?.detail || '取消失敗')
  }
}

async function deleteTask() {
  if (!confirm('確定要刪除此任務嗎？')) return

  try {
    await api.delete(`/api/admin/tasks/${task.value.task_id}`)
    alert('任務已刪除')
    router.push('/tasks')
  } catch (err) {
    alert(err.response?.data?.detail || '刪除失敗')
  }
}

function getStatusName(status) {
  const names = {
    pending: '等待中', processing: '處理中', completed: '已完成',
    failed: '失敗', cancelled: '已取消', canceling: '取消中'
  }
  return names[status] || status
}

function formatDuration(seconds) {
  if (!seconds) return '-'
  if (seconds < 60) return `${Math.round(seconds)} 秒`
  const mins = Math.floor(seconds / 60)
  const secs = Math.round(seconds % 60)
  if (mins < 60) return `${mins} 分 ${secs} 秒`
  const hours = Math.floor(mins / 60)
  const remainMins = mins % 60
  return `${hours} 時 ${remainMins} 分`
}

function formatTimestamp(timestamp) {
  if (!timestamp) return null
  if (typeof timestamp === 'number') {
    return new Date(timestamp * 1000).toLocaleString('zh-TW')
  }
  return timestamp
}

onMounted(() => {
  fetchTask()
})
</script>

<style scoped>
.task-detail-container {
  max-width: 1400px;
  margin: 0 auto;
  padding: 20px;
}

.admin-nav {
  display: flex;
  gap: 15px;
  margin-bottom: 20px;
  background: white;
  padding: 15px 20px;
  border-radius: 20px;
  justify-content: center;
}

.nav-link {
  padding: 12px 24px;
  background: var(--color-primary, #dd8448); color: white;
  color: var(--color-text, rgb(145, 106, 45));
  text-decoration: none;
  border-radius: 12px;
  font-weight: 600;
  transition: all 0.3s;
}

.nav-link:hover { transform: translateY(-2px); }
.nav-link.active {
  background: var(--color-primary, #dd8448);
  color: white;
}

.back-link {
  margin-bottom: 20px;
}

.back-link a {
  color: var(--color-primary, #dd8448);
  text-decoration: none;
  font-weight: 600;
}

.back-link a:hover { text-decoration: underline; }

.loading, .error-message {
  text-align: center;
  padding: 40px;
  font-size: 18px;
}

.spinner {
  border: 4px solid transparent;
  border-top: 4px solid var(--main-primary);
  border-radius: 50%;
  width: 40px;
  height: 40px;
  animation: spin 1s linear infinite;
  margin: 0 auto 20px;
}

@keyframes spin {
  0% { transform: rotate(0deg); }
  100% { transform: rotate(360deg); }
}

.task-header {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 20px;
  margin-bottom: 30px;
}

.page-title {
  color: var(--color-primary, #dd8448);
  font-weight: 700;
  margin: 0;
}

.status-badge {
  padding: 4px 12px;
  border-radius: 8px;
  font-size: 12px;
  font-weight: 700;
}

.status-badge.large {
  padding: 8px 20px;
  font-size: 14px;
}

.status-badge.status-completed { background: #c8e6c9; color: #2e7d32; }
.status-badge.status-failed { background: #ffcdd2; color: #c62828; }
.status-badge.status-processing { background: #fff3e0; color: #f57c00; }
.status-badge.status-pending { background: #e3f2fd; color: #1976d2; }
.status-badge.status-cancelled { background: #f5f5f5; color: #757575; }

.detail-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
  gap: 20px;
  margin-bottom: 30px;
}

.detail-card {
  background: white;
  border-radius: 20px;
  padding: 24px;
}

.detail-card.wide {
  grid-column: span 2;
}

.detail-card.error-card {
  border: 2px solid #ffcdd2;
}

.detail-card h2 {
  font-size: 18px;
  color: var(--color-primary, #dd8448);
  margin-bottom: 20px;
  font-weight: 700;
}

.info-row {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 0;
  border-bottom: 1px solid rgba(163, 177, 198, 0.2);
}

.info-row:last-child { border-bottom: none; }

.label {
  color: var(--color-text-light, #a0917c);
  font-weight: 500;
  min-width: 100px;
}

.value {
  color: var(--color-text, rgb(145, 106, 45));
  font-weight: 600;
}

code {
  background: white;
  padding: 4px 8px;
  border-radius: 6px;
  font-size: 11px;
  border: 1px solid rgba(163, 177, 198, 0.15);
  word-break: break-all;
}

.user-link {
  color: var(--color-primary, #dd8448);
  text-decoration: none;
  font-weight: 600;
}

.user-link:hover { text-decoration: underline; }

.enabled { color: #2e7d32; font-weight: 600; }
.disabled { color: #757575; font-weight: 600; }

.tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.tag {
  background: #e3f2fd;
  color: #1976d2;
  padding: 4px 10px;
  border-radius: 6px;
  font-size: 12px;
  font-weight: 600;
}

.timeline {
  display: flex;
  justify-content: space-between;
  position: relative;
  padding: 20px 0;
}

.timeline::before {
  content: '';
  position: absolute;
  top: 50%;
  left: 0;
  right: 0;
  height: 4px;
  background: rgba(163, 177, 198, 0.3);
  transform: translateY(-50%);
}

.timeline-item {
  display: flex;
  flex-direction: column;
  align-items: center;
  position: relative;
  z-index: 1;
  flex: 1;
}

.timeline-dot {
  width: 20px;
  height: 20px;
  border-radius: 50%;
  background: #f5f5f5;
  border: 3px solid rgba(163, 177, 198, 0.5);
  margin-bottom: 10px;
}

.timeline-item.active .timeline-dot {
  background: var(--main-primary);
  border-color: var(--main-primary-light);
}

.timeline-item.success .timeline-dot {
  background: #2e7d32;
  border-color: #81c784;
}

.timeline-item.error .timeline-dot {
  background: #c62828;
  border-color: #ef9a9a;
}

.timeline-content {
  text-align: center;
}

.timeline-label {
  display: block;
  font-weight: 600;
  color: var(--color-text, rgb(145, 106, 45));
  margin-bottom: 4px;
}

.timeline-time {
  font-size: 12px;
  color: var(--color-text-light, #a0917c);
}

.error-content {
  background: #ffebee;
  padding: 15px;
  border-radius: 12px;
  color: #c62828;
  font-family: monospace;
  font-size: 13px;
  white-space: pre-wrap;
  word-break: break-word;
}

.action-buttons {
  display: flex;
  justify-content: center;
  gap: 15px;
}

.action-btn {
  padding: 12px 24px;
  border: none;
  border-radius: 12px;
  font-size: 14px;
  font-weight: 700;
  cursor: pointer;
  text-decoration: none;
  transition: all 0.3s;
}

.action-btn.view {
  background: var(--color-primary, #dd8448); color: white;
  color: var(--color-primary, #dd8448);
}

.action-btn.cancel {
  background: #fff3e0;
  color: #f57c00;
}

.action-btn.delete {
  background: #ffcdd2;
  color: #c62828;
}

.action-btn:hover {
  transform: translateY(-2px);
}

@media (max-width: 768px) {
  .detail-card.wide {
    grid-column: span 1;
  }

  .timeline {
    flex-direction: column;
    gap: 20px;
  }

  .timeline::before {
    top: 0;
    bottom: 0;
    left: 10px;
    right: auto;
    width: 4px;
    height: auto;
    transform: none;
  }

  .timeline-item {
    flex-direction: row;
    gap: 15px;
  }

  .timeline-dot {
    margin-bottom: 0;
  }

  .timeline-content {
    text-align: left;
  }
}
</style>
