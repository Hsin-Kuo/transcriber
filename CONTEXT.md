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

**Task ownership**:
「一筆 Task 屬於某 user」的查詢條件，單一真實來源是 `TaskRepository.owned_by(user_id)`（回 `{"user.user_id": user_id}`）。所有 ownership 查詢（repo 內部、admin composed filter）都拼接它，呼叫端不手寫欄位路徑。
_Avoid_: 在呼叫端直接寫 `{"user.user_id": ...}` 或打 `task_repo.collection`、重新引入扁平 `user_id` 相容分支。

> **tasks collection schema 一律巢狀**：create path（`intake_service`）只寫巢狀 `user.user_id` / `file.*` / `config.*` / `result.*` / `timestamps.*`。2026-06 probe 確認 prod 136 筆全巢狀、**0 筆扁平**，故舊「nested + flat `$or`」相容分支與 `get_task_field` 的 flat fallback 已全數移除。移除是 **fail-safe**（萬一還原超舊扁平備份，ownership 查詢回空 → 使用者見 404，不洩漏）。**不要再為 tasks 加扁平相容**。注意 `orders` / `tags` / `audit_logs` 等其他 collection 仍是扁平 `user_id`，那是各自設計，與此無關。

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

**TranscriptionIntakeService**:
「從音檔到 Task dispatch」的完整 workflow service。封裝 7 步驟：音檔資訊取得 → user fetch（含 tier）→ 配額預留（atomic reserve）→ diarization 可用性檢查 → tag 自動建立 → task DB 寫入 → [[Task dispatch]] submit。失敗時自動 rollback（release reservation + 清 temp_dir）。介面：`intake(user_id, user_email, file_path, filename, config: IntakeConfig, temp_dir) → IntakeResult`。Router 只負責 upload 組裝（把 HTTP multipart / chunked upload 轉成 `file_path`）和 response 格式化。封裝在 `src/services/intake_service.py`。
_Avoid_: TranscriptionService（舊淺殼已重命名為 [[LocalDispatch]]）、upload service（upload 組裝留在 router，是正當的 HTTP 層責任）。

**Task dispatch**:
把新建 Task 移交給「會去跑它的 runner」的 seam。[[TranscriptionIntakeService]] 呼叫 `submit(job, audio_local_path, temp_dir, user_tier) -> DispatchResult`，由 adapter 決定走 SQS 還是 in-process executor。兩個 adapter：[[WorkerDispatch]]（AWS）、[[LocalDispatch]]（local）。`DispatchResult` 的硬合約只有 `status`（`pending` / `processing`）；`queue_position` 是 best-effort 顯示糖，adapter 能便宜算就算（WorkerDispatch 不算）。temp_dir 在 `submit()` 返回後即歸 adapter 負責清理。
_Avoid_: 把這個 seam 叫「Worker dispatch」（那只是其中一個 adapter）、dispatcher（過泛）。

**WorkerDispatch**:
[[Task dispatch]] 的 **AWS adapter**。`submit()` 含三件事：上傳音檔到 S3 [[Handoff audio]] → 簽 HMAC SQS 訊息 → 送進 `transcriber-tasks` queue；任一步失敗就把 Task 標 failed。fire-and-forget，立即返回 `status=pending`（後續由 GPU Worker 從 SQS 取走）。`start()` 是 no-op。封裝在 `src/services/worker_dispatch.py`。
_Avoid_: handoff、enqueue（這兩個只是 adapter 內部的子步驟）。

**LocalDispatch**:
[[Task dispatch]] 的 **local adapter**，是舊有淺殼 `TranscriptionService` 深化後的形態。`submit()` 內含本地並發閘門（`MAX_CONCURRENT_TASKS`）：未滿載就立即把 [[TranscriptionOrchestrator]] submit 進 thread pool、回 `status=processing`；滿載就把 Task 留 `pending`、回 `status=pending`。另持有一個背景撿單器（5 秒輪詢，把 pending Task 依建立時間接走），由 `start()` 啟動。run-now 與撿單兩條路徑共用同一個內部 `_start(job)`。
_Avoid_: TranscriptionService（舊淺殼命名）、queue processor（撿單器只是 adapter 內部機制）。

