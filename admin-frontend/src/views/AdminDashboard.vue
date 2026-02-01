<template>
  <div class="admin-container">
    <!-- 導航 -->
    <AdminNav />

    <h1 class="admin-title">系統統計後台</h1>

    <div v-if="loading" class="loading">
      <div class="spinner"></div>
      <p>載入統計資料中...</p>
    </div>

    <div v-else-if="error" class="error-message">
      ❌ {{ error }}
    </div>

    <div v-else class="stats-grid">
      <!-- 總覽卡片 -->
      <div class="stat-card">
        <h2>總覽</h2>
        <div class="stat-item">
          <span class="label">總任務數：</span>
          <span class="value">{{ stats.overview.total_tasks }}</span>
        </div>
        <div class="stat-item">
          <span class="label">已完成：</span>
          <span class="value success">{{ stats.overview.completed_tasks }}</span>
        </div>
        <div class="stat-item">
          <span class="label">處理中：</span>
          <span class="value warning">{{ stats.overview.processing_tasks }}</span>
        </div>
        <div class="stat-item">
          <span class="label">失敗：</span>
          <span class="value danger">{{ stats.overview.failed_tasks }}</span>
        </div>
        <div class="stat-item">
          <span class="label">成功率：</span>
          <span class="value">{{ stats.overview.success_rate }}%</span>
        </div>
      </div>

      <!-- Token 使用量卡片 -->
      <div class="stat-card wide">
        <h2>🔢 Token 使用量</h2>

        <!-- 總計 -->
        <div class="token-summary">
          <div class="token-total">
            <span class="total-label">總 Token</span>
            <span class="total-value">{{ formatNumber(stats.token_usage.total_tokens) }}</span>
          </div>
          <div class="token-breakdown">
            <span>輸入: {{ formatNumber(stats.token_usage.prompt_tokens) }}</span>
            <span>輸出: {{ formatNumber(stats.token_usage.completion_tokens) }}</span>
          </div>
          <div class="cost-estimate">
            預估成本: ${{ estimatedCost.toFixed(4) }} USD
          </div>
        </div>

        <!-- 分類統計 -->
        <div class="token-categories">
          <!-- 標點符號 -->
          <div class="token-category">
            <h3>📝 標點符號</h3>
            <div class="stat-item">
              <span class="label">總 Token：</span>
              <span class="value">{{ formatNumber(stats.token_usage.punctuation?.total_tokens || 0) }}</span>
            </div>
            <div class="stat-item">
              <span class="label">輸入 / 輸出：</span>
              <span class="value">{{ formatNumber(stats.token_usage.punctuation?.prompt_tokens || 0) }} / {{ formatNumber(stats.token_usage.punctuation?.completion_tokens || 0) }}</span>
            </div>
            <div class="stat-item">
              <span class="label">任務數：</span>
              <span class="value">{{ stats.token_usage.punctuation?.tasks_count || 0 }}</span>
            </div>
            <div class="stat-item">
              <span class="label">平均每任務：</span>
              <span class="value">{{ formatNumber(stats.token_usage.punctuation?.avg_tokens_per_task || 0) }}</span>
            </div>
          </div>

          <!-- AI 總結 -->
          <div class="token-category">
            <h3>🤖 AI 總結</h3>
            <div class="stat-item">
              <span class="label">總 Token：</span>
              <span class="value">{{ formatNumber(stats.token_usage.summary?.total_tokens || 0) }}</span>
            </div>
            <div class="stat-item">
              <span class="label">輸入 / 輸出：</span>
              <span class="value">{{ formatNumber(stats.token_usage.summary?.prompt_tokens || 0) }} / {{ formatNumber(stats.token_usage.summary?.completion_tokens || 0) }}</span>
            </div>
            <div class="stat-item">
              <span class="label">摘要數：</span>
              <span class="value">{{ stats.token_usage.summary?.summaries_count || 0 }}</span>
            </div>
            <div class="stat-item">
              <span class="label">平均每摘要：</span>
              <span class="value">{{ formatNumber(stats.token_usage.summary?.avg_tokens_per_summary || 0) }}</span>
            </div>
          </div>
        </div>
      </div>

      <!-- 性能統計卡片 -->
      <div class="stat-card">
        <h2>⚡ 性能統計</h2>
        <div class="stat-item">
          <span class="label">平均處理時間：</span>
          <span class="value">{{ formatDuration(stats.performance.avg_duration_seconds) }}</span>
        </div>
        <div class="stat-item">
          <span class="label">最快：</span>
          <span class="value">{{ formatDuration(stats.performance.min_duration_seconds) }}</span>
        </div>
        <div class="stat-item">
          <span class="label">最慢：</span>
          <span class="value">{{ formatDuration(stats.performance.max_duration_seconds) }}</span>
        </div>
      </div>

      <!-- 模型使用統計 -->
      <div class="stat-card wide">
        <h2>🤖 模型使用統計</h2>

        <!-- 標點符號模型 -->
        <div v-if="stats.model_usage.punctuation && stats.model_usage.punctuation.length > 0" class="model-section">
          <h3 class="model-type-title">📝 標點符號模型</h3>
          <table class="data-table">
            <thead>
              <tr>
                <th>模型名稱</th>
                <th>使用次數</th>
                <th>佔比</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="model in stats.model_usage.punctuation" :key="'punct-' + model.model">
                <td>{{ model.model }}</td>
                <td>{{ model.count }}</td>
                <td>
                  <div class="progress-bar">
                    <div
                      class="progress-fill"
                      :style="{width: `${(model.count / stats.overview.total_tasks * 100).toFixed(1)}%`}"
                    ></div>
                    <span class="progress-text">{{ (model.count / stats.overview.total_tasks * 100).toFixed(1) }}%</span>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        <!-- 轉錄模型 -->
        <div v-if="stats.model_usage.transcription && stats.model_usage.transcription.length > 0" class="model-section">
          <h3 class="model-type-title">🎙️ 轉錄模型</h3>
          <table class="data-table">
            <thead>
              <tr>
                <th>模型名稱</th>
                <th>使用次數</th>
                <th>佔比</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="model in stats.model_usage.transcription" :key="'trans-' + model.model">
                <td>{{ model.model }}</td>
                <td>{{ model.count }}</td>
                <td>
                  <div class="progress-bar">
                    <div
                      class="progress-fill"
                      :style="{width: `${(model.count / stats.overview.total_tasks * 100).toFixed(1)}%`}"
                    ></div>
                    <span class="progress-text">{{ (model.count / stats.overview.total_tasks * 100).toFixed(1) }}%</span>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        <!-- 說話者辨識模型 -->
        <div v-if="stats.model_usage.diarization && stats.model_usage.diarization.length > 0" class="model-section">
          <h3 class="model-type-title">👥 說話者辨識模型</h3>
          <table class="data-table">
            <thead>
              <tr>
                <th>模型名稱</th>
                <th>使用次數</th>
                <th>佔比</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="model in stats.model_usage.diarization" :key="'diar-' + model.model">
                <td>{{ model.model }}</td>
                <td>{{ model.count }}</td>
                <td>
                  <div class="progress-bar">
                    <div
                      class="progress-fill"
                      :style="{width: `${(model.count / stats.overview.total_tasks * 100).toFixed(1)}%`}"
                    ></div>
                    <span class="progress-text">{{ (model.count / stats.overview.total_tasks * 100).toFixed(1) }}%</span>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        <!-- AI 總結模型 -->
        <div v-if="stats.model_usage.summary && stats.model_usage.summary.length > 0" class="model-section">
          <h3 class="model-type-title">🤖 AI 總結模型</h3>
          <table class="data-table">
            <thead>
              <tr>
                <th>模型名稱</th>
                <th>使用次數</th>
                <th>佔比</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="model in stats.model_usage.summary" :key="'summary-' + model.model">
                <td>{{ model.model }}</td>
                <td>{{ model.count }}</td>
                <td>
                  <div class="progress-bar">
                    <div
                      class="progress-fill summary-fill"
                      :style="{width: `${(model.count / totalSummaries * 100).toFixed(1)}%`}"
                    ></div>
                    <span class="progress-text">{{ (model.count / totalSummaries * 100).toFixed(1) }}%</span>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        <div v-if="!hasAnyModelUsage" class="no-data">
          暫無模型使用資料
        </div>
      </div>

      <!-- 標點服務使用統計 -->
      <div class="stat-card">
        <h2>標點服務使用</h2>
        <div v-for="provider in stats.punct_provider_usage" :key="provider.provider" class="stat-item">
          <span class="label">{{ provider.provider }}：</span>
          <span class="value">{{ provider.count }}</span>
        </div>
      </div>

      <!-- 最活躍使用者 -->
      <div class="stat-card wide">
        <h2>👥 最活躍使用者（前 10）</h2>
        <table class="data-table">
          <thead>
            <tr>
              <th>使用者 ID</th>
              <th>任務數</th>
              <th>摘要數</th>
              <th>標點 Token</th>
              <th>摘要 Token</th>
              <th>總 Token</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="user in stats.top_users" :key="user.user_id">
              <td><code>{{ user.user_id }}</code></td>
              <td>{{ user.tasks_count }}</td>
              <td>{{ user.summaries_count || 0 }}</td>
              <td>{{ formatNumber(user.punctuation_tokens || 0) }}</td>
              <td>{{ formatNumber(user.summary_tokens || 0) }}</td>
              <td class="highlight">{{ formatNumber(user.total_tokens || 0) }}</td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- 每日統計圖表 -->
      <div class="stat-card full-width">
        <h2>📊 每日統計（最近 30 天）</h2>
        <div class="chart-container">
          <div class="chart-bars">
            <div
              v-for="day in stats.daily_stats"
              :key="day.date"
              class="chart-bar-wrapper"
              :title="`${day.date}: ${day.tasks_count} 任務, ${day.summaries_count || 0} 摘要, ${formatNumber(day.total_tokens || 0)} tokens`"
            >
              <div class="chart-bar" :style="{height: `${(day.tasks_count / maxDailyTasks * 100)}%`}">
                <span class="bar-value">{{ day.tasks_count }}</span>
              </div>
              <span class="bar-label">{{ day.date.slice(5) }}</span>
            </div>
          </div>
        </div>
      </div>
    </div>

    <div class="refresh-section">
      <button @click="fetchStats" class="refresh-btn">🔄 刷新資料</button>
      <span class="last-update">最後更新：{{ lastUpdate }}</span>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import api from '../utils/api'
