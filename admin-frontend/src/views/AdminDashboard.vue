<template>
  <div class="admin-container">
    <!-- 導航 -->
    <nav class="admin-nav">
      <router-link to="/" class="nav-link" exact-active-class="active">
        📊 系統統計
      </router-link>
      <router-link to="/audit-logs" class="nav-link" exact-active-class="active">
        📝 操作記錄
      </router-link>
    </nav>

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
      <div class="stat-card">
        <h2>Token 使用量</h2>
        <div class="stat-item">
          <span class="label">總 Token：</span>
          <span class="value highlight">{{ formatNumber(stats.token_usage.total_tokens) }}</span>
        </div>
        <div class="stat-item">
          <span class="label">輸入 Token：</span>
          <span class="value">{{ formatNumber(stats.token_usage.prompt_tokens) }}</span>
        </div>
        <div class="stat-item">
          <span class="label">輸出 Token：</span>
          <span class="value">{{ formatNumber(stats.token_usage.completion_tokens) }}</span>
        </div>
        <div class="stat-item">
          <span class="label">使用任務數：</span>
          <span class="value">{{ stats.token_usage.tasks_with_tokens }}</span>
        </div>
        <div class="stat-item">
          <span class="label">平均每任務：</span>
          <span class="value">{{ formatNumber(stats.token_usage.avg_tokens_per_task) }}</span>
        </div>
        <div class="cost-estimate">
          預估成本: ${{ estimatedCost.toFixed(4) }} USD
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
              <th>Token 使用量</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="user in stats.top_users" :key="user.user_id">
              <td><code>{{ user.user_id }}</code></td>
              <td>{{ user.tasks_count }}</td>
              <td>{{ formatNumber(user.tokens_used) }}</td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- 每日統計圖表 -->
      <div class="stat-card full-width">
        <h2>每日統計（最近 30 天）</h2>
        <div class="chart-container">
          <div class="chart-bars">
            <div
              v-for="day in stats.daily_stats"
              :key="day.date"
              class="chart-bar-wrapper"
              :title="`${day.date}: ${day.tasks_count} 任務, ${formatNumber(day.tokens_used)} tokens`"
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
    tasks_with_tokens: 0,
    avg_tokens_per_task: 0
  },
  model_usage: {
    punctuation: [],
    transcription: [],
    diarization: []
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
         (stats.value.model_usage.diarization && stats.value.model_usage.diarization.length > 0)
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
  padding: 20px;
}

/* 導航 */
.admin-nav {
  display: flex;
  gap: 15px;
  margin-bottom: 30px;
  background: var(--main-bg);
  padding: 15px 20px;
  border-radius: 20px;
  justify-content: center;
}

