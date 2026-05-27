# 改善任務表

> 此表追蹤架構性技術債（router/service 拆分、前端大檔、結構化 log 等）。
> 上線前 blocker 改去看 [`LAUNCH_READINESS_PLAN.md`](./LAUNCH_READINESS_PLAN.md)；
> M 系列已完成大部分（M4 / M5 / M6 / M7 / M8 ✅，M1 / M2 / M3 部分 ✅）。

## 🔴 高優先（影響維護性）

- [x] **T1** — 拆分 `worker.py`（710 行，職責過多）
  - [x] T1-a：建立 `src/worker_core/sqs_consumer.py`（SQS loop + 訊息分派）
  - [x] T1-b：建立 `src/worker_core/transcription_job.py`（轉錄流程協調）
  - [x] T1-c：建立 `src/worker_core/spot_monitor.py`（Spot 中斷偵測執行緒）
  - [x] T1-d：`worker.py` 改為入口，僅負責啟動
  - [x] T1-e：建立 `config.py`、`state.py`、`db.py`、`model_cache.py`（`audio_converter.py` 後於 pipeline 統一重構併入 `src/utils/audio_converter.py`）

- [x] **T2** — 拆分 `src/services/transcription_service.py`
  - **2026-05-17**：M1.3 B 把 service 從 1145 → 399 行，抽出 `TranscriptionOrchestrator`
  - **2026-05（pipeline 統一重構）**：Web Server 與 Worker 收斂成共用的 `src/transcription/orchestrator.py`，`transcription_service.py` 再縮到 ~72 行、只剩協調者角色
  - [x] T2-a/b/c：原規劃的 audio_preprocessor / segment_assembler / chinese_converter 抽取已被此重構吸收（格式轉換 → `src/utils/audio_converter.py`、segment 合併 → `orchestrator.py`、繁簡 → `orchestrator._run_punctuation_phase`），不再單獨拆
  - [x] T2-d：`transcription_service.py` 精簡為協調者角色
  - **2026-05-22**：`transcription_service.py` 於 Task dispatch seam 重構中刪除，協調者角色併入 `LocalDispatch`（見 LAUNCH_READINESS M1.6）

- [x] **T3** — 封裝 `src/utils/shared_state.py`（全域可變字典）
  - [x] T3-a：改寫為 `TaskStateStore` 類別，包含 get/set/delete/lock 方法
  - [x] T3-b：更新 `task_service.py`、`routers/tasks.py`、`main.py` 改用 `TaskStateStore` 注入

- [x] **T4** — 拆分 `frontend/src/views/TranscriptDetailView.vue`（3645→1905 行，−48%）
  - **2026-05-17**：M2 #5 + #2 + #1 三刀，3645 → 3397 行（−7%）
  - **2026-05-25**：深化 composable 抽取，3397 → 1905 行（−41%）
  - [x] M2 #5：抽出 `components/transcript/ShareDialog.vue`
  - [x] M2 #2：抽出 `composables/transcript/useDisplayPreferences.js`
  - [x] M2 #1：抽出 `utils/searchMatching.ts`（純函數，無 Vue 依賴）
  - [x] 抽出 `useTranscriptDownload.js`（下載 + 摘要格式化）
  - [x] 抽出 `useEditingLifecycle.js`（編輯啟動/取消/儲存 + 滾動恢復）
  - [x] 抽出 `useSubtitleAutosave.js`（講者 / 疏密度 debounced 自動存檔）
  - [x] 抽出 `useContentEditableInput.js`（貼上 / IME / Enter / 快捷鍵）
  - [x] 抽出 `usePageLifecycle.js`（載入 / 生命週期 / 路由守衛 / watchers）

## 🟡 中優先（技術債）

