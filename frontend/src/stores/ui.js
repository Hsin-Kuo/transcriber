/**
 * 全域 UI 狀態 Store
 * 讓任何頁面都能開啟方案面板（PlanPanel）/ 額度不足對話框，
 * 不必把元件鎖在 UserSettingsView 內。
 */
import { ref } from 'vue'
import { defineStore } from 'pinia'

export const useUiStore = defineStore('ui', () => {
  // 方案面板（PlanPanel）開關 —— 全域單一實例掛在 App.vue
  const planPanelOpen = ref(false)

  // 額度不足對話框：{ type: 'duration_minutes' | 'ai_summaries' } 或 null
  const quotaModal = ref(null)

  function openPlanPanel() {
    planPanelOpen.value = true
  }

  function showQuotaModal(quotaType = 'duration_minutes') {
    quotaModal.value = { type: quotaType }
  }

  function closeQuotaModal() {
    quotaModal.value = null
  }

  return {
    planPanelOpen,
    quotaModal,
    openPlanPanel,
    showQuotaModal,
    closeQuotaModal,
  }
})
