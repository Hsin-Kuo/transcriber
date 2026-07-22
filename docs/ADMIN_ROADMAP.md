# 管理後台 設計檢視與功能 Roadmap

> 建立日期：2026-07-20
> 範圍：`admin-frontend/`（Vue3 後台前端）+ `src/routers/admin.py`（後端 admin API）
> 目的：對照「商業 SaaS 後台該有的能力」盤點缺口，依重要程度排出待辦。

## 整體判斷

目前後台是「單人 operator 內部工具」的成熟度——CRUD 到位、營運統計有基礎，但缺了商業 SaaS 後台的三根支柱：**權限分級、金流操作、合規稽核**。

最迫切的風險：任何一個 admin 都能改配額、刪任務、把他人（或自己）升為 admin、重設密碼，且預設管理員帳密為硬編碼的 `admin@example.com / Admin@123456`（`src/database/migrations/seed_admin.py:33`），首登無強制改密。對外營運的付費產品不應維持此狀態。

---

## 現況盤點（Baseline）

### 已有頁面（`admin-frontend/src/router/index.js`，共 7 條 route）
| 頁面 | 路徑 | 用途 |
|---|---|---|
| Dashboard | `/` | 營收/MRR、訂閱分佈、近 6 月月收入、近期訂單、系統概況、模型使用 |
| Users | `/users` | 用戶列表：搜尋 email、篩選角色/狀態/配額、停用/啟用 |
| UserDetail | `/users/:id` | 改配額/角色、停用、重置月配額、調整額外額度、重設密碼 |
| Tasks | `/tasks` | 全域任務列表：搜尋/篩選、取消、刪除、批次刪除 |
| TaskDetail | `/tasks/:id` | 任務檔案/config/stats/models/摘要 log，取消或刪除 |
| AiCost | `/cost` | 逐月 × 功能 × 模型的 token→USD 成本試算 |
| AuditLogs | `/audit-logs` | 操作記錄表格（僅可依 log_type / user_id 篩選） |

### 後端 admin API（全在 `src/routers/admin.py`，prefix `/api/admin`，皆 `Depends(get_current_admin)`）
- 用戶：list / detail / status / role / quota / reset-quota / extra-quota / reset-password
- 任務：list / detail / cancel / delete / batch-delete
- 統計：`/statistics`、`/revenue`、`/cost`
- 稽核：`/audit-logs`（+ `/failed`、`/statistics`、`/resource/{id}` **已實作但前端未接**）
- 維運：`/cleanup/handoff-orphans`（**已實作但前端未接，無排程**）

### 技術現況
- Vue 3 + Pinia + axios；access token 走 httpOnly cookie，401 自動 refresh 重試（設計良好）
- 已接 Sentry
- **無 i18n**（硬編碼繁中）、**無測試**、RWD 覆蓋不完整、views 幾乎無 TypeScript

### RBAC 現況
- 僅單一 `role == "admin"` 布林判定（`src/auth/dependencies.py:111`），**無角色分級、無 per-endpoint 權限、無 Role enum**
- admin 帳號只能靠 seed 腳本建立（硬編碼帳密），後台無「新增管理員」頁

---

## P0 — 必須（安全 / 合規 / 營收基礎）

> ⚠️ = 觸及 auth / payment，屬高風險改動，走 `judgment-rubrics.md §5` 驗收流程。

### 1. RBAC 權限分級 + 最小權限 ⚠️ `L`
- **現況**：單一 `role == "admin"` 布林，任何 admin 可執行全部操作（含 `PUT /users/{id}/role` 升降他人/自己為 admin）。
- **建議**：導入角色（`superadmin` / `billing` / `support` / `read-only`）+ per-endpoint 權限檢查；升降 admin、退款、刪資料等敏感操作限 `superadmin`。角色定義集中成 enum（目前 code 內無任何 Role 常數）。
- **為什麼優先**：這是其他所有 admin 功能的地基，越晚做改動面越大。

### 2. 移除硬編碼管理員帳密 + 首登強制改密 + 管理員邀請流程 ⚠️ `M`
- **現況**：admin 靠 seed 腳本建立、帳密寫死（`seed_admin.py:33`），無首登改密、後台無新增管理員頁。
- **建議**：seed 僅建一次性隨機密碼並強制首登重設；後台加「管理員管理」頁（邀請 email → 設密 → 指派角色 → 停用/撤銷）。
- **附帶**：admin 帳號強制 2FA / TOTP——付費 SaaS 後台基本盤。