- [x] **T5** — 補充測試（部分由 LAUNCH_READINESS_PLAN B2 完成）
  - **2026-05-17 進度**：121 個測試（base 31 + 新增 90）
  - **2026-05-22 進度**：165 後端 + 31 前端測試（新增 TaskDispatch / 轉錄派發整合流程 / TaskRepository / QuotaManager / SSE contract / API_BASE 回歸）
  - 新增覆蓋：JWT entropy / cookie helper / audio validator / WorkerDispatch / TranscriptionJob / TranscriptionOrchestrator / logger middleware / TaskDispatch / TaskRepository / QuotaManager / SSE task-events contract / services API_BASE
  - [x] T5-a：建立 `tests/unit/test_task_repo.py`（2026-05-22）
  - [x] T5-b：建立 `tests/unit/test_quota.py`（2026-05-22）
  - [x] T5-c：JWT 測試已建（B5）
  - [x] T5-d：建立 `tests/integration/test_transcription_flow.py`（2026-05-22；LocalDispatch 整合測試）
  - [x] T5-e：建立 `tests/routers/test_task_sse.py`（2026-05-22；SSE completed frame contract）
  - [x] T5-f：建立 `frontend/src/api/services.test.js`（2026-05-22；API_BASE 回歸測試）

- [x] **T6** — Magic number 集中管理
  - [x] T6-a：擴充 `src/worker_core/config.py`，集中 SQS、Spot、MongoDB 常數
  - [x] T6-b：更新 `sqs_consumer.py`、`spot_monitor.py`、`db.py` 引用 config 常數

- [x] **T7** — Router DI 統一
  - [x] T7-a：審查所有 router，找出直接 instantiate service 的地方
  - [x] T7-b：service provider 集中到 `dependencies.py`（新增 `get_summary_service`、TaskService 單例 `init_task_service` / `get_task_service`）；刪除 tasks.py / summaries.py / audio.py 內重複或死碼的 provider
  - **2026-05-22**：service 注入統一為單一來源。transcriptions.py 內少數 inline `AudioService()`（ffprobe / merge 用、無狀態工具）屬 handler 內部用途，刻意保留——轉 Depends 無 DI 效益

- [x] **T8** — 結構化 logging（由 LAUNCH_READINESS_PLAN M4 完成）
  - [x] T8-a：建立 `src/utils/logger.py`（structlog + request_id middleware）
  - [~] T8-b：舊 print() 漸進遷移（新模組改用 logger，舊檔視觸碰頻率慢慢轉）

## 🟢 低優先（體驗優化）

- [ ] **T9** — SSE 效能（可選，目前夠用，有效能問題再處理）
  - [ ] 評估是否改用 WebSocket 取代每 1-2 秒 poll

- [x] **T10** — 前端 API 型別安全（由 LAUNCH_READINESS_PLAN M3 完成）
  - [x] T10-a：兩前端各加 ESLint 9 + TypeScript（allowJs 漸進）
  - [x] T10-a：轉 utils/api.ts（兩前端各一份）、utils/searchMatching.ts、api/endpoints.ts
  - [x] frontend/src/api/services.js → services.ts（完整 API response types；2026-05-25）

---

## 🔵 營運就緒（上線後持續迭代）

> 2026-05-25 全面評估後新增。按優先度排列。

### P1 — 應盡快處理

- [ ] **O1** — Analytics 整合
  - 加入 Plausible 或 GA4，取得用戶漏斗與轉換率可見性
  - Plausible 免改 CSP、免 cookie consent；GA4 需加白名單

- [ ] **O2** — GDPR 資料匯出
  - 新增 API endpoint 讓用戶下載完整個資（帳號資訊 + 所有轉錄 + segments + tags）
  - 目前只能逐份下載 TXT

- [ ] **O3** — 付款收據 Email
  - 訂閱成功 / 續約成功時寄確認信
  - Email service 基礎設施已有（Resend / SMTP / console）

- [ ] **O4** — Staging 環境
  - 分離 staging 與 production 部署流程
  - 避免直接 push aws 分支即部署生產

### P2 — 重要但可迭代

- [ ] **O5** — 退款機制
  - 藍新退款 API 整合 + admin 退款按鈕

- [x] **O6** — 訂閱到期主動檢查（2026-05-26）
  - 背景 task 每小時掃描 subscription 過期但 status 仍為 active 的用戶，主動降級
  - 與既有 lazy 機制互補（`QuotaManager._expire_subscription`）

- [x] **O7** — Bare `except:` 清理（2026-05-26）
  - user_repo / task_repo → `except Exception`
  - whisper_processor → `except OSError`
  - migrate_json_to_mongo → `except Exception`
  - 全站零 bare except 殘留

