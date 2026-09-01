<template>
  <div class="orders-container">
    <AdminNav />

    <h1 class="page-title">訂單 / 發票</h1>

    <!-- 篩選器（骨架抄 AuditLogsView：preset 時間區間 + URL 同步） -->
    <div class="filters">
      <div class="filter-item">
        <label>建單時間：</label>
        <select v-model="preset" @change="onPresetChange" class="filter-select">
          <option value="all">全部</option>
          <option value="7d">近 7 天</option>
          <option value="30d">近 30 天</option>
          <option value="90d">近 90 天</option>
          <option value="custom">自訂區間</option>
        </select>
      </div>
      <template v-if="preset === 'custom'">
        <div class="filter-item">
          <label>起：</label>
          <input type="date" v-model="dateFrom" @change="applyFilters" class="filter-input date" />
        </div>
        <div class="filter-item">
          <label>迄：</label>
          <input type="date" v-model="dateTo" @change="applyFilters" class="filter-input date" />
        </div>
      </template>

      <div class="filter-item">
        <label>Email：</label>
        <input
          v-model="email"
          @keyup.enter="applyFilters"
          placeholder="用戶 email"
          class="filter-input"
        />
      </div>

      <div class="filter-item">
        <label>訂單狀態：</label>
        <select v-model="status" @change="applyFilters" class="filter-select">
          <option value="">全部</option>
          <option value="pending">pending</option>
          <option value="paid">paid</option>
          <option value="failed">failed</option>
          <option value="expired">expired</option>
          <option value="superseded">superseded</option>
        </select>
      </div>

      <div class="filter-item">
        <label>類型：</label>
        <select v-model="type" @change="applyFilters" class="filter-select">
          <option value="">全部</option>
          <option value="subscription">subscription</option>
          <option value="upgrade_subscription">upgrade_subscription</option>
          <option value="renewal">renewal</option>
          <option value="extra_quota">extra_quota</option>
        </select>
      </div>

      <div class="filter-item">
        <label>方案：</label>
        <select v-model="tier" @change="applyFilters" class="filter-select">
          <option value="">全部</option>
          <option value="basic">basic</option>
          <option value="pro">pro</option>
        </select>
      </div>

      <div class="filter-item">
        <label>發票狀態：</label>
        <select v-model="invoiceStatus" @change="applyFilters" class="filter-select">
          <option value="">全部</option>
          <option value="none">尚無發票</option>
          <option value="issued">issued</option>
          <option value="pending">pending</option>
          <option value="failed">failed</option>
          <option value="needs_manual">needs_manual</option>
          <option value="voided">voided</option>
        </select>
      </div>

      <button @click="applyFilters" class="filter-btn">🔍 套用篩選</button>
      <button @click="clearFilters" class="filter-btn secondary">✕ 清除</button>
    </div>

    <div v-if="loading" class="loading">
      <div class="spinner"></div>
      <p>載入訂單中...</p>
    </div>

    <div v-else-if="error" class="error-message">{{ error }}</div>

    <div v-else class="orders-section">
      <div class="orders-header">
        <span class="total-count">共 {{ total }} 筆（第 {{ currentPage }} / {{ totalPages }} 頁）</span>
        <button @click="fetchOrders" class="refresh-btn">🔄 刷新</button>
      </div>

      <div v-if="orders.length === 0" class="empty-state">📭 沒有符合條件的訂單</div>

      <div v-else class="orders-table-wrapper">
        <table class="orders-table">
          <thead>
            <tr>
              <th></th>
              <th>訂單號</th>
              <th>Email</th>
              <th>類型</th>
              <th>方案 / 週期</th>
              <th>金額</th>
              <th>訂單狀態</th>
              <th>付款時間</th>
              <th>發票狀態</th>
            </tr>
          </thead>
          <tbody>
            <template v-for="order in orders" :key="order.order_no">
              <tr class="order-row" @click="toggleExpand(order.order_no)">
                <td class="expand-col">{{ expanded === order.order_no ? '▾' : '▸' }}</td>
                <td class="order-no">{{ order.order_no }}</td>
                <td>{{ order.user_email || '-' }}</td>
                <td>{{ order.type || '-' }}</td>
                <td>{{ formatPlan(order) }}</td>
                <td class="amount">{{ formatAmount(order.amount_twd) }}</td>
                <td>
                  <span class="status-badge" :class="`order-status-${order.status}`">{{ order.status }}</span>
                </td>
                <td class="timestamp">{{ formatTimestamp(order.paid_at) }}</td>
                <td>
                  <span class="status-badge" :class="invoiceBadgeClass(order.invoice)">
                    {{ invoiceBadgeLabel(order.invoice) }}
                  </span>
                </td>
              </tr>
              <tr v-if="expanded === order.order_no" class="detail-row">
                <td :colspan="9">
                  <OrderDetailPanel :order-no="order.order_no" @changed="fetchOrders" />
                </td>
              </tr>
            </template>
          </tbody>
        </table>
      </div>

      <div class="pagination">
        <button @click="previousPage" :disabled="currentPage === 1" class="page-btn">← 上一頁</button>
        <span class="page-info">第 {{ currentPage }} / {{ totalPages }} 頁（每頁 {{ pageSize }} 筆）</span>
        <button @click="nextPage" :disabled="currentPage >= totalPages" class="page-btn">下一頁 →</button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import api from '../utils/api'
