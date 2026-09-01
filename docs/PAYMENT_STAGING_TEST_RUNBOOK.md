# 金流體檢 staging 真實交易實測 Runbook

> 把上線 checklist（`PAYMENT_AUDIT_GOLIVE_CHECKLIST.md` §6）的實測項展開成可逐條執行的步驟。
> 目的：本地全是 unit + mock + 真 Mongo repo 測試,**沒有一項跑過真實 91APP sandbox 交易**——
> 這份 runbook 是唯一能關掉「mock 驗證 vs 真實驗證」落差的東西（依 `feedback_test_on_staging`）。
>
> 圖例:💻 可腳本化（curl / mongosh / aws,可貼指令）｜🖱️ 必須手動（瀏覽器走 3DS 刷卡,無法純腳本）｜🔍 驗證（查 DB / Sentry / log）
>
> **這份是操作指南,不是程式碼。跑之前先確認前置（§0）都到位。**

---

## §0 前置（跑任何項目前先完成）

- [x] **staging KEK 已 seed**：`/transcriber-staging/card-token-kek`（2026-08-09 已 seed,SecureString,32 bytes 驗過）。沒有它 `/pay` 的 card_token 加密會走 F2 fallback（略過不存）→ 續扣類全跑不起來。
- [ ] **staging 已部署最新 main**：`Deploy to Staging` workflow success（本批已於 merge staging 後綠燈）。KEK 是 seed 在部署之後,`_get_kek` 為 lazy read,下一筆 `/pay` 就會讀到;要百分百確定可再觸發一次 staging 部署。
- [ ] **金流 env**：staging 走 `PAYMENTS91_ENV=sandbox` / `SMILEPAY_ENV=test`（已是預設,勿設 production——staging 是 `APP_ENV=staging`,`validate_payment_env` 不檢查 KEK、也不該打正式帳號）。
- [ ] **連線工具備妥**（下面步驟會用到）：

```bash
# staging Atlas 連線字串（獨立 project transcriber-staging，M0）
STG_MONGO=$(aws ssm get-parameter --name /transcriber-staging/mongodb-url \
  --with-decryption --region ap-northeast-1 --query 'Parameter.Value' --output text)
# 用法：mongosh "$STG_MONGO" --quiet --eval '...'

# staging 後端 log（SSH 到 staging web；金鑰/IP 見 STAGING_PLAN.md / reference_aws_resources）
# journalctl -u transcriber -f    （在 staging web 上）
# 或看 Sentry：environment = staging-*（SENTRY_ENVIRONMENT）
```

- **測試卡（ASSESSMENT §12,期限一律 12/34、CVV 任意）**：
  - 成功：`4503 0749 6961 8452`
  - 3DS 失敗（Failured3DS）：`4800 8957 3345 1295`
  - 銀行拒絕（RefuseTrade）：`4720 8940 9183 3605`
  - 卡過期（cardExpired）：`5442 2801 8461 3035`

- **入口**：使用者端 `https://staging.soundlite.app`、admin `https://admin-staging.soundlite.app`。

---

## §6a 併發 / 狀態機（PR #324 P0-1/2/3、#325 P1-9）

### A1. 首購 3DS 全鏈路 + card_token 落庫（最基礎,先過這關）
1. 🖱️ staging.soundlite.app 登入測試帳號 → 選方案 → checkout → 用**成功卡** `4503 0749 6961 8452` 走完 3DS。
2. 🔍 DB 驗證：
```bash
mongosh "$STG_MONGO" --quiet --eval '
  const u = db.users.findOne({email:"<測試帳號>"});
  print("sub.status =", u.subscription.status);            // 應 active
  print("card_token 前綴 =", (u.subscription.card_token||"").slice(0,3));  // 應 v1:（密文,已加密）
  print("active_order_no =", u.subscription.active_order_no);
'
```
3. 🔍 對應 order：`db.orders.findOne({merchant_order_no:<order_no>})` → `status:"paid"`,且 **`card_token` 欄位不存在**（settle 後 clear_card_token $unset,P2-10）。
4. 🔍 log/Sentry：不應出現 `subscription.pay.card_token_encrypt_failed`（出現=KEK 沒讀到,回 §0）。

**這關過 = KEK + 加密 + settle + $unset 全鏈路通。** 沒過先別往下。