.nav-link {
  padding: 12px 24px;
  background: linear-gradient(145deg, #e9eef5, #d1d9e6);
  color: var(--main-text);
  text-decoration: none;
  border-radius: 12px;
  font-weight: 600;
  transition: all 0.3s;
}

.nav-link:hover {
  transform: translateY(-2px);
}

.nav-link.active {
  background: linear-gradient(145deg, var(--main-primary-light), var(--main-primary));
  color: white;
}

.admin-title {
  text-align: center;
  color: var(--main-primary);
  margin-bottom: 30px;
  font-weight: 700;
}

.loading, .error-message {
  text-align: center;
  padding: 40px;
  font-size: 18px;
  color: var(--main-text);
}

.spinner {
  border: 4px solid transparent;
  border-top: 4px solid var(--main-primary);
  border-right: 4px solid var(--main-primary-light);
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

.stats-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
  gap: 20px;
  margin-bottom: 30px;
}

.stat-card {
  background: var(--main-bg);
  border-radius: 20px;
  padding: 24px;
  border: 1px solid rgba(255, 255, 255, 0.3);
}

.stat-card.wide {
  grid-column: span 2;
}

.stat-card.full-width {
  grid-column: 1 / -1;
}

.stat-card h2 {
  font-size: 18px;
  margin-bottom: 15px;
  color: var(--main-primary);
  font-weight: 700;
}

.stat-item {
  display: flex;
  justify-content: space-between;
  padding: 10px 0;
  border-bottom: 1px solid rgba(163, 177, 198, 0.2);
}

.stat-item:last-child {
  border-bottom: none;
}

.label {
  color: var(--main-text-light);
  font-weight: 500;
}

.value {
  font-weight: 700;
  color: var(--main-text);
}

.value.success {
  color: #2e7d32;
}

.value.warning {
  color: #f57c00;
}

.value.danger {
  color: #c62828;
}

.value.highlight {
  color: var(--main-primary);
  font-size: 1.2em;
}

.cost-estimate {
  margin-top: 15px;
  padding: 12px;
  background: linear-gradient(145deg, #f5d9c4, #e8c4a8);
  border-radius: 12px;
  text-align: center;
  font-weight: 700;
  color: #a0522d;
  box-shadow:
    inset 2px 2px 5px var(--main-shadow-dark),
    inset -2px -2px 5px var(--main-shadow-light);
}

.data-table {
  width: 100%;
  border-collapse: collapse;
}

.data-table th,
.data-table td {
  padding: 12px;
  text-align: left;
  border-bottom: 1px solid rgba(163, 177, 198, 0.2);
}

.data-table th {
  background: var(--main-bg);
  font-weight: 700;
  color: var(--main-primary);
  box-shadow:
    inset 2px 2px 4px var(--main-shadow-dark),
    inset -2px -2px 4px var(--main-shadow-light);
}

.data-table code {
  background: var(--main-bg);
  padding: 4px 8px;
  border-radius: 8px;
  font-size: 0.9em;
  box-shadow:
    inset 2px 2px 4px var(--main-shadow-dark),
    inset -2px -2px 4px var(--main-shadow-light);
}

.progress-bar {
  position: relative;
  width: 100%;
  height: 24px;
  background: var(--main-bg);
  border-radius: 12px;
  overflow: hidden;
  box-shadow:
    inset 3px 3px 6px var(--main-shadow-dark),
    inset -3px -3px 6px var(--main-shadow-light);
}

.progress-fill {
  height: 100%;
  background: linear-gradient(90deg, var(--main-primary), var(--main-primary-light));
  transition: width 0.3s;
  box-shadow:
    2px 2px 4px var(--main-shadow-dark),
    -2px -2px 4px var(--main-shadow-light);
}

.progress-text {
  position: absolute;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  font-size: 0.85em;
  font-weight: 700;
  color: var(--main-text);
}

.chart-container {
  padding: 20px 0;
  min-height: 300px;
}

.chart-bars {
  display: flex;
  align-items: flex-end;
  justify-content: space-around;
  height: 250px;
  gap: 6px;
}

.chart-bar-wrapper {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  min-width: 20px;
}

.chart-bar {
  width: 100%;
  background: linear-gradient(180deg, var(--main-primary-light), var(--main-primary));
  border-radius: 8px 8px 0 0;
  position: relative;
  min-height: 20px;
  transition: all 0.3s;
  cursor: pointer;
  box-shadow:
    3px 3px 6px var(--main-shadow-dark),
    -3px -3px 6px var(--main-shadow-light);
}

.chart-bar:hover {
  background: linear-gradient(180deg, #a5d6a7, #66bb6a);
  transform: translateY(-3px);
  box-shadow:
    5px 5px 10px var(--main-shadow-dark),
    -5px -5px 10px var(--main-shadow-light);
}

.bar-value {
  position: absolute;
  top: -20px;
  left: 50%;
  transform: translateX(-50%);
  font-size: 0.75em;
  font-weight: 700;
  white-space: nowrap;
  color: var(--main-text);
}

.bar-label {
  margin-top: 5px;
  font-size: 0.7em;
  color: var(--main-text-light);
  writing-mode: horizontal-tb;
  text-align: center;
  font-weight: 600;
}

.refresh-section {
  text-align: center;
  padding: 20px;
  display: flex;
  justify-content: center;
  align-items: center;
  gap: 20px;
}

.refresh-btn {
  padding: 12px 24px;
  background: linear-gradient(145deg, #e9eef5, #d1d9e6);
  color: var(--main-primary);
  border: none;
  border-radius: 12px;
  cursor: pointer;
  font-size: 16px;
  font-weight: 700;
  transition: all 0.3s;
}

.refresh-btn:hover {
  transform: translateY(-2px);
}

.refresh-btn:active {
  transform: translateY(0);
}

.last-update {
  color: var(--main-text-light);
  font-size: 14px;
  font-weight: 500;
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
    gap: 2px;
  }

  .bar-label {
    font-size: 0.6em;
  }
}

/* 模型使用統計區塊 */
.model-section {
  margin-bottom: 30px;
}

.model-section:last-child {
  margin-bottom: 0;
}

.model-type-title {
  font-size: 16px;
  font-weight: 700;
  color: var(--main-primary);
  margin-bottom: 12px;
  padding-bottom: 8px;
  border-bottom: 2px solid rgba(163, 177, 198, 0.3);
}

.no-data {
  text-align: center;
  padding: 30px;
  color: var(--main-text-light);
  font-style: italic;
}
</style>
