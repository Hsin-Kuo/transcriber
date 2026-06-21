/**
 * 後端錯誤碼 → 前端 i18n 的集中對照 —— 取代散落各處的硬編字串判定。
 *
 * 後端契約（src/utils/api_errors.py）：detail = { code, message, params? }
 *  - code:    機器可讀，查下方 ERROR_I18N 對應到 i18n key
 *  - message: 後端中文 fallback（前端無對應 code 時沿用）
 *  - params:  i18n 插值參數（如 { max: 3072 }）
 *
 * 漸進遷移：未帶 code（或 code 尚無對應 key）的舊錯誤，自動 fallback 到 message，
 * 所以後端可一個 endpoint 一個 endpoint 慢慢遷，不必前後端同步發版。
 */

/** 已就位 i18n 的錯誤碼 → i18n key。新增後端 code 時在此補一行即可。 */
export const ERROR_I18N: Record<string, string> = {
  INVALID_FILE_SIZE: 'errors.invalidFileSize',
  FILE_TOO_LARGE: 'errors.fileTooLarge',
  UPLOAD_DISK_FULL: 'errors.uploadDiskFull',
  UPLOAD_SESSION_NOT_FOUND: 'errors.uploadSessionNotFound',
  UPLOAD_SESSION_INVALIDATED: 'errors.uploadSessionInvalidated',
  FEATURE_NOT_AVAILABLE: 'uploadErrors.featureNotAvailable',
}

type ErrorDetail = {
  code?: string
  message?: string
  params?: Record<string, unknown>
}

export type ResolvedError = {
  /** 有對應 i18n key 才非 null；caller 用 $t(key, params) 翻譯 */
  key: string | null
  /** i18n 插值參數 */
  params: Record<string, unknown>
  /** 後端中文 fallback（無 key 時用） */
  fallback: string
}

/**
 * 從「裸 detail」或「axios error」解析出 { key, params, fallback }。
 * 不直接呼叫 $t —— 保持純函式好測；翻譯交給 component 端（$t 在那才有 i18n context）。
 */
export function errorI18n(detailOrError: unknown): ResolvedError {
  // 支援傳 axios error（取 response.data.detail）或已展開的 detail
  const detail = (detailOrError as any)?.response?.data?.detail ?? detailOrError

  const obj = detail && typeof detail === 'object' ? (detail as ErrorDetail) : null
  const code = obj?.code ?? null
  const key = code && ERROR_I18N[code] ? ERROR_I18N[code] : null
  const params = obj?.params ?? {}
  const fallback = obj ? (obj.message ?? '') : typeof detail === 'string' ? detail : ''

  return { key, params, fallback }
}
