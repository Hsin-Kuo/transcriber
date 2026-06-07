import { taskService } from '../api/services'

// 防 open redirect：只接受 / 開頭的 internal path，
// 拒絕 protocol-relative (//) 或 windows path (/\\) 形式的外站跳轉。
export function safeRedirect(raw) {
  if (typeof raw !== 'string' || raw.length === 0) return '/'
  if (!raw.startsWith('/')) return '/'
  if (raw.startsWith('//') || raw.startsWith('/\\')) return '/'
  return raw
}

// 登入後（或已登入造訪訪客頁）的落點：
// - 有明確 redirect（從受保護頁被導來）→ 尊重它
// - 否則（預設首頁）使用者已有未刪除任務 → 任務列表 /all，沒有才落上傳頁 /
// 任務查詢失敗不阻斷流程，退回上傳頁。
export async function resolveLandingPath(rawRedirect) {
  const redirect = safeRedirect(rawRedirect)
  if (redirect !== '/') return redirect
  try {
    const { total } = await taskService.list({ limit: 1, skip: 0 })
    if (total >= 1) return '/all'
  } catch {
    // 查詢失敗：退回上傳頁
  }
  return '/'
}
