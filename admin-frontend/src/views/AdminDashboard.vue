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
      <!-- 線上使用者（即時輪詢；資料來自 user_presence，被動記錄 + TTL 自動清） -->
      <div class="stat-card online-card">
        <h2>
          <span class="live-dot" :class="{ stale: onlineError }"></span>
          線上使用者
        </h2>
        <div class="online-display">
          <span class="online-count">{{ onlineUsers === null ? '—' : formatNumber(onlineUsers) }}</span>
          <span class="online-unit">人在線</span>
        </div>
        <div class="stat-item">
          <span class="label">在線判定門檻</span>
          <select v-model.number="onlineWindow" @change="fetchOnline" class="window-select">
            <option :value="60">近 1 分鐘</option>
            <option :value="120">近 2 分鐘</option>
          </select>
        </div>
        <div v-if="onlineError" class="online-error">⚠️ {{ onlineError }}</div>
        <div v-else class="online-hint">每 {{ ONLINE_POLL_SECONDS }} 秒自動更新 · 最後更新 {{ onlineUpdate || '—' }}</div>
      </div>

      <!-- 線上人數趨勢（長期活躍峰值；資料來自 presence_rollup） -->
      <div class="stat-card full-width">
        <h2>
          線上人數趨勢
          <select v-model.number="historyDays" @change="fetchOnlineHistory" class="window-select" style="margin-left:auto">
            <option :value="1">近 1 天</option>
            <option :value="7">近 7 天</option>
            <option :value="30">近 30 天</option>
          </select>
        </h2>
        <div v-if="onlineHistory.length === 0" class="online-hint">
          尚無歷史資料（背景每分鐘抽樣、每小時彙整，累積一段時間後即可看到趨勢）
        </div>
        <template v-else>
          <div v-if="onlinePeak" class="peak-callout">
            歷史峰值 <strong>{{ formatNumber(onlinePeak.peak_online) }}</strong> 人同時在線
            <span class="peak-when">· {{ formatPeakAt(onlinePeak.peak_at) }}</span>
          </div>
          <div class="trend-chart">
            <div
              v-for="b in onlineHistory"
              :key="b.bucket"
              class="trend-bar-wrapper"
              :title="`${formatBucket(b.bucket_start)}：峰值 ${b.peak_online} 人（平均 ${b.avg_online}）`"
            >
              <div
                class="trend-bar"
                :class="{ peak: onlinePeak && b.bucket === onlinePeak.bucket }"
                :style="{ height: `${maxPeak ? (b.peak_online / maxPeak * 100) : 0}%` }"
              ></div>
            </div>
          </div>
        </template>
      </div>

      <!-- 收入總覽 -->
      <div v-if="revenue" class="stat-card revenue-highlight">
        <h2>收入</h2>
        <div class="mrr-display">
          <span class="mrr-amount">NT$ {{ formatNumber(revenue.mrr) }}</span>
          <span class="mrr-label">/月 (MRR)</span>
        </div>
        <div class="stat-item">
          <span class="label">累計收入：</span>
          <span class="value">NT$ {{ formatNumber(revenue.total_revenue) }}</span>
        </div>
        <div class="stat-item">
          <span class="label">額外額度收入：</span>
          <span class="value">NT$ {{ formatNumber(revenue.extra_quota_revenue) }}</span>
        </div>
        <div class="stat-item">
          <span class="label">待取消：</span>
          <span class="value" :class="{ 'danger': revenue.churn.pending_cancel > 0 }">{{ revenue.churn.pending_cancel }} 人</span>
        </div>
        <div class="stat-item">
          <span class="label">本月流失：</span>
          <span class="value" :class="{ 'danger': revenue.churn.expired_this_month > 0 }">{{ revenue.churn.expired_this_month }} 人</span>
        </div>
      </div>

      <!-- 訂閱分佈 -->
      <div v-if="revenue" class="stat-card">
        <h2>訂閱分佈</h2>
        <div class="subscriber-grid">
          <div class="sub-cell">
            <span class="sub-count">{{ revenue.subscriber_count.basic_monthly }}</span>
            <span class="sub-label">Basic 月繳</span>
          </div>
          <div class="sub-cell">
            <span class="sub-count">{{ revenue.subscriber_count.basic_yearly }}</span>
            <span class="sub-label">Basic 年繳</span>
          </div>
          <div class="sub-cell">
            <span class="sub-count">{{ revenue.subscriber_count.pro_monthly }}</span>
            <span class="sub-label">Pro 月繳</span>
          </div>
          <div class="sub-cell">
            <span class="sub-count">{{ revenue.subscriber_count.pro_yearly }}</span>
            <span class="sub-label">Pro 年繳</span>
          </div>
        </div>
        <div class="stat-item" style="margin-top: 12px;">
          <span class="label">付費用戶總計：</span>
          <span class="value">{{ totalSubscribers }} 人</span>
        </div>
      </div>

      <!-- 月收入趨勢 -->
      <div v-if="revenue && revenue.monthly_revenue.length > 0" class="stat-card wide">
        <h2>月收入趨勢</h2>
        <div class="revenue-chart">
          <div
            v-for="m in revenueChartData"
            :key="m.month"
            class="revenue-bar-wrapper"
          >
            <div class="revenue-bar" :style="{ height: m.height + '%' }">
              <span class="revenue-bar-amount">{{ formatNumber(m.amount) }}</span>
            </div>
            <span class="revenue-bar-label">{{ m.month.slice(5) }}月</span>
          </div>
        </div>
      </div>

      <!-- 近期訂單 -->
      <div v-if="revenue && revenue.recent_orders.length > 0" class="stat-card wide">
        <h2>近期付款</h2>
        <table class="data-table">
          <thead>
            <tr>
              <th>時間</th>
              <th>用戶</th>
              <th>類型</th>
              <th>方案</th>
              <th>金額</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="order in revenue.recent_orders" :key="order.order_no">
              <td>{{ formatOrderTime(order.paid_at) }}</td>
              <td>{{ order.user_email || '—' }}</td>
              <td>{{ orderTypeLabel(order.type) }}</td>
              <td>{{ order.tier || '—' }}</td>
              <td>NT$ {{ formatNumber(order.amount) }}</td>
            </tr>
          </tbody>
        </table>
      </div>

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

      <!-- 本月 AI 成本卡片（其他區間見「AI 成本」頁）-->
      <div class="stat-card wide">
        <h2>💰 本月 AI 成本
          <router-link to="/cost" class="card-link">查看其他區間 →</router-link>
        </h2>

        <!-- 總計 -->
        <div class="token-summary">
          <div class="token-total">
            <span class="total-label">本月總成本 (USD){{ monthCost ? '・' + monthCost.month : '' }}</span>
            <span class="total-value">{{ formatUsd(monthCost?.total_cost_usd) }}</span>
          </div>
          <div class="token-breakdown">
            <span>總 Token: {{ formatNumber(monthCost?.total_tokens) }}</span>
          </div>
          <div v-if="monthCost && monthCost.unpriced_tokens > 0" class="cost-estimate unpriced">
            ⚠️ 另有 {{ formatNumber(monthCost.unpriced_tokens) }} tokens 來自未收錄單價的模型，未計入成本
          </div>
        </div>

        <!-- 分類統計 -->
        <div class="token-categories">
          <!-- 標點強化 -->
          <div class="token-category">
            <h3>📝 標點強化</h3>
            <div class="stat-item">
              <span class="label">成本：</span>
              <span class="value highlight">{{ formatUsd(monthCost?.punctuation.cost_usd) }}</span>
            </div>
            <div class="stat-item">
              <span class="label">總 Token：</span>
              <span class="value">{{ formatNumber(monthCost?.punctuation.total_tokens) }}</span>
            </div>
            <div class="stat-item">
              <span class="label">輸入 / 輸出：</span>
              <span class="value">{{ formatNumber(monthCost?.punctuation.prompt_tokens) }} / {{ formatNumber(monthCost?.punctuation.completion_tokens) }}</span>
            </div>
          </div>

          <!-- AI 摘要 -->
          <div class="token-category">
            <h3>🤖 AI 摘要</h3>
            <div class="stat-item">
              <span class="label">成本：</span>
              <span class="value highlight">{{ formatUsd(monthCost?.summary.cost_usd) }}</span>
            </div>
            <div class="stat-item">
              <span class="label">總 Token：</span>
              <span class="value">{{ formatNumber(monthCost?.summary.total_tokens) }}</span>
            </div>
            <div class="stat-item">
              <span class="label">輸入 / 輸出：</span>
              <span class="value">{{ formatNumber(monthCost?.summary.prompt_tokens) }} / {{ formatNumber(monthCost?.summary.completion_tokens) }}</span>
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
          <h3 class="model-type-title">轉錄模型</h3>
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
import { ref, computed, onMounted, onUnmounted } from 'vue'
import api from '../utils/api'
import AdminNav from '../components/shared/AdminNav.vue'

