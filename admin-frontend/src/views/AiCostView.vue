<template>
  <div class="admin-container">
    <AdminNav />

    <h1 class="admin-title">AI 成本統計</h1>

    <div class="controls">
      <label>統計區間：</label>
      <select v-model.number="months" @change="fetchCost" class="range-select">
        <option :value="3">近 3 個月</option>
        <option :value="6">近 6 個月</option>
        <option :value="12">近 12 個月</option>
        <option :value="24">近 24 個月</option>
      </select>
    </div>

    <div v-if="loading" class="loading">
      <div class="spinner"></div>
      <p>載入成本資料中...</p>
    </div>

    <div v-else-if="error" class="error-message">
      ❌ {{ error }}
    </div>

    <div v-else-if="cost" class="stats-grid">
      <!-- 未計價提醒 -->
      <div v-if="cost.totals.unpriced_tokens > 0" class="stat-card full-width unpriced-alert">
        ⚠️ 有 {{ formatNumber(cost.totals.unpriced_tokens) }} tokens 來自單價表未收錄的模型，未計入下方成本。
        請更新 <code>llm_pricing.py</code> 的單價表後重新查看。
      </div>

      <!-- 期間總成本 -->
      <div class="stat-card wide">
        <h2>💰 期間總成本（{{ cost.range_months }} 個月）</h2>
        <div class="token-summary">
          <div class="token-total">
            <span class="total-label">總成本 (USD)</span>
            <span class="total-value">{{ formatUsd(cost.totals.total_cost_usd) }}</span>
          </div>
          <div class="token-breakdown">
            <span>總 Token: {{ formatNumber(cost.totals.total_tokens) }}</span>
          </div>
        </div>
        <div class="token-categories">
          <div class="token-category">
            <h3>📝 標點強化</h3>
            <div class="stat-item">
              <span class="label">成本：</span>
              <span class="value highlight">{{ formatUsd(cost.totals.punctuation.cost_usd) }}</span>
            </div>
            <div class="stat-item">
              <span class="label">總 Token：</span>
              <span class="value">{{ formatNumber(cost.totals.punctuation.total_tokens) }}</span>
            </div>
            <div class="stat-item">
              <span class="label">輸入 / 輸出：</span>
              <span class="value">{{ formatNumber(cost.totals.punctuation.prompt_tokens) }} / {{ formatNumber(cost.totals.punctuation.completion_tokens) }}</span>
            </div>
          </div>
          <div class="token-category">
            <h3>🤖 AI 摘要</h3>
            <div class="stat-item">
              <span class="label">成本：</span>
              <span class="value highlight">{{ formatUsd(cost.totals.summary.cost_usd) }}</span>
            </div>
            <div class="stat-item">
              <span class="label">總 Token：</span>
              <span class="value">{{ formatNumber(cost.totals.summary.total_tokens) }}</span>
            </div>
            <div class="stat-item">
              <span class="label">輸入 / 輸出：</span>
              <span class="value">{{ formatNumber(cost.totals.summary.prompt_tokens) }} / {{ formatNumber(cost.totals.summary.completion_tokens) }}</span>
            </div>
          </div>
        </div>
      </div>

      <!-- 每月成本趨勢 -->
      <div class="stat-card wide">
        <h2>📈 每月成本趨勢 (USD)</h2>
        <div v-if="hasCost" class="revenue-chart">
          <div
            v-for="m in monthlyChartData"
            :key="m.month"
            class="revenue-bar-wrapper"
          >
            <div class="revenue-bar" :style="{ height: m.height + '%' }" :title="formatUsd(m.total_cost_usd)">
              <span class="revenue-bar-amount">{{ formatUsd(m.total_cost_usd) }}</span>
            </div>
            <span class="revenue-bar-label">{{ m.month.slice(5) }}月</span>
          </div>
        </div>
        <div v-else class="no-data">此區間尚無成本資料</div>
      </div>

      <!-- 逐月明細 -->
      <div class="stat-card full-width">
        <h2>📅 逐月明細</h2>
        <table class="data-table">
          <thead>
            <tr>
              <th>月份</th>
              <th>標點成本</th>
              <th>摘要成本</th>
              <th>總成本</th>
              <th>總 Token</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="m in cost.months" :key="m.month">
              <td>{{ m.month }}</td>
              <td>{{ formatUsd(m.punctuation.cost_usd) }}</td>
              <td>{{ formatUsd(m.summary.cost_usd) }}</td>
              <td class="highlight">{{ formatUsd(m.total_cost_usd) }}</td>
              <td>{{ formatNumber(m.total_tokens) }}</td>
            </tr>
          </tbody>
          <tfoot>
            <tr>
              <td><strong>合計</strong></td>
              <td>{{ formatUsd(cost.totals.punctuation.cost_usd) }}</td>
              <td>{{ formatUsd(cost.totals.summary.cost_usd) }}</td>
              <td class="highlight">{{ formatUsd(cost.totals.total_cost_usd) }}</td>
              <td>{{ formatNumber(cost.totals.total_tokens) }}</td>
            </tr>
          </tfoot>
        </table>
      </div>

      <!-- 各模型成本明細 -->
      <div class="stat-card wide">
        <h2>🧮 各模型成本（期間合計）</h2>
        <table v-if="modelRows.length > 0" class="data-table">
          <thead>
            <tr>
              <th>功能</th>
              <th>模型</th>
              <th>總 Token</th>
              <th>輸入 / 輸出</th>
              <th>次數</th>
              <th>成本</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in modelRows" :key="row.feature + '-' + row.model">
              <td>{{ row.feature }}</td>
              <td><code>{{ row.model }}</code>
                <span v-if="!row.priced" class="badge-unpriced">未計價</span>
              </td>
              <td>{{ formatNumber(row.total_tokens) }}</td>
              <td>{{ formatNumber(row.prompt_tokens) }} / {{ formatNumber(row.completion_tokens) }}</td>
              <td>{{ row.count }}</td>
              <td class="highlight">{{ formatUsd(row.cost_usd) }}</td>
            </tr>
          </tbody>
        </table>
        <div v-else class="no-data">此區間尚無模型資料</div>
      </div>

      <!-- 單價參考 -->
      <div class="stat-card wide">
        <h2>🏷️ 單價參考</h2>
        <p class="pricing-meta">
          {{ cost.pricing.unit }}；查證日期 {{ cost.pricing.verified_at }}
        </p>
        <table class="data-table">
          <thead>
            <tr>
              <th>模型</th>
              <th>輸入 ($/1M)</th>
              <th>輸出 ($/1M)</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(price, model) in cost.pricing.models" :key="model">
              <td><code>{{ model }}</code></td>
              <td>${{ price.input }}</td>
              <td>${{ price.output }}</td>
            </tr>
          </tbody>
        </table>
        <ul class="assumptions">
          <li v-for="(a, i) in cost.pricing.assumptions" :key="i">{{ a }}</li>
        </ul>
      </div>

      <!-- 說明 -->
      <div class="stat-card full-width notes-card">
        <h2>ℹ️ 說明</h2>
        <ul class="notes">
          <li v-for="(n, i) in cost.notes" :key="i">{{ n }}</li>
        </ul>
      </div>
    </div>

    <div class="refresh-section">
      <button @click="fetchCost" class="refresh-btn">🔄 刷新資料</button>
      <span class="last-update">最後更新：{{ lastUpdate }}</span>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import api from '../utils/api'
