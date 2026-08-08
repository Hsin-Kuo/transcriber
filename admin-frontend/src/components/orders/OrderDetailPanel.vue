<template>
  <div class="detail-panel">
    <div v-if="loading" class="detail-loading">載入中...</div>
    <div v-else-if="error" class="detail-error">{{ error }}</div>
    <div v-else-if="detail" class="detail-body">
      <div class="order-fields">
        <div class="field"><span class="label">訂單號</span><span class="value">{{ detail.order.merchant_order_no }}</span></div>
        <div class="field"><span class="label">用戶</span><span class="value">{{ detail.order.user_email || detail.order.user_id }}</span></div>
        <div class="field"><span class="label">類型</span><span class="value">{{ detail.order.type }}</span></div>
        <div class="field"><span class="label">方案</span><span class="value">{{ detail.order.tier || '-' }} / {{ detail.order.billing_cycle || '-' }}</span></div>
        <div class="field"><span class="label">金額</span><span class="value">NT$ {{ (detail.order.amount_twd ?? 0).toLocaleString() }}</span></div>
        <div class="field"><span class="label">訂單狀態</span><span class="value">{{ detail.order.status }}</span></div>
        <div class="field"><span class="label">建立時間</span><span class="value">{{ formatTimestamp(detail.order.created_at) }}</span></div>
        <div class="field"><span class="label">付款時間</span><span class="value">{{ formatTimestamp(detail.order.paid_at) }}</span></div>
        <div class="field" v-if="detail.order.card_last4"><span class="label">卡號末四碼</span><span class="value">{{ detail.order.card_last4 }}</span></div>
      </div>

      <h3 class="section-title">發票歷史</h3>
      <div v-if="detail.invoices.length === 0" class="empty-invoices">尚無發票紀錄</div>
      <table v-else class="invoices-table">
        <thead>
          <tr>
            <th>data_id</th>
            <th>發票號碼</th>
            <th>狀態</th>
            <th>嘗試次數</th>
            <th>最後錯誤</th>
            <th>作廢</th>
            <th v-if="canWrite">操作</th>
          </tr>
        </thead>
        <tbody>
          <template v-for="inv in detail.invoices" :key="inv._id">
            <tr>
              <td class="mono">{{ inv.data_id }}</td>
              <td class="mono">{{ inv.invoice_number || '-' }}</td>
              <td><span class="status-badge" :class="`invoice-status-${inv.status}`">{{ inv.status }}</span></td>
              <td>{{ inv.attempts ?? 0 }}</td>
              <td class="last-error">{{ formatLastError(inv.last_error) }}</td>
              <td>
                <span v-if="inv.status === 'voided'">{{ inv.void_reason || '-' }}（{{ formatTimestamp(inv.voided_at) }}）</span>
                <span v-else>-</span>
              </td>
              <td v-if="canWrite" class="actions">
                <button v-if="inv.status === 'issued'" class="action-btn void" @click="voidInvoice(inv)">作廢</button>
                <button v-if="['failed', 'pending'].includes(inv.status)" class="action-btn retry" @click="retryInvoice(inv)">重試</button>
                <button
                  v-if="['voided', 'needs_manual'].includes(inv.status) && !hasOpenInvoice"
                  class="action-btn reissue"
                  :disabled="reissueSubmitting"
                  @click="toggleReissueForm(inv._id)"
                >重開</button>
              </td>
            </tr>
            <tr v-if="reissuingId === inv._id" class="reissue-form-row">
              <td :colspan="canWrite ? 7 : 6">
                <div class="reissue-form">
                  <p class="hint">留空代表沿用原買受人資料</p>
                  <p class="hint hint-warning">修正後的買受人資料會同步更新該用戶儲存的發票設定</p>
                  <div class="form-row">
                    <label>
                      <input type="radio" value="" v-model="reissueBuyer.invoice_type" :disabled="reissueSubmitting" /> 沿用原資料
                    </label>
                    <label>
                      <input type="radio" value="personal" v-model="reissueBuyer.invoice_type" :disabled="reissueSubmitting" /> 個人
                    </label>
                    <label>
                      <input type="radio" value="company" v-model="reissueBuyer.invoice_type" :disabled="reissueSubmitting" /> 公司戶
                    </label>
                  </div>
                  <div v-if="reissueBuyer.invoice_type === 'personal'" class="form-row">
                    <label>手機條碼載具（格式 /XXXXXXX）：</label>
                    <input v-model="reissueBuyer.carrier_num" placeholder="/ABC1234" class="form-input" :disabled="reissueSubmitting" />
                  </div>
                  <div v-if="reissueBuyer.invoice_type === 'company'" class="form-row">
                    <label>統一編號：</label>
                    <input v-model="reissueBuyer.company_tax_id" placeholder="8 碼數字" class="form-input narrow" :disabled="reissueSubmitting" />
                    <label>抬頭：</label>
                    <input v-model="reissueBuyer.company_name" placeholder="公司名稱" class="form-input" :disabled="reissueSubmitting" />
                  </div>
                  <div class="form-actions">
                    <button class="action-btn reissue" :disabled="reissueSubmitting" @click="reissueInvoice(inv)">
                      {{ reissueSubmitting ? '處理中...' : '確定重開' }}
                    </button>
                    <button class="action-btn cancel" :disabled="reissueSubmitting" @click="reissuingId = null">取消</button>
                  </div>
                </div>
              </td>
            </tr>
          </template>
        </tbody>
      </table>

      <p v-if="actionError" class="detail-error">{{ actionError }}</p>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import api from '../../utils/api'