// 線上人數輪詢間隔（秒）。presence 每人 30s 節流寫入、TTL 120s，15s 輪詢足夠即時又不吵。
const ONLINE_POLL_SECONDS = 15

const stats = ref({
  overview: {
    total_tasks: 0,
    completed_tasks: 0,
    processing_tasks: 0,
    failed_tasks: 0,
    success_rate: 0
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

const revenue = ref(null)
const monthCost = ref(null)

const loading = ref(true)
const error = ref(null)
const lastUpdate = ref('')

// 線上人數（獨立輪詢，不受 loading gate 影響）
const onlineUsers = ref(null)
const onlineWindow = ref(120)  // 秒；預設對齊 presence TTL（120s）
const onlineError = ref(null)
const onlineUpdate = ref('')
let onlineTimer = null

// 線上人數歷史趨勢（每小時 rollup；非即時，選單切換或掛載時抓）
const historyDays = ref(7)
const onlineHistory = ref([])
const onlinePeak = ref(null)
const maxPeak = computed(() => Math.max(...onlineHistory.value.map(b => b.peak_online), 1))

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

// 計算總摘要數（用於 AI 總結模型佔比）：由各模型使用次數加總得出
const totalSummaries = computed(() => {
  const models = stats.value.model_usage?.summary || []
  return models.reduce((sum, m) => sum + (m.count || 0), 0) || 1
})

// 訂閱者總數
const totalSubscribers = computed(() => {
  if (!revenue.value) return 0
  const c = revenue.value.subscriber_count
  return c.basic_monthly + c.basic_yearly + c.pro_monthly + c.pro_yearly
})

// 月收入圖表數據（反轉為時間正序 + 計算高度百分比）
const revenueChartData = computed(() => {
  if (!revenue.value) return []
  const data = [...revenue.value.monthly_revenue].reverse()
  const max = Math.max(...data.map(d => d.amount), 1)
  return data.map(d => ({
    ...d,
    height: Math.max((d.amount / max) * 100, 4),
  }))
})

// 獲取收入資料
async function fetchRevenue() {
  try {
    const response = await api.get('/api/admin/revenue')
    revenue.value = response.data
  } catch (err) {
    console.error('載入收入資料失敗:', err)
  }
}

// 本月 AI 成本（沿用 /admin/cost 取當月；其他區間見「AI 成本」頁）
async function fetchMonthCost() {
  try {
    const response = await api.get('/api/admin/cost', { params: { months: 1 } })
    const months = response.data.months || []
    monthCost.value = months.length ? months[months.length - 1] : null
  } catch (err) {
    console.error('載入本月成本失敗:', err)
  }
}

function formatOrderTime(ts) {
  if (!ts) return '—'
  return new Date(ts * 1000).toLocaleString('zh-TW', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
}

function orderTypeLabel(type) {
  const map = { subscription: '訂閱', upgrade_subscription: '升級', downgrade_subscription: '降級', extra_quota: '額外額度' }
  return map[type] || type
}

// 獲取線上人數（輪詢呼叫，失敗只記在卡片上、不干擾整頁）
async function fetchOnline() {
  try {
    const response = await api.get('/api/admin/stats/online', {
      params: { window_seconds: onlineWindow.value },
    })
    onlineUsers.value = response.data.online_users
    onlineError.value = null
    onlineUpdate.value = new Date().toLocaleTimeString('zh-TW')
  } catch (err) {
    onlineError.value = err.response?.data?.detail || err.message || '載入失敗'
    console.error('載入線上人數失敗:', err)
  }
}

// 獲取線上人數歷史（趨勢圖用）
async function fetchOnlineHistory() {
  try {
    const response = await api.get('/api/admin/stats/online/history', {
      params: { days: historyDays.value },
    })
    onlineHistory.value = response.data.buckets || []
    onlinePeak.value = response.data.peak || null
  } catch (err) {
    console.error('載入線上人數歷史失敗:', err)
  }
}

// 桶時間（趨勢圖 tooltip / x 軸）：後端回 UTC ISO，瀏覽器轉本地時區顯示
function formatBucket(iso) {
  if (!iso) return ''
  return new Date(iso).toLocaleString('zh-TW', { month: '2-digit', day: '2-digit', hour: '2-digit' })
}

// 峰值發生時間（精確到分）
function formatPeakAt(iso) {
  if (!iso) return '—'
  return new Date(iso).toLocaleString('zh-TW', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
}

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

// 格式化美金：小額顯示 4 位小數、較大顯示 2 位
function formatUsd(n) {
  if (n === undefined || n === null) return '$0.00'
  const digits = Math.abs(n) < 1 ? 4 : 2
  return '$' + n.toLocaleString('en-US', { minimumFractionDigits: digits, maximumFractionDigits: digits })
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
  fetchRevenue()
  fetchMonthCost()
  fetchOnline()
  fetchOnlineHistory()
  onlineTimer = setInterval(fetchOnline, ONLINE_POLL_SECONDS * 1000)
})

onUnmounted(() => {
  if (onlineTimer) clearInterval(onlineTimer)
})
</script>

<style scoped>
.admin-container {
  max-width: none;
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
  grid-auto-flow: row dense;
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

/* 線上人數卡片 */
.online-display {
  display: flex;
  align-items: baseline;
  gap: 8px;
  margin: 8px 0 12px;
}

.online-count {
  font-size: 2.5rem;
  font-weight: 800;
  line-height: 1;
  color: var(--color-primary, #dd8448);
}

.online-unit {
  font-size: 14px;
  font-weight: 600;
  color: var(--color-text-light, #a0917c);
}

.live-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  background: #2e7d32;
  display: inline-block;
  animation: live-pulse 2s infinite;
}

.live-dot.stale {
  background: #c62828;
  animation: none;
}

@keyframes live-pulse {
  0%   { box-shadow: 0 0 0 0 rgba(46, 125, 50, 0.45); }
  70%  { box-shadow: 0 0 0 8px rgba(46, 125, 50, 0); }
  100% { box-shadow: 0 0 0 0 rgba(46, 125, 50, 0); }
}

.window-select {
  border: 1px solid rgba(163, 177, 198, 0.4);
  border-radius: 8px;
  padding: 4px 8px;
  font-size: 14px;
  font-weight: 600;
  color: var(--color-text, rgb(145, 106, 45));
  background: white;
  cursor: pointer;
}

.online-hint {
  margin-top: 12px;
  font-size: 12px;
  color: var(--color-text-light, #a0917c);
}

.online-error {
  margin-top: 12px;
  font-size: 13px;
  font-weight: 600;
  color: #c62828;
}

/* 線上人數趨勢圖 */
.peak-callout {
  margin-bottom: 14px;
  padding: 10px 14px;
  background: #fff8f3;
  border: 1px solid rgba(221, 132, 72, 0.2);
  border-radius: 10px;
  font-size: 14px;
  color: var(--color-primary-dark, #b8762d);
}

.peak-callout strong {
  font-size: 1.2em;
  color: var(--color-primary, #dd8448);
}

.peak-when {
  color: var(--color-text-light, #a0917c);
  font-weight: 500;
}

.trend-chart {
  display: flex;
  align-items: flex-end;
  gap: 1px;
  height: 160px;
  padding-top: 8px;
}

.trend-bar-wrapper {
  flex: 1 1 0;
  min-width: 0;
  height: 100%;
  display: flex;
  align-items: flex-end;
}

.trend-bar {
  width: 100%;
  min-height: 1px;
  background: rgba(221, 132, 72, 0.35);
  border-radius: 2px 2px 0 0;
  transition: height 0.2s ease;
}

.trend-bar.peak {
  background: var(--color-primary, #dd8448);
}

.trend-bar:hover {
  background: rgba(221, 132, 72, 0.6);
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

.cost-estimate.unpriced {
  background: #fff8e1;
  border-color: rgba(233, 118, 12, 0.35);
  color: #9a5b00;
  font-size: 13px;
}

.card-link {
  margin-left: auto;
  font-size: 12px;
  font-weight: 600;
  color: var(--color-primary, #dd8448);
  text-decoration: none;
}

.card-link:hover {
  text-decoration: underline;
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
  justify-content: flex-end;
  min-width: 16px;
  max-width: 40px;
  height: 200px;
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

/* Revenue section */
.revenue-highlight {
  border-left: 4px solid var(--color-primary, #dd8448);
}

.mrr-display {
  margin-bottom: 16px;
  display: flex;
  align-items: baseline;
  gap: 6px;
}

.mrr-amount {
  font-size: 28px;
  font-weight: 800;
  color: var(--color-primary, #dd8448);
}

.mrr-label {
  font-size: 14px;
  color: #888;
}

.subscriber-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
}

.sub-cell {
  text-align: center;
  padding: 12px;
  background: #f8f9fa;
  border-radius: 8px;
}

.sub-count {
  display: block;
  font-size: 24px;
  font-weight: 700;
  color: #333;
}

.sub-label {
  display: block;
  font-size: 12px;
  color: #888;
  margin-top: 4px;
}

.revenue-chart {
  display: flex;
  align-items: flex-end;
  gap: 12px;
  height: 140px;
  padding-top: 20px;
}

.revenue-bar-wrapper {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  height: 100%;
  justify-content: flex-end;
}

.revenue-bar {
  width: 100%;
  max-width: 60px;
  background: var(--color-primary, #dd8448);
  border-radius: 4px 4px 0 0;
  position: relative;
  min-height: 4px;
  opacity: 0.85;
  transition: opacity 0.2s;
}

.revenue-bar:hover {
  opacity: 1;
}

.revenue-bar-amount {
  position: absolute;
  top: -20px;
  left: 50%;
  transform: translateX(-50%);
  font-size: 11px;
  color: #666;
  white-space: nowrap;
}

.revenue-bar-label {
  margin-top: 6px;
  font-size: 12px;
  color: #888;
}
</style>
