/**
 * useDisplayPreferences — 逐字稿頁的「顯示偏好 + 面板版面狀態」聚合。
 *
 * 隱藏在小介面後的同步機制：
 * - isLeftPanelCollapsed → localStorage 同步
 * - isDarkMode → document data-theme 屬性 + localStorage + authStore.updatePreferences
 * - isMobileView → window resize listener（自動 add/remove）
 * - isEffectivelyCollapsed → 移動端永遠展開的衍生規則
 *
 * 不擁有的（留在 caller 自行管理）：
 * - densityThreshold（屬於 useSubtitleMode，並有 displayMode/isMounted/isInitializing
 *   等 caller-specific 條件需協調）
 * - timeFormat（亦屬於 useSubtitleMode）
 *
 * 注意：必須在 setup() 期間呼叫（內部用 onMounted/onUnmounted 註冊 resize listener）。
 */
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'

import { useAuthStore } from '../../stores/auth'

export function useDisplayPreferences() {
  const authStore = useAuthStore()

  // ── 版面狀態 ──────────────────────────────────
  const isLeftPanelCollapsed = ref(localStorage.getItem('leftPanelCollapsed') === 'true')
  const isMobileDrawerOpen = ref(false)
  const isMobileView = ref(window.innerWidth <= 768)
  // 移動端永遠展開：UI 元件用此值判斷實際渲染樣式
  const isEffectivelyCollapsed = computed(
    () => isLeftPanelCollapsed.value && !isMobileView.value,
  )

  // ── 顯示偏好（內容區外觀）─────────────────────
  const isDarkMode = ref(document.documentElement.getAttribute('data-theme') === 'dark')
  const contentFontSize = ref(16)
  const contentFontWeight = ref(400)
  const contentFontFamily = ref('sans-serif')

  // ── 逐字稿顯示輔助標記 ────────────────────────
  const showTimecodeMarkers = ref(false)
  // 進入編輯模式時備份的 markers 狀態（取消編輯時可還原），caller 在編輯路徑會 mutate
  const savedTimecodeMarkersState = ref(true)

  // ── 同步機制 ──────────────────────────────────
  // 收合狀態 → localStorage
  watch(isLeftPanelCollapsed, (v) => {
    localStorage.setItem('leftPanelCollapsed', String(v))
  })

  // 暗色模式 → document data-theme + localStorage + 後端使用者偏好
  watch(isDarkMode, (dark) => {
    const theme = dark ? 'dark' : 'light'
    if (dark) {
      document.documentElement.setAttribute('data-theme', 'dark')
    } else {
      document.documentElement.removeAttribute('data-theme')
    }
    localStorage.setItem('theme', theme)
    authStore.updatePreferences({ theme })
  })

  // resize 監聽（mount / unmount 自動處理）
  const handleResize = () => {
    isMobileView.value = window.innerWidth <= 768
  }
  onMounted(() => {
    window.addEventListener('resize', handleResize)
  })
  onUnmounted(() => {
    window.removeEventListener('resize', handleResize)
  })

  return {
    // 版面
    isLeftPanelCollapsed,
    isMobileDrawerOpen,
    isMobileView,
    isEffectivelyCollapsed,
    // 顯示偏好
    isDarkMode,
    contentFontSize,
    contentFontWeight,
    contentFontFamily,
    // 顯示輔助標記
    showTimecodeMarkers,
    savedTimecodeMarkersState,
  }
}
