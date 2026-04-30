# 改善任務表
> ⚠️ 全部修改完成後刪除此檔案

## 🔴 高優先（影響維護性）

- [ ] **T1** — 拆分 `worker.py`（710 行，職責過多）
  - [ ] T1-a：建立 `src/worker_core/sqs_consumer.py`（SQS loop + 訊息分派）
  - [ ] T1-b：建立 `src/worker_core/transcription_job.py`（轉錄流程協調）
  - [ ] T1-c：建立 `src/worker_core/spot_monitor.py`（Spot 中斷偵測執行緒）
  - [ ] T1-d：`worker.py` 改為入口，僅負責啟動

- [ ] **T2** — 拆分 `src/services/transcription_service.py`（1,131 行）
  - [ ] T2-a：抽出 `src/services/audio_preprocessor.py`（格式轉換、正規化）
  - [ ] T2-b：抽出 `src/services/segment_assembler.py`（Whisper 輸出 + 說話者合併）
  - [ ] T2-c：抽出 `src/services/chinese_converter.py`（繁簡轉換邏輯集中）
  - [ ] T2-d：`transcription_service.py` 精簡為協調者角色

- [ ] **T3** — 封裝 `src/utils/shared_state.py`（全域可變字典）
  - [ ] T3-a：改寫為 `TaskStateStore` 類別，包含 get/set/delete/lock 方法
  - [ ] T3-b：更新所有使用方（`task_service.py`, `transcription_service.py`, routers）改用注入的方式取得實例

- [ ] **T4** — 拆分 `frontend/src/views/TranscriptDetailView.vue`（107KB，單檔過重）
  - [ ] T4-a：抽出 `TranscriptCanvas.vue`（主要編輯區）
  - [ ] T4-b：抽出 `TranscriptSidebar.vue`（右側摘要/說話者面板）
  - [ ] T4-c：`TranscriptDetailView.vue` 改為組裝用頂層元件

## 🟡 中優先（技術債）

- [ ] **T5** — 補充測試
  - [ ] T5-a：建立 `tests/unit/test_task_repo.py`
  - [ ] T5-b：建立 `tests/unit/test_quota.py`
  - [ ] T5-c：建立 `tests/unit/test_jwt_handler.py`
  - [ ] T5-d：建立 `tests/integration/test_transcription_flow.py`

- [ ] **T6** — Magic number 集中管理
  - [ ] T6-a：建立 `src/config.py`，集中 WorkerConfig、TranscriptionConfig、QuotaConfig 常數
  - [ ] T6-b：更新 `worker.py`、`task_service.py`、`transcription_service.py` 引用 config

- [ ] **T7** — Router DI 統一
  - [ ] T7-a：審查所有 router，找出直接 instantiate service 的地方
  - [ ] T7-b：統一改用 `Depends()` 注入 Service

- [ ] **T8** — 結構化 logging
  - [ ] T8-a：建立 `src/utils/logger.py`（統一 logging 設定 + request-id）
  - [ ] T8-b：替換 `worker.py`、`transcription_service.py`、`task_service.py` 中的 `print()` 為 `logger`

## 🟢 低優先（體驗優化）

- [ ] **T9** — SSE 效能（可選，目前夠用，有效能問題再處理）
  - [ ] 評估是否改用 WebSocket 取代每 1-2 秒 poll

- [ ] **T10** — 前端 API 型別安全
  - [ ] T10-a：為 `api/services.js` 加入 JSDoc 型別，或評估遷移 TypeScript

---

## 進度追蹤

| 任務 | 狀態 | 完成時間 |
|------|------|----------|
| T1 worker.py 拆分 | 🔄 進行中 | — |
| T2 transcription_service 拆分 | ⏳ 待處理 | — |
| T3 shared_state 封裝 | ⏳ 待處理 | — |
| T4 TranscriptDetailView 拆分 | ⏳ 待處理 | — |
| T5 測試補充 | ⏳ 待處理 | — |
| T6 Magic number 集中 | ⏳ 待處理 | — |
| T7 Router DI 統一 | ⏳ 待處理 | — |
| T8 結構化 logging | ⏳ 待處理 | — |
| T9 SSE 效能 | ⏳ 待處理 | — |
| T10 前端型別安全 | ⏳ 待處理 | — |
