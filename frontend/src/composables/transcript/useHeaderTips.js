/**
 * useHeaderTips — 任務詳情頁 header「使用技巧」輪播的狀態機。
 *
 * 職責：
 * - 依 displayMode / hasSpeakerInfo / isContentReady 過濾出當前適用的 tips
 * - 加權隨機挑選（weight 越大越常出現），且不與上一則連續重複
 * - 每 12 秒自動換下一則（僅在適用 tips > 1 時啟動計時器）
 * - 讀使用者偏好 tipsEnabled（authStore → localStorage → 預設開）決定整體開關
 *
 * 輸入為 ref/computed（caller 傳入 header 既有的 reactive 值）。
 * 淡入淡出動畫與手機隱藏交給 component CSS；本 composable 只管「顯示哪一則」。
 *
 * 注意：必須在 setup() 期間呼叫（內部用 onMounted/onUnmounted 管理計時器）。
 */
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'

import { useAuthStore } from '../../stores/auth'
import { modifierKeyLabel } from '../../utils/platform'
import { HEADER_TIPS } from '../../config/headerTips'

const ROTATE_INTERVAL_MS = 12000

export function useHeaderTips({
  displayMode,
  hasSpeakerInfo,
  isContentReady,
  hasAudio = ref(false),
  audioRetentionDays = ref(null),
}) {
  const authStore = useAuthStore()
  const { t } = useI18n()

  // 偏好開關：後端同步值優先，其次 localStorage，預設開（新功能要能被發現）
  const tipsEnabled = computed(() => {
    const pref = authStore.preferences?.tipsEnabled
    if (typeof pref === 'boolean') return pref
    return localStorage.getItem('tipsEnabled') !== 'false'
  })

  // 方案是否支援手動釘選音檔（free 為 0 → 不可釘選）
  const canPin = computed(() => (authStore.maxKeepAudio ?? 0) > 0)

  // 依任務屬性過濾出適用的 tips（gate 判定集中在此）
  const eligibleTips = computed(() => {
    const mode = displayMode.value
    const speaker = hasSpeakerInfo.value
    const ready = isContentReady.value
    const audio = hasAudio.value
    const pin = canPin.value
    return HEADER_TIPS.filter((tip) => {
      if (!tip.modes.includes(mode)) return false
      if (tip.requiresSpeaker && !speaker) return false
      if (tip.requiresCompleted && !ready) return false
      if (tip.requiresAudio && !audio) return false
      if (tip.requiresPin && !pin) return false
      if (tip.requiresNoPin && pin) return false
      return true
    })
  })

  const currentTip = ref(null)
  let timer = null

  function weightedPick(candidates) {
    const total = candidates.reduce((sum, tip) => sum + (tip.weight || 1), 0)
    let r = Math.random() * total
    for (const tip of candidates) {
      r -= tip.weight || 1
      if (r < 0) return tip
    }
    return candidates[candidates.length - 1]
  }

  function pickNext() {
    const all = eligibleTips.value
    if (all.length === 0) {
      currentTip.value = null
      return
    }
    // 不與上一則連續重複（除非只剩一則）
    const pool = all.length > 1 && currentTip.value
      ? all.filter((tip) => tip.id !== currentTip.value.id)
      : all
    currentTip.value = weightedPick(pool)
  }

  function stopRotation() {
    if (timer) {
      clearInterval(timer)
      timer = null
    }
  }

  function startRotation() {
    stopRotation()
    if (!tipsEnabled.value || eligibleTips.value.length === 0) {
      currentTip.value = null
      return
    }
    // 沿用仍適用的當前 tip；否則重挑（避免每次條件微變都跳掉正在看的那則）
    const stillValid = currentTip.value
      && eligibleTips.value.some((tip) => tip.id === currentTip.value.id)
    if (!stillValid) pickNext()
    if (eligibleTips.value.length > 1) {
      timer = setInterval(pickNext, ROTATE_INTERVAL_MS)
    }
  }

  // 開關或適用清單變動時重建輪播（deps 變動才會觸發，頻率低）
  watch([tipsEnabled, eligibleTips], startRotation)

  onMounted(startRotation)
  onUnmounted(stopRotation)

  // 文案：{mod} 佔位帶入平台修飾鍵（Mac→Option、其他→Alt）；{days} 帶入音檔保留天數。
  // {icon}（audioShortcuts 專用）在此解析成可讀詞——渲染時走 <i18n-t> 塞真 icon，
  // 這份純文字只作截斷時的 title（hover 顯示全文）用。
  const currentTipText = computed(() => {
    if (!currentTip.value) return ''
    return t(`transcriptDetail.tips.${currentTip.value.i18nKey}`, {
      mod: modifierKeyLabel,
      days: audioRetentionDays.value,
      icon: t('transcriptDetail.tips.shortcutsIconLabel'),
    })
  })

  const showTips = computed(() => tipsEnabled.value && !!currentTip.value)

  return { currentTip, currentTipText, showTips }
}