import { useAuthStore } from '../../stores/auth'
import { PERM } from '../../constants/permissions'

const props = defineProps({ orderNo: { type: String, required: true } })
const emit = defineEmits(['changed'])

const authStore = useAuthStore()
const canWrite = computed(() => authStore.can(PERM.BILLING_WRITE))
// 該訂單已有開立成功或進行中的發票時不可重開（後端 find_reissue_conflict 會 409，這裡對稱隱藏按鈕）
const hasOpenInvoice = computed(() =>
  (detail.value?.invoices || []).some((i) => ['issued', 'pending', 'failed'].includes(i.status))
)

const detail = ref(null)
const loading = ref(true)
const error = ref(null)
const actionError = ref('')

const reissuingId = ref(null)
const reissueBuyer = ref({ invoice_type: '', carrier_num: '', company_tax_id: '', company_name: '' })
// in-flight 期間 disable 重開相關按鈕：reissue 後端雖已加原子搶佔，前端仍該擋雙擊，
// 避免使用者在第一個請求還在飛時又送第二個（PR-B 驗收 finding #2）。
const reissueSubmitting = ref(false)

async function fetchDetail() {
  loading.value = true
  error.value = null
  try {
    const response = await api.get(`/api/admin/orders/${props.orderNo}`)
    detail.value = response.data
  } catch (err) {
    error.value = err.response?.data?.detail?.message || err.response?.data?.detail || err.message || '載入失敗'
  } finally {
    loading.value = false
  }
}

function formatTimestamp(ts) {
  if (!ts) return '-'
  return new Date(ts * 1000).toLocaleString('zh-TW')
}

function formatLastError(lastError) {
  if (!lastError) return '-'
  return `${lastError.status || ''} ${lastError.desc || ''}`.trim() || '-'
}

async function voidInvoice(inv) {
  const reason = window.prompt('請輸入作廢原因（限 20 字）：', '')
  if (reason === null) return
  const trimmed = reason.trim().slice(0, 20)
  if (!trimmed) {
    window.alert('作廢原因不可為空')
    return
  }
  if (!window.confirm(`確定要作廢發票 ${inv.invoice_number || inv.data_id} 嗎？`)) return

  actionError.value = ''
  try {
    await api.post(`/api/admin/invoices/${inv._id}/void`, { reason: trimmed })
    window.alert('已作廢')
    await fetchDetail()
    emit('changed')
  } catch (err) {
    actionError.value = err.response?.data?.detail?.message || err.response?.data?.detail || '作廢失敗'
  }
}

async function retryInvoice(inv) {
  if (!window.confirm(`確定要重試開立發票 ${inv.data_id} 嗎？`)) return
  actionError.value = ''
  try {
    await api.post(`/api/admin/invoices/${inv._id}/retry`)
    window.alert('已送出重試')
    await fetchDetail()
    emit('changed')
  } catch (err) {
    actionError.value = err.response?.data?.detail?.message || err.response?.data?.detail || '重試失敗'
  }
}

function toggleReissueForm(invId) {
  if (reissuingId.value === invId) {
    reissuingId.value = null
    return
  }
  reissuingId.value = invId
  reissueBuyer.value = { invoice_type: '', carrier_num: '', company_tax_id: '', company_name: '' }
}

