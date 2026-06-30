/// <reference types="vite/client" />
/**
 * 前端 feature flags（環境層級，build 時由各環境 .env 決定）。
 *
 * 慣例同 useTranscriptDownload 的 VITE_BACKEND_PDF_ENABLED。
 */

// 任務詳情編輯自動儲存（設計定案見 memory/project_autosave_task_detail.md）。
// 預設關閉；staging .env 設 VITE_AUTOSAVE_ENABLED=true 先 soak，穩定後再於 prod 開啟。
// 核心存檔路徑 + 靜默覆蓋風險，保留「一個 env 關回手動存」的後路。
export const AUTOSAVE_ENABLED = import.meta.env.VITE_AUTOSAVE_ENABLED === 'true'