import AdminNav from '../components/shared/AdminNav.vue'

const stats = ref({
  overview: {
    total_tasks: 0,
    completed_tasks: 0,
    processing_tasks: 0,
    failed_tasks: 0,
    success_rate: 0
  },
  token_usage: {
    total_tokens: 0,
    prompt_tokens: 0,
    completion_tokens: 0,
    punctuation: {
      total_tokens: 0,
      prompt_tokens: 0,
      completion_tokens: 0,
      tasks_count: 0,
      avg_tokens_per_task: 0
    },
    summary: {
      total_tokens: 0,
      prompt_tokens: 0,
      completion_tokens: 0,
      summaries_count: 0,
      avg_tokens_per_summary: 0
    }
  },
  model_usage: {
    punctuation: [],
    transcription: [],
    diarization: [],
    summary: []
  },
  daily_stats: [],
  top_users: [],
  performance: {
    avg_duration_seconds: 0,
    min_duration_seconds: 0,
    max_duration_seconds: 0
  },
  punct_provider_usage: []
})

const loading = ref(true)
const error = ref(null)
const lastUpdate = ref('')

// 計算預估成本（基於 Gemini 2.0 Flash 定價）
const estimatedCost = computed(() => {
  const promptCost = (stats.value.token_usage.prompt_tokens / 1000000) * 0.075
  const completionCost = (stats.value.token_usage.completion_tokens / 1000000) * 0.30
  return promptCost + completionCost
})

