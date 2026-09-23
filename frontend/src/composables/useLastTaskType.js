/**
 * 記住使用者上一次選的任務類型（文件 / 字幕）。
 *
 * 用 localStorage 而非 sessionStorage：這是跨 session 的偏好，
 * 關掉瀏覽器再回來也該記得（篩選條件才是 sessionStorage，語意不同）。
 *
 * 只記錄「實際送出上傳時」用的值——在設定跳窗改了又取消不算數，
 * 否則使用者只是點開看看就會把預設值改掉。
 */
const STORAGE_KEY = 'upload_lastTaskType'

// 與後端 ALLOWED_TASK_TYPES 一致
const ALLOWED_TASK_TYPES = ['paragraph', 'subtitle']
const DEFAULT_TASK_TYPE = 'paragraph'

/**
 * 讀取上次選擇；沒有紀錄或值不合法時回預設值。
 * 走白名單是因為 localStorage 可被使用者任意竄改，不能直接信。
 */
export function readLastTaskType() {
  try {
    const saved = localStorage.getItem(STORAGE_KEY)
    return ALLOWED_TASK_TYPES.includes(saved) ? saved : DEFAULT_TASK_TYPE
  } catch (error) {
    // Safari 無痕模式等情境下 localStorage 可能直接 throw
    console.error('Failed to read last task type:', error)
    return DEFAULT_TASK_TYPE
  }
}

/** 記錄這次實際送出的選擇。 */
export function rememberTaskType(taskType) {
  if (!ALLOWED_TASK_TYPES.includes(taskType)) return
  try {
    localStorage.setItem(STORAGE_KEY, taskType)
  } catch (error) {
    console.error('Failed to save last task type:', error)
  }
}