### A2. 同一 trade 4→5 兩封 callback 不重複結算
- 91APP sandbox 對同一筆會依 recordStatus 演進送多封。🔍 A1 完成後查 `db.processed_webhooks.find({_id:/^91app:/})`——同 trade 的第二封應被 `duplicate_skipped`（claim natural_id 已收斂成 trade_id,不含 recordStatus）。log 找 `subscription.webhook.duplicate_skipped`。

### A3. lease 跨 worker（需臨時把 staging 調成雙 worker）
- staging 預設 `uvicorn --workers 1`,單 worker 測不到「雙 worker 搶 lease」。
- 🖱️ 臨時把 staging 的 `WEB_CONCURRENCY=2`（`/opt/transcriber/.env` 或 systemd）並重啟,製造併發背景 sweep。
- 🔍 觀察 `db.job_leases` —— 同一時間窗（`_id = "<job>:<window>"`）只有一顆 doc;log 不應出現同一 sweep 同輪跑兩次。驗完**改回 `WEB_CONCURRENCY=1`**。

### A4. 使用者端點 guard 409
- 💻 併發打同一帳號的 `/subscriptions/cancel` 兩次（或 cancel 與 reactivate 交錯）,其中一個應回 `409 SUBSCRIPTION_CONCURRENT_UPDATE`（樂觀鎖 guard 命中）。
```bash
# 需帶登入 cookie；兩條並行
curl -s -X POST https://staging.soundlite.app/subscriptions/cancel -b "<cookies>" -o /dev/null -w "%{http_code}\n" &
curl -s -X POST https://staging.soundlite.app/subscriptions/cancel -b "<cookies>" -o /dev/null -w "%{http_code}\n" &
wait
```

---

## §6b 退款（PR #327 P1-5、#335 F4/F6）

前置：先有一張 A1 產生的 active 訂閱單。退款動作在 **91APP sandbox 後台**對該 trade 發起（或用 sandbox API）。

### B1. 全額退款（recordStatus 7）→ 即時降 free + 發票作廢
1. 🖱️ 91APP sandbox 對 A1 的 trade 發全額退款 → 觸發 callback。
2. 🔍 `db.users.findOne` → `subscription.status:"expired"`、`quota.tier:"free"`、**`subscription.card_token:""`**（F6 清空）。
3. 🔍 `db.orders.findOne` → `refund_processed:true`、`refunded_at` 有值。
4. 🔍 發票：`db.invoices.findOne({order_no:...})` → 狀態 `voided`(自動作廢)或 needs_manual（作廢失敗）。
5. 🔍 Sentry：`payment.refunded_subscription_revoked`(warning)。

### B2. 部分退款（recordStatus 6）→ 人工,不動權益
- 🖱️ sandbox 發部分退款 → 🔍 order `refund_seen:true` + `needs_manual:true`;訂閱**不變**（權益不動）;Sentry `payment.partial_refund_needs_manual`。

### B3. rs=6→7 時序 → 全額仍 revoke
- 🖱️ 先部分退再升級全額退（同 trade）→ 🔍 部分退標 needs_manual 後,全額退**照樣**把訂閱 revoke（F1 拆閘門後 6 不擋 7）。

### B4. 退「重複完成單」不誤殺正常訂閱（H1 回歸,若能造出重複單）
- 需先造出 is_duplicate/needs_refund 的重複完成單（過冷卻重開 checkout 兩張都完成）。退那張重複單 → 🔍 正常付款啟用的訂閱**不受影響**、不被降級。

### B5. 回寫廠商資料（重要,關掉推論缺口）
- 🔍 B1–B4 過程中把 `GET /v2/trades/{id}` 對 **6/7 退款** 的實際回應形狀 dump 下來,回寫 `ASSESSMENT §12`——目前退款分支的判定建立在推論上。

---

## §6c 對帳 / 開票補洞（PR #325 P1-9、#328 P2-13）

### C1. callback 遺失 → 對帳 sweep 主動收斂
- 🖱️ 造一筆「已扣款但 callback 沒進來」：sandbox 完成付款後,人為讓 callback 失敗（或直接在 DB 把一張 paid-in-91APP 的單留成 pending + 有 trade_id）。
- 🔍 等對帳 sweep（`payment_reconciliation`,600s 一輪）→ 該單被回查收斂;Sentry `payment.reconciled`(warning)。log `payment.reconciliation.resolved`。