// 計算每日最大任務數（用於圖表縮放）
const maxDailyTasks = computed(() => {
  return Math.max(...stats.value.daily_stats.map(d => d.tasks_count), 1)
})

// 檢查是否有任何模型使用資料
const hasAnyModelUsage = computed(() => {
  return (stats.value.model_usage.punctuation && stats.value.model_usage.punctuation.length > 0) ||
         (stats.value.model_usage.transcription && stats.value.model_usage.transcription.length > 0) ||
         (stats.value.model_usage.diarization && stats.value.model_usage.diarization.length > 0) ||
         (stats.value.model_usage.summary && stats.value.model_usage.summary.length > 0)
})

// 計算總摘要數（用於 AI 總結模型佔比）
const totalSummaries = computed(() => {
  return stats.value.token_usage.summary?.summaries_count || 1
})

// 獲取統計資料
async function fetchStats() {
  loading.value = true
  error.value = null

  try {
    const response = await api.get('/api/admin/statistics')
    stats.value = response.data
    lastUpdate.value = new Date().toLocaleString('zh-TW')
  } catch (err) {
    error.value = err.response?.data?.detail || err.message || '載入失敗'
    console.error('載入統計失敗:', err)
  } finally {
    loading.value = false
  }
}

// 格式化數字（加千分位）
function formatNumber(num) {
  if (num === undefined || num === null) return '0'
  return num.toLocaleString('zh-TW')
}

