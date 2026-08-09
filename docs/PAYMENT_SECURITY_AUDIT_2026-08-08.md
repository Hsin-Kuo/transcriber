# 金流子系統資安體檢報告（2026-08-08）

> 範圍：91APP Payments（信用卡/續扣 cardToken）+ SmilePay 電子發票整條鏈路。藍新 NewebPay 已全刪。
> 方法：三個 fresh-context opus agent 對抗式審查（維度 A 憑證/認證授權、B 輸入驗證/金額完整性、C 冪等/競態/狀態機），主對話覆核支柱事實去重整併。
> 覆核已確認的支柱：`natural_id = f"{trade_id}:{record_status}"`（subscriptions.py:209）、settle 短路 `if n.is_first_payment and status=="paid"`（order_settlement.py:142）、prod `WEB_CONCURRENCY=2`（transcriber.service:13）、`RUN_BACKGROUND_JOBS` 純 env 無 leader lock（main.py:396）、card_token 明文（order_settlement.py:265）、company_name 無過濾進 PDF（receipt_generator.py:196）。
>
> **整體風險評級：高**。無「匿名直接竊取資金」路徑，但有多條「重複結算 / 免費續用 / 雙倍權益 / 使用者可觸發 SSRF」路徑，且 prod 併發模型（雙 worker 無 leader lock + 整包 $set）會放大其中數條。

---

## P0 — 上線前必修（資金損失 / 資料外洩 / 使用者可觸發）

### P0-1　續扣單可被重複結算
`subscriptions.py:209` 的去重鍵 `natural_id = f"{trade_id}:{record_status}"` 把 recordStatus 納入 key，而 `order_settlement.py:142` 的 ALREADY_PAID 短路**只在 `is_first_payment=True` 時生效**（`type=renewal` 恆 False，無重入防線）。
- **場景**：91APP 對同一筆 trade 依 recordStatus 演進送多次 callback（授權 4 → 請款 5，ASSESSMENT §6.1 已載），兩封 natural_id 不同（`trade:4` / `trade:5`）都 claim 成功 → 續扣分支跑兩次 → `current_period_end` 以第二封時間重算（多送服務天數）、`reset_monthly_usage` 再歸零（當期用量白洗）、期末降級的 `pending_plan_change` 被清空（下期仍按高價扣）。`/pay`（傳 statusCode）與 `/callback`（傳 recordStatus）也互不去重。
- **修法**：settle 短路拿掉 `is_first_payment` 條件，`status=="paid"` 一律回 ALREADY_PAID（續扣靠 deterministic order_no 區分期別，不需靠這個重入）；`natural_id` 統一成 `trade_id`（或 order_no），recordStatus 演進交給 order 狀態機。
- 交叉印證：三個維度各自獨立命中（A callback 隱含 / B-F3 / C-F1）。

### P0-2　背景 sweep 多 worker 並行 + 訂閱整包 $set → 續扣成功被降級蓋掉
prod `WEB_CONCURRENCY=2`，`RUN_BACKGROUND_JOBS` 是 per-process env（`main.py:396`），無 leader lock → **兩個 uvicorn worker 都跑 `periodic_renewal_check`／`periodic_invoice_retry`**（`RUN_BACKGROUND_JOBS=false` 只能區分跨 EC2 replica，區分不了同機 worker）。而 `user_repo.update_subscription`（:261）全系統都做「讀整包 sub → 改 → `$set` 整包」，無樂觀鎖、無條件更新。
- **場景**：dunning 第 6 天（重試 4 次×2 天 ≈ 寬限 6 天，branch2 重試與 branch3 寬限到期同時成立）：worker A 續扣成功寫入 active+新週期；worker B 的 branch3 在 A 寫入前已讀到 past_due，整包 `$set` 把剛續約的訂閱蓋回 expired + 降 free → **使用者被扣款卻掉到免費方案**，並釋放釘選音檔。
- **修法**：(a) 背景 sweep 改 DB leader lease（processed_webhooks 同款 `_id`+TTL）或搬成獨立 systemd timer/oneshot，別靠 env 區分 worker；(b) 訂閱狀態變更改帶條件的 dotted `$set`（`{"_id":..., "subscription.status":"past_due"}`）。
- C-F3 / C-F9。

