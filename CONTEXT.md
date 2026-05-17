# Transcriber

語音轉文字平台（SoundLite）。使用者上傳音檔，系統做語音辨識、加標點、可選說話者辨識，最後保存轉錄結果與音檔。

本檔記錄的是「跨層共用、跟程式碼名稱直接相關、且容易被同義詞稀釋」的領域詞彙。

## Language

### Pipeline 階段

**Phase**:
轉錄流程的序列階段，總共三個：`PREPARATION` → `TRANSCRIPTION` → `PUNCTUATION`。是進度報告的最小單位。
_Avoid_: stage（容易跟一般 staging 混）、step（過度細粒度）。

**PREPARATION phase**:
含下載音檔、ffmpeg 轉 MP3、上傳轉碼後音檔、模型載入。權重 10%。

**TRANSCRIPTION phase**:
Whisper 轉錄（含 chunking 並行）與說話者辨識（pyannote）的並行區段。權重 77%。

**PUNCTUATION phase**:
Gemini / OpenAI 加標點。權重 13%。

**phase_progress**:
單一 Phase 內部的進度，0.0~1.0。例如 transcription chunked 模式裡「完成 3/10 段」就是 0.3。

**overall_percentage**:
所有 phase 加權後的總百分比（0~100）。**由 ProgressStore 在讀出時動態計算**，呼叫端不直接寫總百分比。

### 任務狀態

**Task**:
使用者一次上傳音檔產生一筆 Task。在 MongoDB 持久化，含 user / config / 結果 metadata 等。
_Avoid_: Job、Request。

**Transcription**:
Task 完成後產出的轉錄結果（含 full_text、segments、語言、speakers 等），存在 `transcriptions` collection。
_Avoid_: Result、Output。

**Persistent task state**:
Task 完成後仍有意義的欄位（status、user、tier、result references、timestamps）。永久存在 `tasks` collection。

**Transient progress state**:
只在執行期間有意義的欄位（phase、phase_progress、message、chunks 進度、diarization 子狀態等）。執行完成後失去意義，由 `task_progress` collection 的 TTL 自動清。
_Avoid_: memory state（舊命名，已從程式碼移除）。

### 部署角色

**Web Server**:
處理 HTTP / SSE / 認證，建立 Task 並通知 Worker。`APP_ROLE=server`，或 `DEPLOY_ENV=local` 下單一進程。

**Worker**:
實際跑轉錄 pipeline 的進程。`DEPLOY_ENV=local` 時是 Web Server 同進程的背景執行緒；`DEPLOY_ENV=aws` 時是獨立的 GPU EC2，從 SQS 取訊息。
_Avoid_: GPU server、Processor（後者是 pipeline 內部的元件名稱）。

**Worker dispatch**:
Web Server 把新建 Task 移交給 Worker 的動作。AWS 模式下含三件事：上傳音檔到 S3 → 簽 HMAC SQS 訊息 → 送進 `transcriber-tasks` queue；任一步失敗就把 Task 標 failed。`local` 模式下不適用（任務直接走 in-process executor）。封裝在 `src/services/worker_dispatch.py`。
_Avoid_: handoff、enqueue（這兩個只是 dispatch 內部的子步驟）。

## Relationships

- 一個 **Task** 經過三個 **Phase**（PREPARATION → TRANSCRIPTION → PUNCTUATION），完成後產出一份 **Transcription**。
- **Worker** 在執行 Task 期間持續更新 **transient progress state**；**Web Server** 透過 SSE 把 transient state 推送給前端。
- **Transient progress state** 存在獨立的 `task_progress` collection（由 ProgressStore 封裝），跟 `tasks` collection 的 **persistent task state** 完全分離。

## Example dialogue

> **Dev:** "如果 Worker 在 TRANSCRIPTION phase 中途被 Spot 中斷，Task 的 transient progress state 怎麼辦？"
>
> **Domain expert:** "Task 本身會被 orphan-cleanup 標成 failed，persistent state 改完狀態。Transient progress state 由 `task_progress` collection 的 TTL (6 小時) 自動清。"

> **Dev:** "Worker 可不可以直接寫 overall_percentage？"
>
> **Domain expert:** "不行。Worker 只回報 phase 跟 phase_progress；overall_percentage 是 ProgressStore 算出來的 derived value。這樣兩種部署模式才共用同一張 PHASE_WEIGHTS。"

## Flagged ambiguities

- **「Phase」這個詞**：本專案專用於轉錄 pipeline 的三個階段（PREPARATION/TRANSCRIPTION/PUNCTUATION），不要拿來指 deployment phase / release phase 等。