**TranscriptionJob**:
[[Task dispatch]] 的 typed payload（Pydantic），帶 task_id + 轉錄設定（language / chunking / punctuation / diarization / max_speakers / ui_language / handoff_ext）。Web Server 建構；AWS 模式序列化成 SQS body、local 模式直接交給 [[LocalDispatch]]。**跟 [[Task]] 不同**：Task 是 MongoDB 持久實體，TranscriptionJob 是「跑這個 Task 要知道的指令」的傳遞訊息。class 名 `TranscriptionJob`，但檔案維持 `src/models/worker_job.py`（不改檔名，避免跟 worker 薄殼 `src/worker_core/transcription_job.py` 撞名）。
_Avoid_: TranscriptionWorkerJob（舊名；「Worker」一旦兩模式共用就在說謊）、把它跟 [[Task]] 混用。

**TranscriptionOrchestrator**:
單次 transcription run 的 Phase 狀態機 + 取消 + 終態（completed / failed）協調者。持有 processors（whisper / punctuation / diarization）與 progress_store，不持有 Task 業務狀態。run() 從 PREPARATION 跑到 PUNCTUATION，期間透過 check_cancelled() poll DB；遇取消拋 `TranscriptionCancelled`、遇例外走 `_mark_failed`、成功走 `_mark_completed`（含 quota consume）。封裝在 `src/transcription/orchestrator.py`，**Web Server 與 Worker 兩個進程共用同一個 class**（透過 [[AudioSource]] adapter 抽掉「音檔從哪來」這個唯一會變的點）。
_Avoid_: pipeline（暗示 declarative DAG）、runner（過泛）、TranscriptionRun（容易誤以為是 Task 本身）。

**AudioSource**:
取得單一 Task 的 [[Handoff audio]] 到本機檔案系統的 adapter，是 Orchestrator 兩進程共用的唯一變化點。`LocalFileSource` 直接回傳 router 已放在 disk 上的路徑，`cleanup()` 清掉 router 為該 task 建的 temp_dir；`S3Source` 從 `handoff/{task_id}.{ext}` 下載到 temp dir，只在 `cleanup(succeeded=True)`（任務成功）才 DELETE handoff 物件——失敗/取消時保留 handoff 供重試，殘留由 orphan sweep 收。**只負責 acquire() + cleanup()**——格式轉換在 `audio_converter`、永久儲存在 `storage_service`，都不歸 AudioSource 管。封裝在 `src/transcription/audio_source.py`。
_Avoid_: AudioFetcher、AudioProvider（過泛）、AudioAdapter（adapter 是 role 不是名字）、AudioInput（容易跟 raw bytes / file handle 等多種 input 概念混）。

**TranscriptionCancelled**:
Orchestrator 內 check_cancelled() 偵測到 Task status 已被使用者透過 cancel endpoint 設成 canceling/cancelled 時拋出。Top-level except 統一處理 cleanup 但**不**覆蓋 status（避免覆掉 cancel endpoint 寫的 cancelled）。**單一 exception class，兩個進程共用**——Orchestrator 模組搬到 `src/transcription/` 後，Web Server 與 Worker 都從同一處 import。

### 音檔形態與儲存

**Handoff audio**:
使用者上傳的原始音檔，AWS 模式下由 Web Server 透過 dispatch 寫到 `s3://{bucket}/handoff/{task_id}.{actual_ext}`（key 副檔名誠實反映實際內容）。**只是 Web Server → Worker 的傳遞暫態**，Worker 取走 + 轉成 [[Compact audio]] 後 DELETE。Local 模式對應 `temp_dir/input.{ext}`，由 router 直接交給 Orchestrator、轉完後 temp_dir 整個清掉。
_Avoid_: raw audio（過泛、容易跟「未壓縮 PCM」混）、source audio（容易跟 [[AudioSource]] adapter 混）、original（過泛）。

**Compact audio**:
使用者下載「這個 task 的音檔」時拿到的唯一形態。**契約是物理狀態的範圍，不是流程**——永久檔必須滿足全部五個屬性：
- container = `mp3`
- codec = `mp3`
- channels = `1`（mono）
- bit_rate ≤ `128000`（VBR 略有誤差，實作上保留 slack 到 ≤ ~130000）
- sample_rate ∈ `{8000, 11025, 12000, 16000, 22050, 24000, 32000, 44100, 48000}`（標準 MP3 支援的 sample rate）