### P0-3　權益先施後寫狀態 → 一次付款雙倍額度
`order_settlement.py:286-295`（extra_quota `add_extra_quota` 是 `$inc`）與 `:247-251`（升級舊額度結轉，同 `$inc`）**先施加權益、order 狀態後寫**，中間無原子閘門，重入判定是 check-then-act 讀 `order.status`。
- **場景**：`/pay` 無 3D 立即成交，settle 已 `$inc` 尚未寫 `status=paid`；callback 打進另一個 worker（claim key 不同，見 P0-1）→ 也讀到 pending → 再 `$inc` 一次 → **雙倍額度**。`$inc` 後 update 失敗或進程重啟亦同。
- **修法**：先搶單再施效果——`update_one({merchant_order_no, status:{"$ne":"paid"}}, {"$set":{"status":"paid",...}})`，`modified_count==1` 才 `$inc`；否則回 ALREADY_PAID。
- C-F2。

### P0-4　收據 PDF markup injection → 使用者可觸發 blind SSRF + 收據 500
`company_name` 在 request model 是裸 `Optional[str]`（無 pattern/max_length），`_handle_invoice_save` 原樣寫入 `user.invoice_info`，`receipt_generator._invoice_line`（:196）直接 f-string 組成字串丟進 ReportLab `Paragraph()`。ReportLab Paragraph 解析 XML-like markup（`<img src>`/`<link>`），實測 4.5.1 `trustedSchemes` 含 `http/https/file/ftp`、`trustedHosts=None`。
- **場景**：已付款使用者 `POST /purchase-extra`（開票路徑有 sanitize、PDF 路徑漏了）帶 `company_name="<img src='http://internal:8000/x' width=1 height=1/>"` + `save_invoice=true`（建單當下即寫入，不需完成付款）→ `GET /order/{paid_no}/receipt` → prod web EC2 主動對內部 URL 發 GET（blind SSRF，`file://` 同樣放行）；非圖片回應 → `UnidentifiedImageError` 未捕捉 → 收據端點 500。同一 sink 的 `order.trade_id`（:253）取自未認證 callback payload。
- **修法**：request model `company_name` 加 `max_length=60` + 開票前既有的 `sanitize_item_text`；`receipt_generator` 所有動態值套 `xml.sax.saxutils.escape`；啟動時 `reportlab.rl_config.trustedSchemes=[]`（本專案 PDF 從不需外部資源）。
- B-F1。**agent 本機驗證會實際發出對外請求**。

---

## P1 — 金流正確性 / 上線 gate

### P1-5　退款 / 爭議款不撤銷訂閱
`order_settlement.py:148` 對已 paid 單的失敗通知（recordStatus 6 部分退款 / 7 全額退款 / 3 取消）一律 `status="failed"`，不動 subscription / extra_quota / invoice、不標 `needs_refund`、不告警。
- **場景**：付 Pro 年繳 10,989 → active +1 年 → 向發卡行全額退款 → callback recordStatus=7 → 落 failed 分支（或被 P0-1 的 ALREADY_PAID 短路先吃掉）→ **錢退了、Pro 留一整年、發票仍 issued**。
- **修法**：`interpret_record_status` 拆 `refunded`(6/7) 獨立語意；settle 加 refund 分支：已 paid 的訂閱單呼叫 `_expire_to_free`+Sentry alert+連動發票作廢，extra_quota 單扣回額度。**需產品決策**（退款是否即時降級 vs 期末），建議開 issue 排下個金流 PR。
- B-F2 / C-F8。

### P1-6　prod 環境變數 fallback → 可能用公開測試帳號開真客戶發票
`SMILEPAY_ENV` 預設 `test`、`PAYMENTS91_ENV` 預設 `sandbox`，`deploy/.env.aws` 兩行都還註解著，無啟動驗證；`config_loader.get_parameter` SSM 失敗靜默 fallback 到 env，而 `.env.example` 的 SmilePay 值是**速買配官方公開測試帳號**（`Verify_key` 在公開文件明文可得）。
- **場景**：上線忘記解註解、或 SSM 一時不通觸發 fallback + 機器 `.env` 殘留範例值（memory 記載 prod 曾因殘留 .env 跑 4 個月 medium，同類故障）→ 真客戶發票（姓名/Email/統編/載具 PII）開到公開帳號 `SEI1004730` → 任何人持公開 `Verify_key` 可作廢我方客戶發票 / 讀發票明細。
- **修法**：`__init__` fail-fast：`DEPLOY_ENV=aws` 且 `APP_ENV=prod` 時 `SMILEPAY_ENV!=production` 直接 `RuntimeError`；金流/發票類 SSM 參數讀取失敗不 fallback（`get_parameter(required=True)`）。
- A-F4。