import AdminNav from '../components/shared/AdminNav.vue'
import OrderDetailPanel from '../components/orders/OrderDetailPanel.vue'

const route = useRoute()
const router = useRouter()

const orders = ref([])
const total = ref(0)
const loading = ref(true)
const error = ref(null)
const currentPage = ref(1)
const pageSize = ref(50)
const expanded = ref(null)

const preset = ref('all')
const dateFrom = ref('')
const dateTo = ref('')
const email = ref('')
const status = ref('')
const type = ref('')
const tier = ref('')
const invoiceStatus = ref('')

const totalPages = computed(() => Math.max(1, Math.ceil(total.value / pageSize.value)))

// 用本地日期（非 toISOString 的 UTC 日期）——否則台北時間 00:00–08:00 這段，
// toISOString() 換算出的 UTC 日期還是「昨天」，會把當天剛建立的訂單篩掉。
function formatLocalDate(date) {
  const y = date.getFullYear()
  const m = String(date.getMonth() + 1).padStart(2, '0')
  const d = String(date.getDate()).padStart(2, '0')
  return `${y}-${m}-${d}`
}

function computeRange() {
  if (preset.value === 'all') return { from: '', to: '' }
  if (preset.value === 'custom') return { from: dateFrom.value, to: dateTo.value }
  const days = { '7d': 7, '30d': 30, '90d': 90 }[preset.value] || 30
  const to = new Date()
  const from = new Date(to.getTime() - days * 86400000)
  return { from: formatLocalDate(from), to: formatLocalDate(to) }
}

function buildParams() {
  const { from, to } = computeRange()
  const p = { skip: (currentPage.value - 1) * pageSize.value, limit: pageSize.value }
  if (from) p.date_from = from
  if (to) p.date_to = to
  if (email.value.trim()) p.email = email.value.trim()
  if (status.value) p.status = status.value
  if (type.value) p.type = type.value
  if (tier.value) p.tier = tier.value
  if (invoiceStatus.value) p.invoice_status = invoiceStatus.value
  return p
}

function syncToUrl() {
  const q = { preset: preset.value }
  if (preset.value === 'custom') {
    if (dateFrom.value) q.date_from = dateFrom.value
    if (dateTo.value) q.date_to = dateTo.value
  }
  if (email.value.trim()) q.email = email.value.trim()
  if (status.value) q.status = status.value
  if (type.value) q.type = type.value
  if (tier.value) q.tier = tier.value
  if (invoiceStatus.value) q.invoice_status = invoiceStatus.value
  if (currentPage.value > 1) q.page = String(currentPage.value)
  router.replace({ query: q }).catch(() => {})
}

