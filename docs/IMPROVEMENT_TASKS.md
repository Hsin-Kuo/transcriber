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
  - [x] T1-e：建立 `config.py`、`state.py`、`db.py`、`model_cache.py`、`audio_converter.py`

- [~] **T2** — 拆分 `src/services/transcription_service.py`
  - **2026-05-17 進度**：M1.3 B 範圍把 service 從 1145 → 399 行（−65%）抽出 `TranscriptionOrchestrator`
  - 原 T2 細部拆分（audio_preprocessor / segment_assembler / chinese_converter）仍可做但 ROI 已降低
  - [ ] T2-a：抽出 `src/services/audio_preprocessor.py`（格式轉換、正規化）— 留剩 399 行可繼續啃
  - [ ] T2-b：抽出 `src/services/segment_assembler.py`（Whisper 輸出 + 說話者合併）
  - [ ] T2-c：抽出 `src/services/chinese_converter.py`（繁簡轉換邏輯集中）
  - [x] T2-d：`transcription_service.py` 精簡為協調者角色（已完成由 M1.3）

- [x] **T3** — 封裝 `src/utils/shared_state.py`（全域可變字典）
  - [x] T3-a：改寫為 `TaskStateStore` 類別，包含 get/set/delete/lock 方法
  - [x] T3-b：更新 `task_service.py`、`routers/tasks.py`、`main.py` 改用 `TaskStateStore` 注入

- [~] **T4** — 拆分 `frontend/src/views/TranscriptDetailView.vue`
  - **2026-05-17 進度**：M2 #5 + #2 + #1 三刀，3645 → 3397 行（−7%）
  - 拆出 `ShareDialog.vue` 元件、`useDisplayPreferences` composable、`utils/searchMatching.ts`
  - 原 T4-a/b（Canvas + Sidebar）的具體切分在重評後判定為 shallow extraction，不做
  - [x] M2 #5：抽出 `components/transcript/ShareDialog.vue`
  - [x] M2 #2：抽出 `composables/transcript/useDisplayPreferences.js`
  - [x] M2 #1：抽出 `utils/searchMatching.ts`（純函數，無 Vue 依賴）

## 🟡 中優先（技術債）

- [~] **T5** — 補充測試（部分由 LAUNCH_READINESS_PLAN B2 完成）
  - **2026-05-17 進度**：121 個測試（base 31 + 新增 90）
  - 新增覆蓋：JWT entropy / cookie helper / audio validator / WorkerDispatch / TranscriptionWorkerJob / TranscriptionOrchestrator / logger middleware
  - [ ] T5-a：建立 `tests/unit/test_task_repo.py`
  - [ ] T5-b：建立 `tests/unit/test_quota.py`
  - [x] T5-c：JWT 測試已建（B5）
  - [ ] T5-d：建立 `tests/integration/test_transcription_flow.py`

- [x] **T6** — Magic number 集中管理
  - [x] T6-a：擴充 `src/worker_core/config.py`，集中 SQS、Spot、MongoDB 常數
  - [x] T6-b：更新 `sqs_consumer.py`、`spot_monitor.py`、`db.py` 引用 config 常數

- [ ] **T7** — Router DI 統一
  - [ ] T7-a：審查所有 router，找出直接 instantiate service 的地方
  - [ ] T7-b：統一改用 `Depends()` 注入 Service
  - 註：跟 LAUNCH_READINESS_PLAN M1 #2（DeploymentMode adapter）一併考慮會比較自然

- [x] **T8** — 結構化 logging（由 LAUNCH_READINESS_PLAN M4 完成）
  - [x] T8-a：建立 `src/utils/logger.py`（structlog + request_id middleware）
  - [~] T8-b：舊 print() 漸進遷移（新模組改用 logger，舊檔視觸碰頻率慢慢轉）

## 🟢 低優先（體驗優化）

- [ ] **T9** — SSE 效能（可選，目前夠用，有效能問題再處理）
  - [ ] 評估是否改用 WebSocket 取代每 1-2 秒 poll

- [x] **T10** — 前端 API 型別安全（由 LAUNCH_READINESS_PLAN M3 完成）
  - [x] T10-a：兩前端各加 ESLint 9 + TypeScript（allowJs 漸進）
  - [x] T10-a：轉 utils/api.ts（兩前端各一份）、utils/searchMatching.ts、api/endpoints.ts
  - [ ] frontend/src/api/services.js 待後續（需設計 API response types）

---

## 進度追蹤

| 任務 | 狀態 | 完成時間 |
|------|------|----------|
| T1 worker.py 拆分 | ✅ 完成 | 2026-04-30 |
| T2 transcription_service 拆分 | 🟡 部分完成（M1.3 由協調者抽出） | 2026-05-17 |
| T3 shared_state 封裝 | ✅ 完成 | 2026-04-30 |
| T4 TranscriptDetailView 拆分 | 🟡 部分完成（M2 三刀） | 2026-05-17 |
| T5 測試補充 | 🟡 部分完成（121 個測試含 B2 新增） | 2026-05-17 |
| T6 Magic number 集中 | ✅ 完成 | 2026-04-30 |
| T7 Router DI 統一 | ⏳ 待處理 | — |
| T8 結構化 logging | ✅ 完成（M4） | 2026-05-17 |
| T9 SSE 效能 | ⏳ 待處理 | — |
| T10 前端型別安全 | ✅ 完成（M3） | 2026-05-17 |