### P1-7　renewal sweep 無 per-item try/except → poison doc 癱瘓整輪扣款
`renewal_service.run_renewal_sweep` 的 `async for` 無 per-user try/except（invoice sweep 有，這裡漏），`_attempt_charge` 先 claim 後建單。
- **場景**：past_due 使用者走 `/update-card` 建了一張 pending recovery 單 → sweep 掃到他：claim 成功 → `order_repo.create` 撞 `(user_id,type)` partial unique index → `DuplicatePendingOrderError` 拋穿整個 sweep → **整輪中止**（其他到期使用者本輪不扣款）；且 claim 已佔用 → 該使用者後續輪次被 claim 擋掉，白損 3 次重試機會直到第 6 天降級。同形引信：舊藍新遺留訂閱缺 `billing_cycle`（KeyError）、`get_subscription_price` 回 None。
- **修法**：每筆使用者包 try/except（例外時 release claim 讓下輪可重試）；建單前查同 user in-flight pending renewal 沿用/supersede，或 recovery 單用獨立 type 避 unique index。
- C-F4。

### P1-8　/callback 未認證 + 無 IP allowlist + 無限流 + trade_id 未驗證未 encode
`location = /subscriptions/callback` exact match 優先於 `limit_req` 的 regex location → 無限流；兩份 nginx 都停在 `# TODO: 補 91APP 來源 IP allowlist`；`trade_id` 取自 payload 未驗格式即拼進 `f"/v2/trades/{trade_id}"` 並用我方 shared secret 簽章。
- **場景**：`tradeId` 具日期+流水結構可枚舉。(a) 送 `{tradeId:<猜測>, bindingStatus:"Failed"}` 命中「已 3D 成功但真 callback 未到」的首購單 → 回查 success 但 payload `bindingStatus!=Succeeded` → order 標 failed，真 callback 隨後被 `duplicate_skipped` → 使用者扣款卻永久不啟用（無限流讓枚舉零成本）。(b) `{tradeId:"X?merchantOrderId=victim"}` 注入 query（`../` 路徑穿越被 httpx 正規化擋，但 query 注入能過簽章）。
- **修法**：nginx 補 `allow 91APP_CIDR; deny all;` + `limit_req zone=webhook`；`trade_id` 先驗 `^[A-Za-z0-9_-]{1,64}$` + `urllib.parse.quote(safe="")`；`bindingStatus` 不可作判定來源，改以回查結果為準。⚠️ IP allowlist 需搭配 P2-15 的 real_ip 修正（否則擋錯對象）。
- A-F1 / B-F4。

### P1-9　對帳補償未實作 → callback 遺失即靜默漏單
ASSESSMENT §6.1 自訂「callback 不可依賴重送，需自建定時掃 pending 主動回查」——未實作。`/callback` 的 `query_trade` 逾時 → raise 500 → 91APP 不重送 → `periodic_order_cleanup` 於 T+1h 標 expired → **使用者已扣款、無訂閱、無發票、無告警**。
- **修法**：加對帳 sweep 掃「已進入付款（有 trade_id）但仍 pending/expired」的單主動回查 91APP 收斂；標 expired 前先查一次。
- C-F5。

---

## P2 — 硬化 / 縱深防禦