由 [[TranscriptionOrchestrator]] 的 PREPARATION phase 從 [[Handoff audio]] 產生。實作策略是 **precise skip + 自適應 re-encode**：ffprobe 抓 5 個屬性，全 match 才 skip ffmpeg（保留輸入品質、節省 CPU）；任一不 match 就 re-encode，target 依輸入自適應——`channels = 1`（永遠 mono）、`sample_rate = min(input, 16000)`（不 upsample）、`bit_rate = min(input, 128000)`（不 grow）。**設計保證：re-encode 永不讓檔案變大**，只把超出契約上限的維度壓回去。儲存在 `uploads/{tier}/{task_id}.mp3`（AWS 為 S3 key，local 為 `uploads/{task_id}.mp3` 不帶 tier）。`task.result.audio_file` 指向此處，僅在 Orchestrator finalize 成功後寫入；`task.result.audio_filename` 保留使用者上傳的原 stem + `.mp3`。

**為什麼不叫 "Normalized"**：永久檔的 sample_rate **不保證一致**（不同 task 可能是 8kHz、16kHz、44.1kHz 等通過 predicate 的任何 rate）——"normalized" 暗示「屬性完全一致」會誤導。"Compact" 強調真正硬性的共同點：mono + bitrate 上限 + mp3 container。Whisper 內部一律 downsample，所以 sample_rate 對轉錄無影響；對使用者下載也只是檔案微差。

_Avoid_: normalized audio（過度承諾屬性一致性、暗示「全部 task 的永久檔屬性 identical」是錯的）、processed audio、converted audio、output audio、final audio（都不夠特定）；mp3（過泛、容易跟使用者上傳的 mp3 混）。

> **Skip predicate 為什麼必須檢全部 5 個屬性**：歷史上有兩次踩過半成品優化——`suffix == '.mp3'`（連 ffprobe 都沒查、wav 改名 .mp3 直接 crash whisper）跟 `codec == 'mp3'`（不檢 sample_rate / channels / bit_rate，44.1kHz stereo 192k MP3 也被當成 Compact audio 存進去）。**不要再寫「mp3 就跳」這種寬條件**——要嘛 5 個全檢、要嘛永遠重編。中間版本永遠是 bug。

> **舊資料**：2026-05 之前的 task 用半成品 skip predicate 產出的 `result.audio_file` 物件可能違反 Compact audio 契約（stereo、>128kbps 等）。未做 backfill——契約只承諾未來 task。

### 金流與訂單

**Order**:
一次付款嘗試的持久實體，存 `orders` collection。`type` ∈ `{subscription, upgrade_subscription, downgrade_subscription, extra_quota}`；status 生命週期 `pending → paid / failed`，外加 `superseded`（被新 checkout 取代）、`expired`（逾時未付，sweep 標記）兩個終態，首期重複完成時另標 `is_duplicate + needs_refund`。帶 `tier` / `billing_cycle` / `amount_twd` / `period_no`（藍新委託編號）/ `prev_order_no`+`prev_period_no`（升降級指向被取代的前一張）/ `extra_duration_minutes`+`extra_ai_summaries`（這張要加值的額度）。**Order document 是 checkout 與 settlement 之間的契約**——settlement 讀的欄位全是 checkout 寫進去的。封裝在 `order_repo`（partial unique index 保證同 user+type 同時只有一張 pending）。
_Avoid_: Subscription（Order 是「付款嘗試」，訂閱是它成功後對 user 的效果）、Transaction、Payment（過泛）。

**OrderSettlement**:
「把藍新 [[PaymentNotification]] 收斂成帳號狀態變更」的 deep module。兩個入口：`open_pending(draft) -> Order`（建 pending 單，含防連點冷卻 + supersede 既有 pending + 靠 DB unique index 防並發 TOCTOU）與 `settle(notification) -> SettleResult`（依 `(order_type, is_first_payment, success)` 矩陣套用 [[Settlement effect]]）。**Router 的殘留責任**：checkout 組裝（算 amount、判 upgrade/downgrade/scheduled、用 newebpay_service adapter 產 form）+ webhook 的 decrypt（adapter）+ idempotency `claim`/`release`（屬 HTTP 重試語意，留在 edge）。封裝在 `src/services/order_settlement.py`。
_Avoid_: SubscriptionService（太窄——它也管 [[Order]] 的 extra_quota MPG，那不是訂閱）、PaymentService（過泛）、把它跟 newebpay_service adapter 混（後者只負責藍新協定的加解密 / 表單 / 委託終止 API，不含任何帳號狀態邏輯）。