### C2. entitlement_pending 被 resettle 補施
- 🖱️ 難自然造（要 settle 中途 crash）;可在 DB 手動標一張 paid 單 `entitlement_pending:true, entitlement_retry_count:0` → 🔍 resettle sweep 補施權益 + 清旗標 + 補開發票。**F1 驗證**：若該單同時 `refund_seen:true`,resettle 必須**跳過**（不重開）,標 needs_manual。

### C3. 開票補洞 sweep（P2-13）—— 預設 no-op
- ⚠️ `INVOICE_GAP_EPOCH` **未設 → gap sweep 是 no-op**（安全預設）。要測需先在 staging 設 `INVOICE_GAP_EPOCH=<現在的 unix 秒>`,再造一張「paid 但無 invoice doc」的單 → 🔍 sweep 補開 + Sentry `invoice.gap_recovered`。測完視需要移除 epoch。

---

## §6d 綁卡 / 續扣 / dunning（PR #323 P1-8、#331 P2-10、#334 F5、#335）

### D1. 續扣（MIT 免 3D）用加密 token
- 🖱️/🔍 A1 產生的 active 訂閱,把 `subscription.next_charge_at` 在 DB 改成過去時間 → 等 renewal sweep（1800s;或臨時縮短）→ 🔍 應成功續扣、`renewal.charge.success`。**驗證**：續扣讀的是 `subscription.card_token`（v1: 密文）,renewal 內解密後餵 91APP——若解密失敗會走 `CardTokenDecryptError`→needs_card_update（不該發生,發生=KEK 問題）。

### D2. dunning 分流（Failured3DS / RefuseTrade / cardExpired）
- 🖱️ 用不同測試卡跑失敗續扣,🔍 對照 `classify_failure`：`cardExpired`/`CardNumberWrong`→needs_card_update（不自動重試）;`RefuseTrade`→retryable（排 next_retry_at）;耗盡 4 次→降 free。
- 🔍 **F5 驗證**：在 grace 快滿時對該帳號 `/reactivate`,同時等 expiry sweep——reactivate 後的訂閱**不該**被 sweep 蓋回 expired+free（樂觀 guard）。

### D3. 首購 3DS response 形狀回寫（關掉最大推論缺口）
- 🔍 A1 完成 3DS 後,dump `GET /v2/trades/{id}` 首購+3D 的實際回應——確認 (a) cardToken 是否在 3D 之後才出現、(b) `bindingtoken` 是否為 MIT 可用 token（N3）。回寫 `ASSESSMENT §12`。這是綁卡 gate 與補救寫回的判定依據,目前是推論。

---

## §6e 環境 / IP（PR #326 P1-6、#329/#330 P2-15）

### E1. P1-6 不誤擋 staging
- 🔍 staging（`APP_ENV=staging`）金流走 sandbox/test、未被 P1-6 fail-fast 誤擋——A1 能跑起來就已間接驗證。

### E2. real_ip / X-Real-IP（依賴 origin 鎖定,staging 未鎖定前為半套）
- ⚠️ origin 未鎖定（SG 還開著）前,`X-Real-IP` = 直連來源或 CF edge,非真實 client IP。
- 🖱️ staging 先做 origin 鎖定（checklist §3,SG 收斂到 CF prefix）後,🔍 nginx access log 的 client IP 應變成真實來源(非 `172.68.x.x` CF edge);rate limit key 變 per-source。
- 💻 直連驗證：`curl -sI --max-time 5 http://52.196.120.189/ -H 'Host: staging.soundlite.app'` → origin 鎖定後應 timeout（經 CF 才通）。

---

## 通過標準 / 收尾

- §6a A1 是 gate：不過不往下。
- 每一項「回寫 ASSESSMENT §12」的資料缺口（B5、D3）補完,才算把「判定建立在推論上」這件事關掉。
- 驗完把臨時改動還原：`WEB_CONCURRENCY` 改回 1、`INVOICE_GAP_EPOCH` 視需要移除、DB 手動造的測試 doc 清掉。
- staging 實測全綠 + 資料回寫後,才進 checklist §5（geo-block）與 prod 上線序列。

> 註：大量步驟需人工在瀏覽器走 3DS 刷卡（91APP 無 headless sandbox API 可完整模擬 3D 導頁）,
> 無法做成全自動腳本。可腳本化的是 DB 驗證、併發 curl、直連檢查;3DS/退款觸發是手動。