function hydrateFromUrl() {
  const q = route.query
  if (q.preset) preset.value = q.preset
  if (q.date_from) dateFrom.value = q.date_from
  if (q.date_to) dateTo.value = q.date_to
  if (q.email) email.value = q.email
  if (q.status) status.value = q.status
  if (q.type) type.value = q.type
  if (q.tier) tier.value = q.tier
  if (q.invoice_status) invoiceStatus.value = q.invoice_status
  if (q.page) currentPage.value = Math.max(1, parseInt(q.page, 10) || 1)
}

async function fetchOrders() {
  loading.value = true
  error.value = null
  try {
    const response = await api.get('/api/admin/orders', { params: buildParams() })
    orders.value = response.data.orders || []
    total.value = response.data.total || 0
  } catch (err) {
    error.value = err.response?.data?.detail?.message || err.response?.data?.detail || err.message || '載入失敗'
  } finally {
    loading.value = false
  }
}

function applyFilters() {
  currentPage.value = 1
  syncToUrl()
  fetchOrders()
}

function onPresetChange() {
  if (preset.value !== 'custom') {
    dateFrom.value = ''
    dateTo.value = ''
  }
  applyFilters()
}

function clearFilters() {
  preset.value = 'all'
  dateFrom.value = ''
  dateTo.value = ''
  email.value = ''
  status.value = ''
  type.value = ''
  tier.value = ''
  invoiceStatus.value = ''
  applyFilters()
}

function previousPage() {
  if (currentPage.value > 1) {
    currentPage.value--
    syncToUrl()
    fetchOrders()
  }
}

function nextPage() {
  if (currentPage.value < totalPages.value) {
    currentPage.value++
    syncToUrl()
    fetchOrders()
  }
}

function toggleExpand(orderNo) {
  expanded.value = expanded.value === orderNo ? null : orderNo
}

function formatPlan(order) {
  if (order.type === 'extra_quota') return '加購'
  if (!order.tier) return '-'
  return order.billing_cycle ? `${order.tier} / ${order.billing_cycle}` : order.tier
}

function formatAmount(amount) {
  if (amount === null || amount === undefined) return '-'
  return `NT$ ${amount.toLocaleString()}`
}

function formatTimestamp(ts) {
  if (!ts) return '-'
  return new Date(ts * 1000).toLocaleString('zh-TW')
}

// 發票狀態 badge：issued=綠、pending/failed=黃、needs_manual=紅、voided=灰、無=–
function invoiceBadgeClass(invoice) {
  if (!invoice) return 'invoice-status-none'
  return `invoice-status-${invoice.status}`
}

function invoiceBadgeLabel(invoice) {
  if (!invoice) return '–'
  return invoice.status
}

onMounted(() => {
  hydrateFromUrl()
  fetchOrders()
})
</script>

<style scoped>
.orders-container {
  max-width: none;
  margin: 0 auto;
  padding: 0 20px 40px;
}

.page-title {
  text-align: center;
  color: var(--color-text, rgb(145, 106, 45));
  margin-bottom: 24px;
  font-weight: 700;
  font-size: 1.75rem;
}

.filters {
  display: flex;
  gap: 12px;
  align-items: center;
  background: white;
  padding: 16px 20px;
  border-radius: 12px;
  margin-bottom: 20px;
  flex-wrap: wrap;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.06);
  border: 1px solid rgba(163, 177, 198, 0.2);
}

.filter-item { display: flex; align-items: center; gap: 8px; }
.filter-item label { font-weight: 600; color: var(--color-text, rgb(145, 106, 45)); white-space: nowrap; font-size: 14px; }

.filter-select, .filter-input {
  padding: 8px 12px;
  border: 1px solid rgba(163, 177, 198, 0.3);
  border-radius: 8px;
  background: white;
  color: var(--color-text, rgb(145, 106, 45));
  font-size: 14px;
  outline: none;
}

.filter-select { min-width: 140px; }
.filter-input { min-width: 180px; }
.filter-input.date { min-width: 140px; }