**PaymentNotification**:
跨 settlement seam 的 typed payload。Router 用 newebpay_service adapter 把藍新 raw form 解密、`claim` idempotency 後，交一個 typed notification 給 `settle()`。帶 `order_no` / `period_no` / `trade_no` / `success`（藍新 Status 是否 SUCCESS）/ `is_first_payment`（由藍新 `AlreadyTimes` 判定，初次建立 Notify 無此欄位即視為首期）。**`settle()` 的整個 test surface 就是這個 dataclass**——餵 plain object 即可測每一條 transition，不碰 AES、不碰 `webhook_repo`、不起 FastAPI。
_Avoid_: webhook payload（藍新 raw 加密 form 是 adapter 解密前的另一回事）、PeriodResult（藍新欄位名，不該外洩到 domain）。

**Settlement effect**:
`settle()` 對單一 [[PaymentNotification]] 算出的帳號狀態變更，共五種：**啟用訂閱**（首期成功；升級時附帶把舊方案剩餘額度結轉進 `extra_quota` + 終止舊藍新委託）、**續訂展期**（renewal 成功，只滾 `current_period_end` + 歸零 monthly usage）、**降為 free**（renewal 失敗 → `expired`）、**加值**（extra_quota MPG 成功與升級結轉共用）、**拒絕重複完成**（sibling 已先啟動 → 標 `needs_refund` + 終止多出來的委託，不重複啟用/加值）。**孤兒委託對帳收斂**（終止該 user 名下非當前 active 的已 paid 委託，防雙重扣款）是「啟用訂閱」effect 的尾段，best-effort + Sentry 警示，絕不可拋例外拖垮已成功的啟用。

### 認證與憑證

> 已落地：`src/services/credential_flow.py` + `tests/services/test_credential_flow.py`，且 `auth.py`
> 的 register / verify×2 / resend / forgot / reset×2 共 7 個 endpoint 已接線委派（edge 只留
> rate-limit + 寄信 + audit + exception→HTTP）。`registration-status` / `abandon-registration`
> 是 bounce-driven 讀取/刪除、非 token 生命週期，**不**經 CredentialFlow。

**Email credential challenge**:
一個「證明你控制某 email」的一次性憑證：高熵 token（`secrets.token_urlsafe(32)`），DB **只存 hash**（`hash_token`，清掉 legacy plaintext 欄位），帶 expiry。兩種用途共用同一形態——**帳號啟用**（verification，24h）與**密碼重設**（reset，1h）。生命週期三動作：issue（簽發 + 寄信）→ consume（驗證 + 套效果）→ preflight（唯讀預檢）。**preflight 絕不寫 DB、絕不 consume**——防 mail gateway / 連結預掃 bot 的自動 GET 把 token 燒掉（見 `auth.py` verify-email preflight 註解）。
_Avoid_: verification token（過窄，漏掉 reset）、magic link（暗示免密碼登入，非本意）、OTP（非數字碼、非短時效）。

**CredentialFlow**:
擁有 [[Email credential challenge]] 完整生命週期的 deep module，是 auth router 第一群（register / verify×2 / resend / registration-status / abandon / forgot / reset×2）深化後的形態。三入口：`issue(intent, email, password?)`（intent ∈ `{register, resend, forgot}`）、`consume(purpose, token, new_password?)`（purpose ∈ `{verify_email, reset_password}`）、`preflight(purpose, token)`。`issue` 是單一入口跑 **(intent × account_state)** 矩陣（對應 [[Settlement effect]] 的 matrix 手法）：`register` 撞 unknown→建帳號+寄驗證、verified→寄 account-exists、unverified→重簽；`resend`/`forgot` 各自的 silent 分支與 bounce 規則（含 `forgot` **故意不** skip `email_bounced`，避免真實用戶被永久鎖死）全收斂進矩陣。**自己做 `user_repo` 寫入**（建帳號 / 寫 token hash / 啟用 / 設密碼）——這是核心領域行為，不外推成指令。**只有非自己領域的副作用外推**：寄哪封信 / 不寄、要清哪些 rate-limit key、audit 描述，全由 [[CredentialOutcome]] 帶回，edge 執行。**enumeration 防護的單一守點**——「是否找到 user」與「對外回什麼 + 寄哪封信」的耦合收斂在此，不再散在 router。預計封裝在 `src/services/credential_flow.py`。
_Avoid_: AuthService（過廣——login / refresh / logout 的 session 簽發、me / preferences / delete-account 的 self-service 都**不**在此）、把 enumeration 分支寫回 router、在 module 內直接寄信（寄送是 edge adapter）。

