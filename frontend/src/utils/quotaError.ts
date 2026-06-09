/**
 * 額度不足錯誤的共用判定 —— 後端以 detail.code === 'QUOTA_EXCEEDED' 標示。
 * 前端各處（axios 攔截器、上傳、批次、AI 摘要）統一用這裡，避免字串散落、偵測漂移。
 */
export const QUOTA_EXCEEDED = 'QUOTA_EXCEEDED'

type QuotaDetail = {
  code?: string
  message?: string
  quota?: { type?: string }
}

export type QuotaInfo = { type: string }

/** 從 API 回應的 detail 物件判定額度錯誤；非額度錯誤回 null。批次 per-file error 也是此形狀。 */
export function quotaErrorFromDetail(detail: unknown): QuotaInfo | null {
  if (detail && typeof detail === 'object' && (detail as QuotaDetail).code === QUOTA_EXCEEDED) {
    return { type: (detail as QuotaDetail).quota?.type || 'duration_minutes' }
  }
  return null
}

/** 從 axios error 判定額度錯誤；非額度錯誤回 null。 */
export function quotaErrorFromResponse(error: any): QuotaInfo | null {
  return quotaErrorFromDetail(error?.response?.data?.detail)
}
