/**
 * 新手導覽（方案 C）全域狀態 Store
 *
 * 為何需要全域：導覽要跨頁（上傳頁 → 任務列表 → 任務詳情），
 * 一換頁元件就 unmount，狀態若放在 view 內會遺失。改由此 store 記住
 * 「目前進行到哪個 phase」，各頁 mount 時讀 phase 跑自己那段 driver 步驟。
 */
import { ref, computed } from 'vue'
import { defineStore } from 'pinia'

const SEEN_KEY = 'sl_tour_done'

// 導覽階段（跨頁）—— 單一來源，避免裸字串散落各檔
export const TOUR_PHASES = {
  UPLOAD: 'upload',
  LIST: 'list',
  DETAIL: 'detail',
}

// data-tour 錨點名稱 —— 與各 .vue template 的 data-tour="..." 屬性必須一致。
// step builder 一律透過 tourSel() 引用，集中列出所有錨點契約方便維護。
export const TOUR_ANCHORS = {
  UPLOAD: 'upload',
  LANGUAGE: 'language',
  DIARIZE: 'diarize',
  TASK_TYPE: 'task-type',
  START: 'start',
  DEMO_CARD: 'demo-card',
  T_TRANSCRIPT: 't-transcript',
  T_ACTIONS: 't-actions',
  T_SUMMARY: 't-summary',
  T_AUDIO: 't-audio',
}

// 把錨點名稱轉成 driver 用的 CSS selector
export const tourSel = (name) => `[data-tour="${name}"]`

export const useTourStore = defineStore('tour', () => {
  // 是否正在導覽
  const active = ref(false)
  // 目前階段：'upload' | 'list' | 'detail'
  const phase = ref(null)
  // 跨頁導航中旗標：避免「導航造成的 driver destroy」被誤判成使用者關閉導覽
  const advancing = ref(false)
  // demo 卡片動畫狀態：'pending' | 'processing' | 'completed'
  const demoStatus = ref('processing')
  // demo 卡片進度（processing 時的百分比）
  const demoProgress = ref(0)

  // 任務列表 / 詳情階段需要顯示 demo 卡片
  const showDemoCard = computed(
    () =>
      active.value &&
      (phase.value === TOUR_PHASES.LIST || phase.value === TOUR_PHASES.DETAIL)
  )

  // localStorage 一律 try/catch；讀失敗回「已看過」→ 寧可不跑也不要每次重觸發
  function hasSeen() {
    try {
      return localStorage.getItem(SEEN_KEY) === '1'
    } catch {
      return true
    }
  }
  function markSeen() {
    try {
      localStorage.setItem(SEEN_KEY, '1')
    } catch {
      /* no-op */
    }
  }

  function start() {
    active.value = true
    phase.value = TOUR_PHASES.UPLOAD
    advancing.value = false
    demoStatus.value = 'processing'
    demoProgress.value = 0
  }

  function setPhase(p) {
    phase.value = p
  }

  // 進入「跨頁導航」：呼叫端在 router.push 前設定，下一頁 mount 後再清除
  function beginAdvance() {
    advancing.value = true
  }
  function endAdvance() {
    advancing.value = false
  }

  function setDemoStatus(status, progress = null) {
    demoStatus.value = status
    if (progress !== null) demoProgress.value = progress
  }

  // 結束導覽（完成 / 略過）→ 重置並標記看過
  function finish() {
    active.value = false
    phase.value = null
    advancing.value = false
    demoStatus.value = 'processing'
    demoProgress.value = 0
    markSeen()
  }

  return {
    active,
    phase,
    advancing,
    demoStatus,
    demoProgress,
    showDemoCard,
    hasSeen,
    markSeen,
    start,
    setPhase,
    beginAdvance,
    endAdvance,
    setDemoStatus,
    finish,
  }
})