**CredentialOutcome**:
跨 CredentialFlow → router seam 的 typed payload，也是 `CredentialFlow` 的**整個 test surface**——注入 fake `user_repo`、餵 plain `(intent, email)`，斷言寫進 repo 的 token hash / 狀態 + outcome 內容，跑遍 unknown / unverified / verified / bounced 矩陣，**不起 FastAPI、不碰 SMTP、不碰真 rate_limit_repo**。四欄：`response`（enumeration-safe 對外訊息，edge 直接回）、`email`（[[EmailInstruction]] | None）、`rate_limit_clears`（`list[(limit_type, key)]`，clear-on-success 的領域效果）、`audit`（`AuditDescriptor`：action / user_id / status_code / message，由 edge 配 `request` 落 log）。
_Avoid_: 把 HTTP status code / `Response` 物件塞進 outcome（HTTP 形態屬 edge）、把 `request` / IP 放進來（那是 edge 取的）。

**EmailInstruction**:
[[CredentialOutcome]] 內「該寄哪封信」的決策本身（不是寄送動作）。typed variants：`SendVerification(to, token)` / `SendAccountExists(to)` / `SendPasswordReset(to, token)` / `None`（不寄）。**module 決定、edge 用 `email_service` 真的寄**——這個分離讓 enumeration 不變式（unknown 與 unverified-bounced 對外不可區分）可在 module 層直接斷言。
_Avoid_: 在 module 內呼叫 `email_service.send_*`、把 email 模板內容放進來（模板屬 [[email_service]] adapter）。

**CredentialTokenInvalid / CredentialTokenExpired**:
`consume()` / `preflight()` 撞到無效 / 過期 token 時拋出的 typed domain exception（**單一處定義、兩入口共用 import**，跟 [[TranscriptionCancelled]] 同規格）。這些**非 enumeration 敏感**（token 本身即 secret），edge catch 後 map 成 400 / 410。token-invalid 不走 [[CredentialOutcome]]（沒有 enumeration-safe response 要回，直接是錯誤）。
_Avoid_: 在 module 內 `raise HTTPException`（HTTP 語意屬 edge）、用回傳 None 表達失敗（失去型別、呼叫端易漏判）。

## Relationships

- 一個 **Task** 經過三個 **Phase**（PREPARATION → TRANSCRIPTION → PUNCTUATION），完成後產出一份 **Transcription**。
- **Worker** 在執行 Task 期間持續更新 **transient progress state**；**Web Server** 透過 SSE 把 transient state 推送給前端。
- **Transient progress state** 存在獨立的 `task_progress` collection（由 ProgressStore 封裝），跟 `tasks` collection 的 **persistent task state** 完全分離。
- **OrderSettlement** 的 `open_pending` 建出一張 pending **Order**；藍新回 [[PaymentNotification]] 後 `settle` 把它推進終態並套用 **Settlement effect**（改寫 user 的 subscription / quota / usage）。Router 只負責 checkout 組裝、webhook 解密與 idempotency。
- **CredentialFlow** 的 `issue` / `consume` 對單一 [[Email credential challenge]] 算出 [[CredentialOutcome]]（含 [[EmailInstruction]] 決策 + rate-limit clear 指令 + audit 描述）；router 只負責 rate-limit check+record（pre-lookup）+ 429、用 `email_service` 真的寄信、配 `request` 落 audit、把 [[CredentialTokenInvalid]] / Expired map 成 400 / 410。session（login/refresh/logout）與 self-service（me/preferences/delete-account）不經此 module。

## Example dialogue

> **Dev:** "如果 Worker 在 TRANSCRIPTION phase 中途被 Spot 中斷，Task 的 transient progress state 怎麼辦？"
>
> **Domain expert:** "Task 本身會被 orphan-cleanup 標成 failed，persistent state 改完狀態。Transient progress state 由 `task_progress` collection 的 TTL (6 小時) 自動清。"

> **Dev:** "Worker 可不可以直接寫 overall_percentage？"
>
> **Domain expert:** "不行。Worker 只回報 phase 跟 phase_progress；overall_percentage 是 ProgressStore 算出來的 derived value。這樣兩種部署模式才共用同一張 PHASE_WEIGHTS。"

## Flagged ambiguities

- **「Phase」這個詞**：本專案專用於轉錄 pipeline 的三個階段（PREPARATION/TRANSCRIPTION/PUNCTUATION），不要拿來指 deployment phase / release phase 等。
