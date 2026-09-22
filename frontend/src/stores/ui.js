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

  // 手機版任務搜尋列是否展開。
  // 入口按鈕在 MobileHeader（App.vue 層級），輸入框在 TaskListContainer，
  // 兩者不同分支，所以開關狀態放這裡；搜尋字串仍留在 TaskListContainer。
  const mobileSearchOpen = ref(false)

  function openPlanPanel() {
    planPanelOpen.value = true
  }

  function showQuotaModal(quotaType = 'duration_minutes') {
    quotaModal.value = { type: quotaType }
  }

  function closeQuotaModal() {
    quotaModal.value = null
  }

  function toggleMobileSearch() {
    mobileSearchOpen.value = !mobileSearchOpen.value
  }

  function closeMobileSearch() {
    mobileSearchOpen.value = false
  }

  return {
    planPanelOpen,
    quotaModal,
    mobileSearchOpen,
    openPlanPanel,
    showQuotaModal,
    closeQuotaModal,
    toggleMobileSearch,
    closeMobileSearch,
  }
})
