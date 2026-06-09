/**
 * 訂閱方案價格（TWD）—— 前端單一來源。
 * 後端另有定價（SSM / 環境變數），此處僅供前端方案頁與結帳頁顯示，改價需同步後端。
 */
export const TIER_PRICES = {
  free: { monthly: 0, yearly: 0 },
  basic: { monthly: 299, yearly: 3289 },
  pro: { monthly: 899, yearly: 9889 },
}

/** 取得某方案在指定計費週期的價格（找不到回 0）。 */
export function tierPrice(tier, billing) {
  return TIER_PRICES[tier]?.[billing] ?? 0
}
