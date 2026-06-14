import { useI18n } from 'vue-i18n'

/**
 * 加購套餐的顯示名稱：依 type + amount 由 i18n 組出（DB label 僅作 fallback / 後端用）。
 * PlanPanel 與 CheckoutView 共用，避免重複的 type→i18n-key 對應。
 */
export function useAddonLabel() {
  const { t } = useI18n()
  return function addonLabel(pkg) {
    if (pkg?.type === 'duration') return t('userSettings.checkout.addonDurationLabel', { n: pkg.amount })
    if (pkg?.type === 'ai_summaries') return t('userSettings.checkout.addonAiLabel', { n: pkg.amount })
    return pkg?.label || ''
  }
}