// 格式化時長
function formatDuration(seconds) {
  if (!seconds) return '0秒'
  const hours = Math.floor(seconds / 3600)
  const mins = Math.floor((seconds % 3600) / 60)
  const secs = Math.floor(seconds % 60)

  if (hours > 0) {
    return `${hours}時${mins}分${secs}秒`
  } else if (mins > 0) {
    return `${mins}分${secs}秒`
  } else {
    return `${secs}秒`
  }
}

onMounted(() => {
  fetchStats()
})
</script>

<style scoped>
.admin-container {
  max-width: 1400px;
  margin: 0 auto;
  padding: 0 20px 40px;
}

.admin-title {
  text-align: center;
  color: var(--color-text, rgb(145, 106, 45));
  margin-bottom: 30px;
  font-weight: 700;
  font-size: 1.75rem;
}

.stats-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
  gap: 20px;
  margin-bottom: 30px;
}

.stat-card {
  background: white;
  border-radius: 14px;
  padding: 24px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.06);
  border: 1px solid rgba(163, 177, 198, 0.2);
}

.stat-card.wide {
  grid-column: span 2;
}

.stat-card.full-width {
  grid-column: 1 / -1;
}

.stat-card h2 {
  font-size: 16px;
  margin-bottom: 16px;
  color: var(--color-primary, #dd8448);
  font-weight: 700;
  display: flex;
  align-items: center;
  gap: 8px;
}

.stat-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 10px 0;
  border-bottom: 1px solid rgba(163, 177, 198, 0.15);
}

.stat-item:last-child {
  border-bottom: none;
}

