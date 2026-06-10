/**
 * 全域上傳狀態 Store —— 「上傳進度看板」
 *
 * 為什麼存在：上傳大檔可能耗時數分鐘，使用者常會在上傳途中切去其他頁面。
 * 進度若綁在 TranscriptionView 的 local ref，元件 unmount 後進度就消失。
 * 把進度 / 生命週期抽到這個 app-global 的 Pinia store，搭配掛在 App.vue 的
 * GlobalUploadProgress 浮層，使用者跳到任何頁面都能持續看到上傳進度。
 *
 * 注意：本 store 只負責「進度可見性 + 取消」。通知（showNotification 是 App 層
 * provide）與跳頁仍由 TranscriptionView 處理——router / inject 的 reference 在元件
 * unmount 後仍有效，所以即使使用者離開上傳頁，完成後的通知與導頁照常運作。
 */
import { ref, computed } from 'vue'
import { defineStore } from 'pinia'

export const useUploadStore = defineStore('upload', () => {
  const active = ref(false) // 看板是否顯示（含 done / error 待使用者關閉）
  const kind = ref('single') // 'single' | 'merge' | 'batch'
  const label = ref('') // 顯示名稱（檔名或「N 個檔案」）
  const progress = ref(0) // 0-100（分片上傳才有逐步進度）
  const batchCurrent = ref(0) // 批次：目前第幾個檔案
  const batchTotal = ref(0) // 批次：總共幾個檔案
  const status = ref('idle') // 'idle' | 'uploading' | 'done' | 'error' | 'cancelled'
  const errorMessage = ref('')

  // AbortController 不需要響應式，用 closure 變數保存
  let abortController = null

  // 是否有上傳「正在進行」（用來鎖在頁面上傳按鈕、決定取消鈕是否顯示）
  const busy = computed(() => active.value && status.value === 'uploading')

  function start({ kind: k = 'single', label: l = '', batchTotal: total = 0 } = {}) {
    abortController = new AbortController()
    active.value = true
    kind.value = k
    label.value = l
    progress.value = 0
    batchCurrent.value = 0
    batchTotal.value = total
    status.value = 'uploading'
    errorMessage.value = ''
  }

  function setProgress(pct) {
    if (status.value === 'uploading') progress.value = pct
  }

  function setFileProgress(current, total) {
    batchCurrent.value = current
    batchTotal.value = total
  }

  function succeed() {
    progress.value = 100
    status.value = 'done'
  }

  function fail(message = '') {
    status.value = 'error'
    errorMessage.value = message
  }

  // 使用者主動取消：中止所有進行中的 chunk 請求。
  // 後端已上傳的暫存分片由 periodic_chunk_upload_cleanup（3h sweep）自行清理。
  function cancel() {
    if (abortController) abortController.abort()
    status.value = 'cancelled'
  }

  function dismiss() {
    active.value = false
    status.value = 'idle'
    abortController = null
  }

  // 給 caller 把 signal 串進 axios 請求（AbortController 非響應式，用 getter 取）
  function getSignal() {
    return abortController ? abortController.signal : undefined
  }

  return {
    active,
    kind,
    label,
    progress,
    batchCurrent,
    batchTotal,
    status,
    errorMessage,
    busy,
    start,
    setProgress,
    setFileProgress,
    succeed,
    fail,
    cancel,
    dismiss,
    getSignal,
  }
})