.filter-btn {
  padding: 8px 16px;
  background: var(--color-primary, #dd8448);
  color: white;
  border: none;
  border-radius: 8px;
  cursor: pointer;
  font-size: 13px;
  font-weight: 600;
}

.filter-btn.secondary { background: #fff5f5; color: #c62828; border: 1px solid rgba(198, 40, 40, 0.2); }

.loading, .error-message { text-align: center; padding: 40px; font-size: 16px; }

.spinner {
  border: 4px solid transparent;
  border-top: 4px solid var(--main-primary);
  border-radius: 50%;
  width: 40px;
  height: 40px;
  animation: spin 1s linear infinite;
  margin: 0 auto 20px;
}

@keyframes spin { 0% { transform: rotate(0deg); } 100% { transform: rotate(360deg); } }

.orders-section {
  background: white;
  border-radius: 12px;
  padding: 20px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.06);
  border: 1px solid rgba(163, 177, 198, 0.2);
}

.orders-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; }
.total-count { font-weight: 600; color: var(--color-text, rgb(145, 106, 45)); font-size: 14px; }

.refresh-btn {
  padding: 8px 14px;
  background: var(--color-primary, #dd8448);
  color: white;
  border: none;
  border-radius: 8px;
  cursor: pointer;
  font-size: 13px;
  font-weight: 600;
}

.empty-state { text-align: center; padding: 60px; font-size: 16px; color: var(--color-text-light, #a0917c); }

.orders-table-wrapper { overflow-x: auto; border-radius: 8px; border: 1px solid rgba(163, 177, 198, 0.15); }

.orders-table { width: 100%; border-collapse: collapse; font-size: 13px; }

.orders-table th {
  background: #fafafa;
  padding: 12px;
  text-align: left;
  font-weight: 600;
  color: var(--color-text, rgb(145, 106, 45));
  border-bottom: 1px solid rgba(163, 177, 198, 0.2);
  white-space: nowrap;
  font-size: 12px;
}

.orders-table td { padding: 10px 12px; border-bottom: 1px solid rgba(163, 177, 198, 0.1); color: var(--color-text, rgb(145, 106, 45)); }

.order-row { cursor: pointer; }
.order-row:hover { background: rgba(221, 132, 72, 0.04); }
.expand-col { width: 20px; color: var(--color-text-light, #a0917c); }
.order-no { font-family: monospace; font-size: 12px; }
.amount { text-align: right; font-variant-numeric: tabular-nums; }
.timestamp { white-space: nowrap; font-size: 12px; color: var(--color-text-light, #a0917c); }

.detail-row td { padding: 0; background: #fafafa; }

.status-badge {
  display: inline-block;
  padding: 3px 8px;
  border-radius: 4px;
  font-size: 11px;
  font-weight: 600;
}

.order-status-paid { background: #d4edda; color: #155724; }
.order-status-pending { background: #fff3cd; color: #856404; }
.order-status-failed { background: #ffebee; color: #c62828; }
.order-status-expired,
.order-status-superseded { background: #f5f5f5; color: #757575; }

.invoice-status-issued { background: #d4edda; color: #155724; }
.invoice-status-pending,
.invoice-status-failed { background: #fff3cd; color: #856404; }
.invoice-status-needs_manual { background: #ffebee; color: #c62828; }
.invoice-status-voided { background: #f5f5f5; color: #757575; }
.invoice-status-none { background: transparent; color: var(--color-text-light, #a0917c); }

.pagination {
  display: flex;
  justify-content: center;
  align-items: center;
  gap: 16px;
  margin-top: 24px;
  padding-top: 20px;
  border-top: 1px solid rgba(163, 177, 198, 0.2);
}

.page-btn {
  padding: 8px 16px;
  background: var(--color-primary, #dd8448);
  color: white;
  border: none;
  border-radius: 8px;
  cursor: pointer;
  font-size: 13px;
  font-weight: 600;
}

.page-btn:disabled { opacity: 0.5; cursor: not-allowed; }
.page-info { font-weight: 500; color: var(--color-text, rgb(145, 106, 45)); font-size: 13px; }
</style>