- [ ] **O8** — SEO / OG Meta Tags
  - index.html 加 description、OG tags
  - 分享頁面（/s/:token）加動態 meta（轉錄標題 + 描述）

- [x] **O9** — Accessibility 基礎（2026-05-27）
  - [x] Phase 1：全局 `:focus-visible` / icon button aria-label / aria-live / dialog role / progress bar role
  - [x] Phase 2：`useFocusTrap` composable（Tab 循環 + focus restore）套用至 5 個 modal/panel
  - [x] Phase 2：div@click 轉語義（SubtitleTable 時間戳 / speaker badge 加 role="button" + keyboard）
  - [x] Phase 2：SearchReplacePopup 所有 icon button aria-label + input aria-label
  - [x] Phase 2：MergeModal upload zone role="button" + keyboard support
  - [x] Phase 2：TranscriptHeader speaker input aria-label

- [ ] **O10** — IaC（基礎設施即代碼）
  - 用 Terraform 或 CDK 定義 AWS 資源
  - 目前全手動，僅文件記錄 instance ID

- [ ] **O11** — Session 管理
  - 「登出所有裝置」功能
  - 用戶可查看活躍 session 列表

- [x] **O12** — MongoDB 連線池調優（2026-05-27）
  - maxPoolSize=20 / minPoolSize=2 / waitQueueTimeoutMS=5000
  - 防止池滿時無限等待、減少冷啟動延遲

### P3 — Nice-to-have

- [ ] **O13** — Circuit breaker（Gemini / S3 熔斷）
- [ ] **O14** — 內容審核 / 濫用舉報機制
- [ ] **O15** — Admin 收入 dashboard
- [x] **O16** — Plan 升降級處理（已實作，非傳統 proration）
  - 升級：剩餘配額歸入 `extra_quota` + 立即生效新方案
  - 降級：維持當前方案直到期末，排程新方案於到期日首扣
  - 不做金額差額計算，設計上刻意如此
- [x] **O17** — Google OAuth HTTP timeout 設定（2026-05-27）

### 已完成

- [x] CSP 從 Report-Only 切換為強制模式（2026-05-25）
- [x] 登入 rate limit（IP 20次 + Email 5次 / 15分鐘）（2026-05-25）
- [x] 隱私權政策 + 服務條款文件撰寫（`docs/privacy-policy.md`、`docs/terms-of-service.md`）（2026-05-25）
- [x] 前端 code splitting（主 bundle 648KB→293KB，-55%）+ 移除 dead wavesurfer.js（2026-05-25）
- [x] 全局網路錯誤 toast（5xx / network error / offline / online）（2026-05-25）
- [x] Pending 訂單 TTL 清理（expires_at + 背景 sweep）（2026-05-25）
- [x] O6 訂閱到期主動檢查（背景 task 每小時掃描 + 降級）（2026-05-26）
- [x] O7 Bare `except:` 清理（全站零 bare except）（2026-05-26）
- [x] O9 Accessibility 基礎（focus-visible / aria-label / aria-live / focus trap / 語義化）（2026-05-27）

---

## 進度追蹤

| 任務 | 狀態 | 完成時間 |
|------|------|----------|
| T1 worker.py 拆分 | ✅ 完成 | 2026-04-30 |
| T2 transcription_service 拆分 | 🟡 部分完成（M1.3 由協調者抽出） | 2026-05-17 |
| T3 shared_state 封裝 | ✅ 完成 | 2026-04-30 |
| T4 TranscriptDetailView 拆分 | ✅ 完成（3645→1905 行，−48%） | 2026-05-25 |
| T5 測試補充 | ✅ 完成（165 後端 + 31 前端；T5-a~f 全 ✅） | 2026-05-22 |
| T6 Magic number 集中 | ✅ 完成 | 2026-04-30 |
| T7 Router DI 統一 | ✅ 完成（service provider 集中至 dependencies.py） | 2026-05-22 |
| T8 結構化 logging | ✅ 完成（M4） | 2026-05-17 |
| T9 SSE 效能 | ⏳ 待處理 | — |
| T10 前端型別安全 | ✅ 完成（M3） | 2026-05-17 |