| # | 問題 | 位置 | 修法 |
|---|------|------|------|
| P2-10 | **card_token 明文存 DB**（orders + users.subscription 雙份，token 無效期免 CVV） | order_settlement.py:226,265 | KMS/AES-GCM envelope 加密，扣款當下解密；settle 後 `$unset` orders 那份避免雙份 |
| P2-11 | **Sentry 漏遮 91APP API key**（`N1-API-KEY` 連字號寫法不在 `_SENSITIVE_SUBSTRINGS`；payments91 `_post/_get` 無 httpx 例外處理，逾時例外的 frame local `headers` 明文進 Sentry） | sentry_init.py:13 / payments91_service.py:64 | 補 `api-key`/正規化 `-`→`_` 再比對；payments91 加 httpx try/except |
| P2-12 | **停用/降級帳號 refresh 不撤銷**（`/auth/refresh` 不查 is_active/deleted_at、role 沿用舊 claim；停用只寫 is_active 不清 refresh_tokens） | auth.py refresh 端點 / admin.py:356 | refresh 重讀 DB 檢查 is_active + role；停用時清 refresh_tokens（credential_flow.py:374 有先例） |
| P2-13 | **開票單一 fire-and-forget 起點**（settle 內 create_background_task 是唯一起點，doc 沒 upsert 成功時 sweep 只掃 invoices 補不到） | order_settlement.py:167 / invoice_service.py:468 | sweep 補「orders.paid 超過 N 分且無 invoice doc」查詢，或 settle 標 paid 同步落 pending invoice doc |
| P2-14 | **reissue 同 order 多非活躍 doc 時仍可雙開票**（per-doc lease vs per-order check 非原子，兩 admin 對 needs_manual+voided 兩顆 doc 同時重開各算不同 R{n}） | invoice_service.py:584 | 對 `{order_no, status∈{issued,pending,failed}}` 建 partial unique index，第二個 create 由 DB 擋 |
| P2-15 | **XFF 來源 IP 可偽造**（既有，與 GEO_BLOCK_CN_PLAN 同源；nginx 缺 real_ip、後端取 XFF[0]） | audit_logger.py:22 / nginx | `set_real_ip_from` CF 網段 + `real_ip_header CF-Connecting-IP`；後端讀 X-Real-IP |

---

## 核對過、確認無 finding（避免重複勞動）

- HMAC 簽章公式正確（`base64(lowercase_hex(HMAC-SHA256(payload, shared_secret)))`，key 用原字串，簽 A 送 A 無錯位）；callback 不信 payload、以回查 recordStatus 判成敗（PR#316 修正正確、無殘留 statusCode 誤用）；`interpret_record_status` fail-closed；admin void/retry/reissue 三支全掛 BILLING_WRITE 且 admin_role 即時讀 DB（無 `None→SUPERADMIN` 後門）；使用者端 IDOR 有 owner 過濾；`/payment-config` 只下發 publishable_key；SmilePay 列印 URL（含 Verify_key）已全 repo 零引用；金額全由後端價格表決定（request model 無 amount 欄位）；NoSQL injection 無可用路徑（FastAPI 型別 + pydantic lax mode 擋掉 operator 走私）；發票欄位送 SmilePay 有 sanitize + 雙層 regex + ΣAmount 驗算；defusedxml 擋 XXE；前端無 v-html（Vue 插值 escape）；生產 CORS 強制鎖定；CSP 未為 91APP SDK 放寬 unsafe-*（現存 unsafe-eval 是 vue-i18n 既有議題）；webhook claim 原子（`_id` unique insert）；invoice lease 三道防線對「即時 vs sweep vs admin_retry」互斥有效；跨期 gate / deadline 告警去重正確；`/reactivate` 不構成免費升級。

---

## 建議處理順序

1. **一行/低風險先清**：P2-11（Sentry 遮蔽，一行）、P0-4 的 escape 部分（receipt escape + trustedSchemes 清空，兩行即消 SSRF+500）。
2. **上線 gate（prod 前必做）**：P1-6（env fail-fast）、P1-8 的 nginx allowlist（部署待辦已列）+ trade_id 驗證。
3. **併發正確性（本輪金流最核心）**：P0-1、P0-2、P0-3 應綁一個 PR 一起修（都繞著「settle 重入 + 整包 $set」的同一根因）+ staging 真實交易實測。
4. **韌性**：P1-7（sweep 隔離）、P1-9 / P2-13（對帳與補洞 sweep）。
5. **需產品決策**：P1-5（退款撤訂閱語意）—— 開 issue。
6. **硬化**：P2-10（card_token 加密）、P2-12（refresh 撤銷）、P2-14（reissue partial index）、P2-15（real_ip，與 geo-block 一起）。

> 依 judgment-rubrics §5，以上任一修改都動 payment/webhook，合併前走高風險驗收（/security-review + fresh-context 第二意見），行為驗證依 feedback_test_on_staging 在 staging 跑真實交易（尤其 refund 與併發路徑）。
