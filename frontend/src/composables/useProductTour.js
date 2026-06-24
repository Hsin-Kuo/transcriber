// 新手互動式導覽（方案 C）：driver.js 薄包裝層
// - driver.js 用 dynamic import 延後載入，對首屏 bundle 零影響
// - disableActiveInteraction: true → 導覽期間禁止點擊被高亮的頁面元素，
//   使用者只能用 popover 的「下一步」前進。這是核心安全模型：
//   不可能在導覽中誤觸上傳/送出/呼叫 API。
// - 一次性旗標、phase 狀態改由 stores/tour.js 管理（跨頁需要）；此檔只負責驅動 driver。
//   行動裝置判斷留在此處供呼叫端使用。

export function useProductTour() {
  // ≤768px 表單 2 欄變單欄、spotlight 價值低 → 行動裝置跳過導覽
  const isMobile = () => {
    try {
      return window.matchMedia('(max-width: 768px)').matches
    } catch {
      return false
    }
  }

  let driverObj = null

  // 啟動一段導覽（單一頁面的 steps）。
  // 跨頁時：每頁各自呼叫一次 run；頁與頁之間的銜接由呼叫端在 step 的
  // onNextClick 內 router.push + tourStore.setPhase 完成。
  async function run({ steps, t, onDestroyed }) {
    try {
      const [{ driver }] = await Promise.all([
        import('driver.js'),
        import('driver.js/dist/driver.css'),
      ])
      driverObj = driver({
        showProgress: true,
        allowClose: true, // 保留右上角 ✕ 關閉鈕
        overlayClickBehavior: () => {}, // 點 overlay/其他地方 → no-op，不自動關閉
        allowKeyboardControl: false, // 停用鍵盤（含 Esc），只能按 ✕ 離開
        disableActiveInteraction: true,
        overlayOpacity: 0.6,
        stagePadding: 6,
        stageRadius: 10,
        popoverClass: 'sl-tour-popover',
        nextBtnText: t('tour.next'),
        prevBtnText: t('tour.prev'),
        doneBtnText: t('tour.done'),
        progressText: '{{current}} / {{total}}',
        steps,
        onDestroyed: () => {
          driverObj = null
          onDestroyed?.()
        },
      })
      driverObj.drive()
    } catch (err) {
      // 導覽是 nice-to-have，載入或啟動失敗都不可影響主流程
      console.warn('[tour] failed to start:', err)
      onDestroyed?.()
    }
    return driverObj
  }

  const getDriver = () => driverObj

  // 跨頁交棒：銷毀目前 overlay（onDestroyed 會因 advancing=true 略過收尾）後導航到下一個 phase 的頁面。
  // 收斂原本散在各 view 的 beginAdvance→setPhase→destroy→push 重複序列。
  function advanceTo(tourStore, router, phase, path) {
    tourStore.beginAdvance()
    tourStore.setPhase(phase)
    getDriver()?.destroy?.()
    router.push(path)
  }

  // 產生「driver 結束」處理器：換頁中(advancing)不收尾讓導覽延續；否則執行 onFinish 後結束整個導覽。
  function makeDestroyHandler(tourStore, onFinish) {
    return () => {
      if (tourStore.advancing) return
      onFinish?.()
      tourStore.finish()
    }
  }

  return { isMobile, run, getDriver, advanceTo, makeDestroyHandler }
}