async function reissueInvoice(inv) {
  if (reissueSubmitting.value) return  // 防雙擊：上一個重開請求還在飛就忽略這次點擊
  if (!window.confirm(`確定要重開發票（原 ${inv.data_id}）嗎？`)) return

  let corrected_buyer
  if (reissueBuyer.value.invoice_type === 'personal') {
    corrected_buyer = {
      invoice_type: 'personal',
      carrier_num: reissueBuyer.value.carrier_num || '',
    }
  } else if (reissueBuyer.value.invoice_type === 'company') {
    if (!/^\d{8}$/.test(reissueBuyer.value.company_tax_id || '')) {
      window.alert('統一編號需為 8 碼數字')
      return
    }
    if (!(reissueBuyer.value.company_name || '').trim()) {
      window.alert('公司戶需填寫抬頭')
      return
    }
    corrected_buyer = {
      invoice_type: 'company',
      company_tax_id: reissueBuyer.value.company_tax_id,
      company_name: reissueBuyer.value.company_name,
    }
  }

  actionError.value = ''
  reissueSubmitting.value = true
  try {
    await api.post(`/api/admin/invoices/${inv._id}/reissue`, { corrected_buyer })
    window.alert('已送出重開')
    reissuingId.value = null
    await fetchDetail()
    emit('changed')
  } catch (err) {
    actionError.value = err.response?.data?.detail?.message || err.response?.data?.detail || '重開失敗'
  } finally {
    reissueSubmitting.value = false
  }
}

onMounted(fetchDetail)
</script>

<style scoped>
.detail-panel { padding: 16px 24px 24px; }
.detail-loading, .detail-error { padding: 12px 0; color: var(--color-text-light, #a0917c); }
.detail-error { color: #c62828; }

.order-fields {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
  gap: 10px 20px;
  margin-bottom: 16px;
  padding: 12px 0;
  border-bottom: 1px solid rgba(163, 177, 198, 0.2);
}

.field { display: flex; flex-direction: column; gap: 2px; font-size: 13px; }
.field .label { color: var(--color-text-light, #a0917c); font-size: 11px; }
.field .value { color: var(--color-text, rgb(145, 106, 45)); font-weight: 600; }

.section-title { font-size: 14px; margin: 12px 0 8px; color: var(--color-text, rgb(145, 106, 45)); }

.empty-invoices { color: var(--color-text-light, #a0917c); font-size: 13px; padding: 8px 0; }

.invoices-table { width: 100%; border-collapse: collapse; font-size: 12px; background: white; }
.invoices-table th {
  text-align: left;
  padding: 8px 10px;
  background: #f5f5f5;
  color: var(--color-text, rgb(145, 106, 45));
  font-weight: 600;
  border-bottom: 1px solid rgba(163, 177, 198, 0.2);
}
.invoices-table td { padding: 8px 10px; border-bottom: 1px solid rgba(163, 177, 198, 0.1); }
.mono { font-family: monospace; }
.last-error { max-width: 260px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: #c62828; }

.status-badge { display: inline-block; padding: 3px 8px; border-radius: 4px; font-size: 11px; font-weight: 600; }
.invoice-status-issued { background: #d4edda; color: #155724; }
.invoice-status-pending, .invoice-status-failed { background: #fff3cd; color: #856404; }
.invoice-status-needs_manual { background: #ffebee; color: #c62828; }
.invoice-status-voided { background: #f5f5f5; color: #757575; }

.actions { display: flex; gap: 6px; }
.action-btn {
  padding: 4px 10px;
  border: none;
  border-radius: 6px;
  font-size: 11px;
  font-weight: 600;
  cursor: pointer;
}
.action-btn.void { background: #ffcdd2; color: #c62828; }
.action-btn.retry { background: #fff3e0; color: #f57c00; }
.action-btn.reissue { background: #e3f2fd; color: #1976d2; }
.action-btn.cancel { background: #f5f5f5; color: #757575; }

.reissue-form-row td { background: #fafafa; }
.reissue-form { padding: 10px 0; display: flex; flex-direction: column; gap: 10px; }
.reissue-form .hint { font-size: 12px; color: var(--color-text-light, #a0917c); margin: 0; }
.reissue-form .hint-warning { color: #f57c00; }
.action-btn:disabled { opacity: 0.5; cursor: not-allowed; }
.form-input:disabled { background: #f5f5f5; cursor: not-allowed; }
.form-row { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; font-size: 13px; }
.form-input {
  padding: 6px 10px;
  border: 1px solid rgba(163, 177, 198, 0.3);
  border-radius: 6px;
  font-size: 13px;
}
.form-input.narrow { max-width: 120px; }
.form-actions { display: flex; gap: 8px; }
</style>