### 3. 金流操作能力（不只唯讀報表） ⚠️ `L`
- **現況**：`/revenue` 只讀加總；**無**退款、單筆訂單明細、手動開通/取消訂閱、重寄收據等操作型 endpoint。`db.orders` 只被讀來算營收。
- **建議**：訂單列表+明細頁、退款(refund)、手動調整訂閱狀態、resend receipt/invoice、**續扣失敗(dunning)可視化**（藍新 / 91APP 定期定額失敗名單）。
- **為什麼優先**：客服日常需要「幫用戶退款/補開通」，現在只能進 DB 手改——危險且無稽核。

### 4. 稽核查詢強化 + 匯出（合規） `M`
- **現況**：`AuditLogsView` 只能按 log_type / user_id 篩，無日期範圍、無 action 篩選、無關鍵字、**無匯出**；action/log_type 印英文原字串、before/after 不顯示。
- **建議**：加日期區間 + action + resource 篩選、before/after diff 檢視、**CSV 匯出**（GDPR 合規基本要求）、action 中文對照。

---

## P1 — 重要（營運支援 / 分析深度）

### 5. 客服支援工具組 `M`
- **Impersonation /「以此用戶身分檢視」**（read-only、全程記稽核）——debug 用戶問題最常用，目前完全沒有。
- **帳號備註 / 標記 / 活動時間軸**：客服可在帳號留 note、看該用戶完整操作歷程（可聚合既有 audit_logs）。

### 6. 系統健康 / 維運儀表板 `M`
- **現況**：後台對 GPU worker 狀態、SQS 佇列深度、卡住/失敗任務率**零可視化**（已有 heartbeats、雙 SQS、spot worker，但 admin 看不到）。`cleanup/handoff-orphans` 已寫好卻無 UI。
- **建議**：Ops 頁顯示 worker 上線狀態(heartbeat)、queue depth、近 24h 失敗率、卡單清單 + 一鍵重派/清理。

### 7. 站內通訊 / 通知 `M`
- 對單一/批次用戶寄信、發系統公告/維護通知、方案/配額異動主動通知。付費用戶溝通是留存關鍵。

### 8. 分析深化 + 自訂區間 `M`
- **現況**：`statistics` 固定近 30 天、`revenue` 固定近 6 月，前端無日期選擇器；已有 MRR/訂閱/任務量/AI 成本/Top users/基本 churn。
- **缺**：DAU/WAU/MAU 時間序列、留存(cohort/retention)、註冊→啟用→付費**轉換漏斗**、ARPU/LTV、方案升降級趨勢、可自訂區間 + 圖表匯出。

### 9. Quick wins — 把已寫好的接上線 `S`（最划算，建議插隊先做）
- 後端已實作、前端未接：`GET /audit-logs/failed`、`/audit-logs/statistics`、`/audit-logs/resource/{id}`、`POST /cleanup/handoff-orphans`。純接線即可回收既有能力。

---

## P2 — 加分（產品化 / 體質）

### 10. 方案 / 功能開關管理 UI `M`
- 方案 tier 目前 code 定義（`QUOTA_TIERS` 為唯一權威來源），改價/額度/功能需動 code + 部署。長期應 config 化 + feature flag。**注意：勿破壞 tier 單一權威來源。**
- 折扣碼 / 促銷碼管理。

### 11. 濫用 / 內容治理 `M`
- 檢舉處理、可疑用量偵測（單帳號暴衝）、rate-limit 覆寫、封鎖名單。

### 12. GDPR / DSAR 工具 `S–M`
- 後台側受理「匯出我的資料 / 刪除請求」（已有帳號刪除邏輯，補 admin 受理與稽核即可）。

### 13. 工程體質 `M`
- 後台**零測試**、無 i18n、RWD 不完整（UsersView / UserDetailView 無 media query）、views 幾乎無 TypeScript。若長期演進，至少補關鍵操作（改配額 / 退款 / 刪除）的整合測試。

---

## 建議執行順序

1. **P0-1（RBAC）+ P0-2（管理員帳號安全）** — 地基，先立好再長功能，且為純安全項。
2. **P1-9（接線 quick wins）** — 穿插進行，低成本回收價值。
3. **P0-3（金流操作）+ P0-4（稽核匯出）** — 直接影響日常客服與合規。
4. 之後才是 P1 營運/分析、P2 產品化。

## 工作量標記
`S` = 數小時～1 天　`M` = 數天　`L` = 1 週以上（含設計 + 高風險驗收）