.label {
  color: var(--color-text-light, #a0917c);
  font-weight: 500;
  font-size: 14px;
}

.value {
  font-weight: 700;
  color: var(--color-text, rgb(145, 106, 45));
  font-size: 15px;
}

.value.success { color: #2e7d32; }
.value.warning { color: #e9760c; }
.value.danger { color: #c62828; }
.value.highlight {
  color: var(--color-primary, #dd8448);
  font-size: 1.1em;
}

.cost-estimate {
  margin-top: 16px;
  padding: 12px 16px;
  background: #fff8f3;
  border: 1px solid rgba(221, 132, 72, 0.2);
  border-radius: 10px;
  text-align: center;
  font-weight: 700;
  color: var(--color-primary-dark, #b8762d);
  font-size: 14px;
}

.data-table {
  width: 100%;
  border-collapse: collapse;
}

.data-table th,
.data-table td {
  padding: 12px;
  text-align: left;
  border-bottom: 1px solid rgba(163, 177, 198, 0.15);
}

.data-table th {
  background: #fafafa;
  font-weight: 600;
  color: var(--color-text, rgb(145, 106, 45));
  font-size: 13px;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.data-table tbody tr:hover {
  background: rgba(221, 132, 72, 0.04);
}

.data-table code {
  background: #f5f5f5;
  padding: 4px 8px;
  border-radius: 6px;
  font-size: 12px;
  color: var(--color-text-muted, #4a6680);
}

.progress-bar {
  position: relative;
  width: 100%;
  height: 22px;
  background: #f0f0f0;
  border-radius: 11px;
  overflow: hidden;
}

.progress-fill {
  height: 100%;
  background: linear-gradient(90deg, var(--color-primary, #dd8448), var(--color-primary-light, #f59e42));
  border-radius: 11px;
  transition: width 0.3s;
}

.progress-text {
  position: absolute;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  font-size: 11px;
  font-weight: 700;
  color: var(--color-text, rgb(145, 106, 45));
}

.chart-container {
  padding: 20px 0;
  min-height: 280px;
}

.chart-bars {
  display: flex;
  align-items: flex-end;
  justify-content: space-around;
  height: 220px;
  gap: 6px;
  padding: 0 10px;
}

.chart-bar-wrapper {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  min-width: 16px;
  max-width: 40px;
}

.chart-bar {
  width: 100%;
  background: var(--color-primary, #dd8448);
  border-radius: 4px 4px 0 0;
  position: relative;
  min-height: 4px;
  transition: all 0.2s;
  cursor: pointer;
}

.chart-bar:hover {
  background: var(--color-primary-dark, #b8762d);
  transform: scaleY(1.02);
}

.bar-value {
  position: absolute;
  top: -18px;
  left: 50%;
  transform: translateX(-50%);
  font-size: 10px;
  font-weight: 700;
  white-space: nowrap;
  color: var(--color-text, rgb(145, 106, 45));
}

.bar-label {
  margin-top: 6px;
  font-size: 10px;
  color: var(--color-text-light, #a0917c);
  text-align: center;
  font-weight: 500;
}

.refresh-section {
  text-align: center;
  padding: 20px;
  display: flex;
  justify-content: center;
  align-items: center;
  gap: 16px;
}

.refresh-btn {
  padding: 10px 20px;
  background: var(--color-primary, #dd8448);
  color: white;
  border: none;
  border-radius: 8px;
  cursor: pointer;
  font-size: 14px;
  font-weight: 600;
  transition: all 0.2s;
}

.refresh-btn:hover {
  background: var(--color-primary-dark, #b8762d);
  transform: translateY(-1px);
}

.last-update {
  color: var(--color-text-light, #a0917c);
  font-size: 13px;
}

.model-section {
  margin-bottom: 24px;
}

.model-section:last-child {
  margin-bottom: 0;
}

.model-type-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--color-text, rgb(145, 106, 45));
  margin-bottom: 12px;
  padding-bottom: 8px;
  border-bottom: 1px solid rgba(163, 177, 198, 0.2);
}

.no-data {
  text-align: center;
  padding: 30px;
  color: var(--color-text-light, #a0917c);
}

/* Token 使用量卡片樣式 */
.token-summary {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 20px;
  background: linear-gradient(135deg, #fff8f3 0%, #fff 100%);
  border-radius: 12px;
  margin-bottom: 20px;
  border: 1px solid rgba(221, 132, 72, 0.15);
}

.token-total {
  display: flex;
  flex-direction: column;
  align-items: center;
  margin-bottom: 8px;
}

.total-label {
  font-size: 13px;
  color: var(--color-text-light, #a0917c);
  font-weight: 500;
}

.total-value {
  font-size: 28px;
  font-weight: 700;
  color: var(--color-primary, #dd8448);
}

.token-breakdown {
  display: flex;
  gap: 20px;
  font-size: 13px;
  color: var(--color-text-light, #a0917c);
}

.token-categories {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 20px;
}

.token-category {
  padding: 16px;
  background: #fafafa;
  border-radius: 10px;
  border: 1px solid rgba(163, 177, 198, 0.15);
}

.token-category h3 {
  font-size: 14px;
  font-weight: 600;
  color: var(--color-text, rgb(145, 106, 45));
  margin-bottom: 12px;
  padding-bottom: 8px;
  border-bottom: 1px solid rgba(163, 177, 198, 0.2);
}

.data-table td.highlight {
  font-weight: 700;
  color: var(--color-primary, #dd8448);
}

/* AI 總結模型進度條 */
.progress-fill.summary-fill {
  background: linear-gradient(90deg, #6366f1, #8b5cf6);
}

@media (max-width: 768px) {
  .stats-grid {
    grid-template-columns: 1fr;
  }

  .stat-card.wide,
  .stat-card.full-width {
    grid-column: 1;
  }

  .chart-bars {
    gap: 3px;
  }

  .bar-label {
    font-size: 8px;
  }

  .bar-value {
    font-size: 8px;
  }

  .token-categories {
    grid-template-columns: 1fr;
  }

  .data-table {
    font-size: 12px;
  }

  .data-table th,
  .data-table td {
    padding: 8px 4px;
  }
}
</style>