import AdminNav from '../components/shared/AdminNav.vue'

const cost = ref(null)
const months = ref(6)
const loading = ref(true)
const error = ref(null)
const lastUpdate = ref('')

// 是否有任何非零成本（決定趨勢圖 vs 空狀態）
const hasCost = computed(() =>
  !!cost.value && cost.value.months.some(m => m.total_tokens > 0)
)

// 每月成本趨勢（後端已回時間正序；算高度百分比、保底 4%）
const monthlyChartData = computed(() => {
  if (!cost.value) return []
  const data = cost.value.months
  const max = Math.max(...data.map(m => m.total_cost_usd), 0.0001)
  return data.map(m => ({
    ...m,
    height: Math.max((m.total_cost_usd / max) * 100, 4),
  }))
})

// 攤平各模型成本（標點 + 摘要），依成本高到低
const modelRows = computed(() => {
  const t = cost.value?.totals
  if (!t) return []
  const rows = []
  for (const [key, label] of [['punctuation', '標點'], ['summary', '摘要']]) {
    for (const m of t[key].models) rows.push({ feature: label, ...m })
  }
  rows.sort((a, b) => b.cost_usd - a.cost_usd)
  return rows
})

async function fetchCost() {
  loading.value = true
  error.value = null
  try {
    const response = await api.get('/api/admin/cost', { params: { months: months.value } })
    cost.value = response.data
    lastUpdate.value = new Date().toLocaleString('zh-TW')
  } catch (err) {
    error.value = err.response?.data?.detail || err.message || '載入失敗'
    console.error('載入 AI 成本失敗:', err)
  } finally {
    loading.value = false
  }
}

