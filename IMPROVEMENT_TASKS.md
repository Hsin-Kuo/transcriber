# 改善任務表

> 此表追蹤架構性技術債（router/service 拆分、前端大檔、結構化 log 等）。
> 上線前 blocker 改去看 [`docs/LAUNCH_READINESS_PLAN.md`](./docs/LAUNCH_READINESS_PLAN.md)，那邊的 M1-M8 與本表的 T2/T4/T7/T8/T10 有重疊。

## 🔴 高優先（影響維護性）

- [x] **T1** — 拆分 `worker.py`（710 行，職責過多）
  - [x] T1-a：建立 `src/worker_core/sqs_consumer.py`（SQS loop + 訊息分派）
  - [x] T1-b：建立 `src/worker_core/transcription_job.py`（轉錄流程協調）
  - [x] T1-c：建立 `src/worker_core/spot_monitor.py`（Spot 中斷偵測執行緒）
  - [x] T1-d：`worker.py` 改為入口，僅負責啟動
  - [x] T1-e：建立 `config.py`、`state.py`、`db.py`、`model_cache.py`、`audio_converter.py`

- [ ] **T2** — 拆分 `src/services/transcription_service.py`（1,131 行）→ 對應 LAUNCH_READINESS_PLAN M1
  - [ ] T2-a：抽出 `src/services/audio_preprocessor.py`（格式轉換、正規化）
  - [ ] T2-b：抽出 `src/services/segment_assembler.py`（Whisper 輸出 + 說話者合併）
  - [ ] T2-c：抽出 `src/services/chinese_converter.py`（繁簡轉換邏輯集中）
  - [ ] T2-d：`transcription_service.py` 精簡為協調者角色

- [x] **T3** — 封裝 `src/utils/shared_state.py`（全域可變字典）
  - [x] T3-a：改寫為 `TaskStateStore` 類別，包含 get/set/delete/lock 方法
  - [x] T3-b：更新 `task_service.py`、`routers/tasks.py`、`main.py` 改用 `TaskStateStore` 注入

- [ ] **T4** — 拆分 `frontend/src/views/TranscriptDetailView.vue`（107KB，單檔過重）→ 對應 LAUNCH_READINESS_PLAN M2
  - [ ] T4-a：抽出 `TranscriptCanvas.vue`（主要編輯區）
  - [ ] T4-b：抽出 `TranscriptSidebar.vue`（右側摘要/說話者面板）
  - [ ] T4-c：`TranscriptDetailView.vue` 改為組裝用頂層元件

## 🟡 中優先（技術債）

- [~] **T5** — 補充測試（部分由 LAUNCH_READINESS_PLAN B2 完成）
  - [ ] T5-a：建立 `tests/unit/test_task_repo.py`
  - [ ] T5-b：建立 `tests/unit/test_quota.py`
  - [x] T5-c：JWT 測試已建於 `tests/auth/test_jwt_handler_entropy.py`（B5）
  - [ ] T5-d：建立 `tests/integration/test_transcription_flow.py`
  - 附加：B2 也補了 `tests/auth/test_cookies.py` 與 `tests/services/test_audio_validator.py`

- [x] **T6** — Magic number 集中管理
  - [x] T6-a：擴充 `src/worker_core/config.py`，集中 SQS、Spot、MongoDB 常數
  - [x] T6-b：更新 `sqs_consumer.py`、`spot_monitor.py`、`db.py` 引用 config 常數

- [ ] **T7** — Router DI 統一 → 對應 LAUNCH_READINESS_PLAN M1
  - [ ] T7-a：審查所有 router，找出直接 instantiate service 的地方
  - [ ] T7-b：統一改用 `Depends()` 注入 Service

- [ ] **T8** — 結構化 logging → 對應 LAUNCH_READINESS_PLAN M4
  - [ ] T8-a：建立 `src/utils/logger.py`（統一 logging 設定 + request-id）
  - [ ] T8-b：替換 `worker.py`、`transcription_service.py`、`task_service.py` 中的 `print()` 為 `logger`

## 🟢 低優先（體驗優化）

- [ ] **T9** — SSE 效能（可選，目前夠用，有效能問題再處理）
  - [ ] 評估是否改用 WebSocket 取代每 1-2 秒 poll

- [ ] **T10** — 前端 API 型別安全 → 對應 LAUNCH_READINESS_PLAN M3
  - [ ] T10-a：為 `api/services.js` 加入 JSDoc 型別，或評估遷移 TypeScript

---

## 進度追蹤

| 任務 | 狀態 | 完成時間 |
|------|------|----------|
| T1 worker.py 拆分 | ✅ 完成 | 2026-04-30 |
| T2 transcription_service 拆分 | ⏳ 待處理 | — |
| T3 shared_state 封裝 | ✅ 完成 | 2026-04-30 |
| T4 TranscriptDetailView 拆分 | ⏳ 待處理 | — |
| T5 測試補充 | 🟡 部分完成（T5-c） | 2026-05-17 |
| T6 Magic number 集中 | ✅ 完成 | 2026-04-30 |
| T7 Router DI 統一 | ⏳ 待處理 | — |
| T8 結構化 logging | ⏳ 待處理 | — |
| T9 SSE 效能 | ⏳ 待處理 | — |
| T10 前端型別安全 | ⏳ 待處理 | — |