// 格式化數字（千分位）
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

onMounted(fetchCost)
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
  margin-bottom: 20px;
  font-weight: 700;
  font-size: 1.75rem;
}

.controls {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
  margin-bottom: 24px;
  color: var(--color-text-light, #a0917c);
  font-size: 14px;
}

.range-select {
  padding: 8px 12px;
  border-radius: 8px;
  border: 1px solid rgba(163, 177, 198, 0.4);
  background: white;
  color: var(--color-text, rgb(145, 106, 45));
  font-size: 14px;
  cursor: pointer;
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

.stat-card.wide { grid-column: span 2; }
.stat-card.full-width { grid-column: 1 / -1; }

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

.stat-item:last-child { border-bottom: none; }

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

.value.highlight {
  color: var(--color-primary, #dd8448);
  font-size: 1.1em;
}

/* 未計價提醒 */
.unpriced-alert {
  background: #fff8e1;
  border: 1px solid rgba(233, 118, 12, 0.35);
  color: #9a5b00;
  font-weight: 600;
  font-size: 14px;
}

.unpriced-alert code {
  background: rgba(0, 0, 0, 0.06);
  padding: 2px 6px;
  border-radius: 6px;
}

/* 總成本摘要 */
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

/* 表格 */
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

.data-table tbody tr:hover { background: rgba(221, 132, 72, 0.04); }

.data-table tfoot td {
  border-top: 2px solid rgba(163, 177, 198, 0.3);
  font-weight: 700;
  color: var(--color-text, rgb(145, 106, 45));
}

.data-table td.highlight {
  font-weight: 700;
  color: var(--color-primary, #dd8448);
}

.data-table code {
  background: #f5f5f5;
  padding: 4px 8px;
  border-radius: 6px;
  font-size: 12px;
  color: var(--color-text-muted, #4a6680);
}

.badge-unpriced {
  margin-left: 6px;
  padding: 2px 6px;
  border-radius: 6px;
  background: #fff3e0;
  color: #9a5b00;
  font-size: 11px;
  font-weight: 600;
}

/* 每月趨勢 bar chart */
.revenue-chart {
  display: flex;
  align-items: flex-end;
  gap: 12px;
  height: 160px;
  padding-top: 24px;
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

.revenue-bar:hover { opacity: 1; }

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

/* 單價 / 說明 */
.pricing-meta {
  font-size: 13px;
  color: var(--color-text-light, #a0917c);
  margin-bottom: 12px;
}

.assumptions,
.notes {
  margin: 12px 0 0;
  padding-left: 20px;
  font-size: 13px;
  color: var(--color-text-light, #a0917c);
  line-height: 1.8;
}

.notes-card { border-left: 4px solid rgba(163, 177, 198, 0.4); }

.no-data {
  text-align: center;
  padding: 30px;
  color: var(--color-text-light, #a0917c);
}

/* 刷新 */
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

@media (max-width: 768px) {
  .stats-grid { grid-template-columns: 1fr; }
  .stat-card.wide,
  .stat-card.full-width { grid-column: 1; }
  .token-categories { grid-template-columns: 1fr; }
  .data-table { font-size: 12px; }
  .data-table th,
  .data-table td { padding: 8px 4px; }
}
</style>
