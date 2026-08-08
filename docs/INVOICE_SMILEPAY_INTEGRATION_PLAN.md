# SmilePay 電子發票串接設計（含 admin 訂單/發票後台）

> 狀態：設計定案 v2（2026-08-07，已含第二意見審查修正），尚未實作。API 規格見 `docs/INVOICE_SMILEPAY_API.md`。
> 範圍決策（使用者拍板）：後台＝查看＋作廢＋重試/重開；折讓先留 service 能力、不做 UI；admin 訂單列表頁（ADMIN_ROADMAP P0-3）本次一起做。
> v2 修正來源：fresh-context 審查（PASS with fixes），必改 10 項已全數回填，見各節 ★ 標記。

## 1. 目標

1. 付款成功（首購/續扣/升級/加購/換卡挽回）自動開立電子發票，資料完整落庫。
2. Admin 後台新增「訂單」頁：訂單列表＋詳情，發票狀態為一級欄位；可作廢、可重試、可修正買受人資料後重開、可看列印畫面。
3. 使用者端（BillingPanel）可看到自己訂單的發票號碼/隨機碼/開立日期。

**非目標（本次不做）**：折讓單 UI（部分退款情境，service 層預留）、捐贈/愛心碼、自然人憑證載具、對帳自動化（無 API，見 INVOICE_SMILEPAY_API.md §13）。

## 2. 總體流程

```
建單（checkout/升級/加購/續扣/update-card recovery）
  └─ 寫 order.invoice_snapshot ＋ 加購單快照 sku/label ★新增
付款成功 → OrderSettlement.settle() → outcome ∈ {ACTIVATED, RENEWED, GRANTED}
  └─ create_background_task(issue_for_order(order))  ★背景觸發，不佔 /pay、/callback 請求路徑
       ├─ 成功：invoices status=issued（InvoiceNumber/RandomNumber/InvoiceType 落庫）
       ├─ 暫時性失敗：failed + next_retry_at（backoff）
       ├─ 永久性失敗：分流（載具錯→自動降級 B2C 無載具重開；統編/抬頭錯→needs_manual+即時 alert）★
       └─ 結果不明（response 遺失）：needs_manual + alert，不自動重送 ★
背景 sweep（每 10 分鐘，lease 防多 process 並發）★
  └─ 撈 pending/failed 到期者重試；deadline 告警獨立掃描；超時仍照開（InvoiceDate=當下）★
Admin 後台
  ├─ GET  /api/admin/orders、GET /api/admin/orders/{order_no}
  └─ POST /api/admin/invoices/{id}/void | /retry | /reissue（可帶修正後 buyer）★
使用者端
  └─ 付款紀錄附發票三欄，BillingPanel 顯示
```

**開票時機決策**：settle 成功 → `create_background_task` 立即嘗試（不阻塞 91APP callback / 使用者等待的 /pay 回應；httpx timeout 30s 不會落在請求路徑上）；失敗由 sweep 補救。SmilePay 無查詢 API，同步等回應完整落庫是唯一可靠路徑，因此單次嘗試內部仍是「送出→等回應→落庫」原子序列。

**不開票的情況**：`REJECTED_DUPLICATE`（needs_refund 重複付款單）、`FAILED`；outcome 白名單制。

## 3. 資料模型

### 3.1 新 collection：`invoices`

一筆發票一個 document（作廢後重開 = 新 document，舊的標 voided，靠 `order_no` 串歷史）：

```
{
  _id,
  order_no:        str,   # merchant_order_no（非 unique——重開會有第二筆）
  user_id:         str,
  data_id:         str,   # 送 SmilePay 的自訂發票編號，unique index（冪等鍵，見 §6）
  status:          "pending" | "issued" | "failed" | "voided" | "needs_manual",
  claimed_until:   float | None,  # ★ lease：處理中的 worker 持有，防雙 process 並發
  invoice_type:    "B2C" | "B2C2B" | "B2B" | None,
  invoice_number:  str | None,
  random_number:   str | None,
  invoice_date:    str | None,
  buyer:           {...},         # 開立當下實際使用的 buyer（snapshot 或降級後結果）
  amount_twd:      int,
  attempts:        int,
  first_attempt_at: float,        # ★ 期別判定用（見 §6 跨期 gate）
  next_retry_at:   float,         # ★ 建立時即寫 now，不允許 null（sweep 撈單條件依賴它）
  deadline_at:     float,         # paid_at + 48hr(B2C)/168hr(B2B)——僅告警用，不阻止開立 ★
  last_error:      {status: str, desc: str} | None,
  voided_at:       float | None,
  void_reason:     str | None,
  allowance_numbers: [str],
  created_at, updated_at: float   # 一律 get_utc_timestamp()，勿用 datetime.utcnow().timestamp() ★
}
```

索引（`src/main.py` startup `_safe_create("invoices", ...)`）：
- `data_id` unique（併發 reissue 的最後防線）
- `order_no`；`user_id`
- `(status, next_retry_at)` — sweep 用

Repository：`src/database/repositories/invoice_repo.py`，比照 `order_repo.py`。核心方法 `claim_for_processing(invoice_id, lease_seconds=120)`：`find_one_and_update({_id, status ∈ [pending,failed], $or:[{claimed_until:None},{claimed_until:{$lt:now}}]}, {$set:{claimed_until:now+lease}})` ——**冪等與並發防護都在 invoices doc 上，不用 processed_webhooks**（★審查修正：claim/release 語意錯配會把重試全數擋死）。

### 3.2 order 新欄位：`invoice_snapshot` ＋ 加購 sku 快照

現況缺陷：發票資訊只存在 `users.invoice_info`，開票讀 user 現值會發生「訂單 A 用事後改過的抬頭開票」。修法：**建單當下快照到 order**。

```
invoice_snapshot: {
  invoice_type:   "personal" | "company",   # ★注意：user.invoice_info 的對應鍵叫 `type`，
  carrier_type:   "1" | None,               #    快照時要做 key 對映，勿直接整包複製
  carrier_num:    str | None,
  company_tax_id: str | None,
  company_name:   str | None,
}
```

寫入點（★審查修正：共五處，先前漏了 update-card）：
1. checkout 建單（`src/routers/subscriptions.py`，取 request 欄位）
2. 升級建單（同上）
3. 加購建單（同上；**同時新增快照 `sku` + `label`**——目前加購單只有 quantity/unit_price，無品名來源，發票 Description 靠它）
4. **`/update-card` 換卡挽回建單**（`type=renewal` 全額單，settle 後 outcome=RENEWED 在開票白名單內）
5. `renewal_service` 續扣建單——取 `user.invoice_info` 當下值，**經 key 對映**（`type`→`invoice_type`）後快照

既有 paid 訂單無 snapshot：不補 migration，開票 fallback 讀 `user.invoice_info`（同樣經 key 對映＋§3.3 sanity check）。

### 3.3 買受人資料品質（★審查修正：驗證要放在「開票來源」上，不只是 request model）

1. **Request model 驗證**：`company_tax_id` 加 `Field(pattern=r"^\d{8}$")`；`carrier_num` 加 `Field(pattern=r"^/[0-9A-Z+\-.]{7}$")`（**後端也要驗**，非瀏覽器 client 會繞過前端）；`invoice_type=company` 時 `company_name` 必填。
2. **`_handle_invoice_save` 支援覆蓋與清空**：現況只在有值時寫入、切換型態不清舊值 → 用戶從公司改回個人後仍會被開 B2B。改成整包覆蓋語意。
3. **開票前 server 端 sanity check**（`build_invoice_fields` 入口）：統編非 8 碼數字、company 缺抬頭、載具格式錯 → 不送 SmilePay，直接走 §4.2 的永久性失敗分流。上線前存量的髒 `invoice_info` 靠這層擋（否則每期續扣都撞 -10021）。

## 4. 後端模組

### 4.1 `src/utils/smilepay_service.py`（transport 層，照抄 payments91_service 形狀）

- class `SmilePayService`；`get_parameter("/transcriber/smilepay-grvc", fallback_env="SMILEPAY_GRVC")`、`.../smilepay-verify-key`；`SMILEPAY_ENV` 開關（預設 `test`）。
- `base_url` 切 `https://ssl.smse.com.tw/api/` vs `/api_test/`；`print_base_url` 切 `einvoice.smilepay.net/einvoice/` vs `/einvoice_test/`。
- transport：`httpx.AsyncClient(timeout=30.0)` 每呼叫新建；**一律 POST，含列印代抓**（★Verify_key 不進 URL → 不進 httpx/Sentry breadcrumb/proxy log）。
- **Sentry scrubbing**：★在 Sentry `before_send`/`before_breadcrumb` 把 `Verify_key` 加入遮罩清單（現有 scrubbing 機制若無，補一個）。
- `_parse()`：`defusedxml.ElementTree` → dict；非 XML 包成 `{"Status": "-9999", "raw": text[:500]}`，不 raise。
- 公開方法：`issue_invoice(**fields)`、`void_invoice(invoice_number, invoice_date, reason)`、`create_allowance(...)`／`cancel_allowance(...)`（預留）。金額欄位送 `ALLAmount`；`_parse()` 接受任意 root tag（作廢回應實測是 `SmilePayEinvoiceModify`，見 §9）。
- module-level lazy singleton；不自 log。

### 4.2 `src/services/invoice_service.py`（業務層）

**錯誤分類**（★審查修正核心）——`classify_invoice_error(status_code) -> "transient" | "carrier_bad" | "buyer_bad" | "unknown"`，module-level 純函數（比照 `renewal_service.classify_failure`）：

| 類別 | 錯誤碼 | 處置 |
|---|---|---|
| transient | `-10046`（愛心碼伺服器）、`-10071`（無可用字軌）、`-9999`（非 XML）、5xx | backoff 重試：5min → 30min → 2hr → 每 4hr |
| carrier_bad | `-10052/-10053/-10056/-10057/-10058`（載具錯） | **自動降級**：改 B2C 無載具（Name+Email）、換新 data_id 重開；成功後通知使用者載具未生效 |
| buyer_bad | `-10021/-10023/-10025`（統編/抬頭錯） | **needs_manual + 即時 Sentry alert**（B2B 不可擅自降級成 B2C，企業要統編抵稅；人工聯繫修正後 reissue） |
| 其他負值（明細/金額/格式類） | `-10061~-10067`、`-100410` 等 | needs_manual + alert（程式 bug 或資料異常，重試無意義） |

**`issue_for_order(db, order)`**：
1. 若該 order 已有 `issued` 的 invoice → 跳過（settle 重入防護第一層）。
2. upsert invoice doc（status=pending、`next_retry_at=now`、`first_attempt_at=now`）→ `claim_for_processing()` 拿 lease，拿不到代表另一 process 在處理 → 跳過。
3. 呼 `issue_invoice` → 依 `Status`：
   - `0` → issued＋落號碼三欄，清 lease。
   - `-10072`（data_id 重複）→ needs_manual + alert（前次已成功但號碼取不回，上速買配後台人工回填）。
   - 其他 → 按分類表處置；**所有分支都清 lease**（★重試被自己 claim 擋死的修正）。
4. 網路例外：
   - **connect error（請求未送出）**→ failed + next_retry_at，安全重試。
   - **read timeout / response 遺失（結果不明）**→ needs_manual + alert（★data_id 冪等只保證同期別內，跨期重送可能真開兩張；量少，人工核對速買配後台最安全）。

**`periodic_invoice_retry(db, interval_seconds=600)` + `run_invoice_retry_sweep(db) -> dict`**（比照 renewal_service 形狀）：
- retry 撈單：`status ∈ {pending, failed}` 且 `next_retry_at <= now`（★建立時必寫 now、欄位不允許 null，防「卡在 pending 永遠沒人撈」；防守性地仍在 query 加 `$or: [{next_retry_at: null}]`）。
- **deadline 告警獨立掃描**（★不依附 retry 條件）：未 issued 且 `deadline_at - now < 6hr` → Sentry alert；**超過 deadline 仍照常重試開立**（`InvoiceDate` 一律送當下，API 不會拒收；-10033/-10034 限制的是回填過久的日期，不是「過時不能開」）＋告警記錄稅務日期差異。
- **跨期別 gate**：重試時若當下期別（雙月）≠ `first_attempt_at` 期別 → 停止自動重試、轉 needs_manual（★data_id 防重複開票的效力只在同期別內）。

**`void_invoice_for(db, invoice, reason, admin_id)`**：types=Cancel → 成功標 voided；`-2008`（附 Nowstatus）/`-2009` 原样回給 admin。

**`reissue(db, invoice, corrected_buyer=None, admin_id)`**（★審查修正：補「作廢後重開」入口）：
- 允許 status ∈ {voided, needs_manual}；`corrected_buyer` 有值則覆蓋 snapshot（並回寫 `user.invoice_info` 供未來訂單使用，記 audit）。
- 新 data_id = `SL-{order_no}-R{n}`，`n` = 該 order 現有 invoices 最大 R 序號 +1；併發撞號由 `data_id` unique index 擋（DuplicateKeyError → 重算重試一次）。

**settle hook**：`OrderSettlement.settle()` 尾端，outcome ∈ 白名單 → `create_background_task(issue_for_order(...))`，外層 try/except log（絕不影響結算回傳）。注入：`build_order_settlement()` 加參數——**`renewal_service` 兩處呼叫點要同步改**。

### 4.3 使用者端 API

- 付款紀錄（`GET /subscriptions/orders`）附掛 `{invoice_number, random_number, invoice_date, invoice_status}`（只回 issued/voided）。`/subscriptions/status` 是訂閱摘要、無訂單列表，**刻意不附掛**（PR-C 定案 2026-08-08）。
- `BillingPanel.vue` 付款紀錄加發票欄（voided 顯示「已作廢」）；i18n zh-TW/en。
- 使用者端 PDF 下載：待 §9 spike；第一版先只顯示號碼資訊。

## 5. 開票參數對映（order → SmilePay）

| SmilePay 欄位 | 來源 | 備註 |
|---|---|---|
| `InvoiceDate` / `InvoiceTime` | 開票當下（Asia/Taipei） | `YYYY/MM/DD`＋`HH:MM:SS`；重試也用當下 |
| `Intype` / `TaxType` / `DonateMark` | 固定 `07` / `1` / `0` | |
| `data_id` | 首次 `SL-{merchant_order_no}`；重開 `SL-{merchant_order_no}-R{n}` | unique 冪等鍵 |
| `orderid` | `merchant_order_no` | ≤30 字，現有前綴格式安全 |
| `Description` | 訂閱＝`SoundLite {tier}方案({cycle})` 固定字典；加購＝order 快照的 `label`（★建單時落庫，不反推） | **禁 `\|` 與符號**，統一過 `sanitize_item_text()`（去符號、截長度） |
| `Quantity`/`UnitPrice`/`Amount` | 訂閱＝`1/amount_twd/amount_twd`；加購＝`quantity/unit_price_twd/小計` | 含稅整數；送出前驗算 `ΣAmount == AllAmount`，不合直接 needs_manual（程式 bug） |
| `AllAmount` | `amount_twd` | §9 spike：`ALLAmount` 拼法實測 |
| `Email` | user.email | SmilePay 據此寄通知/建會員載具 |
| — B2C（personal）— | | |
| `Name` | user 顯示名 → 去符號、截 30 字；空值 fallback email local-part（去符號截 30） ★清洗規則寫死 | |
| `CarrierType`/`CarrierID`/`CarrierID2` | carrier_num 有效→`3J0002`+carrier_num（明暗碼同值）；無/降級→全不帶 | 格式 `^/[0-9A-Z+\-.]{7}$` 前後端都驗 |
| — B2B（company）— | | |
| `Buyer_id`/`CompanyName` | company_tax_id / company_name | sanity check 過才送 |
| `UnitTAX` | `Y` | 含稅價送入；`SalesAmount`/`TaxAmount` 是否需帶列入 §9 spike ★ |
| `Visa_Last4` | order.card_last4（有就帶） | |

## 6. 冪等與並發防護總表（★審查後重寫）

| 風險 | 防線 |
|---|---|
| 兩個 uvicorn worker 同時 sweep／settle 與 sweep 並發 | `invoices.claim_for_processing()` lease（120s，find_one_and_update 原子搶佔）；**不用 processed_webhooks**（其 90 天 TTL 與「失敗不 release」語意會擋死重試） |
| settle 重入（ALREADY_PAID 已短路）＋殘餘 | issue_for_order 開頭查同 order_no 已有 issued → 跳過 |
| SmilePay 端重複開立 | `data_id` 同期別 unique；`-10072` → needs_manual（不自動換號重送） |
| response 遺失（送達與否不明） | needs_manual + alert，人工核對後台；不賭 -10072 |
| 跨期別重試 | 期別（雙月）變更 → 停自動重試轉 needs_manual |
| 併發 reissue 撞 R{n} | `data_id` unique index → DuplicateKeyError 重算一次 |
| deadline | 只告警（前 6hr、過線），**不停止開立** |

## 7. Admin 後台

### 7.1 後端 endpoints（`src/routers/admin.py` 新 section）

| Endpoint | 權限 | 說明 |
|---|---|---|
| `GET /api/admin/orders` | `BILLING_READ` | 列表。`_build_order_filter()`（照 `_build_audit_filter` 模式）：email 搜尋（→user_id 解析）、`status`/`type`/`tier`/`date_from/to`/`invoice_status`；`skip/limit(≤100)`＋真 total；每筆附 `invoice: {status, invoice_number, invoice_date} \| null`（aggregation `$lookup`） |
| `GET /api/admin/orders/{order_no}` | `BILLING_READ` | 詳情＋該單全部 invoices 歷史＋user email |
| `POST /api/admin/invoices/{id}/void` | `BILLING_WRITE` | body `{reason}`（≤20 字，超長 400）；audit `void_invoice`（details 含 before/after/reason/order_no） |
| `POST /api/admin/invoices/{id}/retry` | `BILLING_WRITE` | 僅 failed/pending；audit `retry_invoice` |
| `POST /api/admin/invoices/{id}/reissue` | `BILLING_WRITE` | ★僅 voided/needs_manual；body 可帶 `corrected_buyer`（同 request model 驗證）；audit `reissue_invoice` |

~~`GET /api/admin/invoices/{id}/print`~~ ——**已依 §9 spike 結果移除**（列印頁 PDF 為 client-side 產生、資產相對路徑，代抓不可行；順帶消除 HTML 轉發的 XSS 面）。

repository：`order_repo` 加 admin 全域分頁查詢。

PR-B 實作註記（PR-A 複審遺留）：
- `invoice_service.reissue()` 對非法狀態/查無 order 會 `raise ValueError`——admin router 要對映成 4xx，別讓它變 500。
- 上線前跑一次 prod 檢查：`users` 裡 `invoice_info.type=="company"` 且 `company_tax_id` 或 `company_name` 為空的筆數（存量髒資料會在開票時走 needs_manual 分流，量大要先清）。

### 7.2 admin-frontend

- Router 加 `/orders`；AdminNav 加 `v-if="authStore.can(PERM.BILLING_READ)"`。
- `AdminOrdersView.vue`：篩選/URL 同步抄 `AuditLogsView.vue`；行內操作抄 `AdminTasksView.vue`（`can(PERM.BILLING_WRITE)`+confirm+POST）。
- 欄位：訂單號、email、type、tier/cycle、金額、訂單狀態、paid_at、發票狀態 badge（issued=綠、pending/failed=黃、needs_manual=紅、voided=灰、無=–）。
- 操作：作廢（輸入原因，限 20 字）、重試（failed）、**重開**（voided/needs_manual，可展開表單修正 buyer 後送出）。
- 詳情展開：訂單欄位＋發票歷史（含每次 attempt 的 last_error）。

## 8. 設定與部署

- `.env.example`：`SMILEPAY_GRVC` / `SMILEPAY_VERIFY_KEY` / `SMILEPAY_ENV=test` 區塊（官方公開測試憑證可放 example）。
- `deploy/.env.aws`：`SMILEPAY_ENV=production`＋SSM 對照註解；`deploy/.env.aws.staging`：`SMILEPAY_ENV=test`。
- SSM：`/transcriber/smilepay-grvc`、`/transcriber/smilepay-verify-key`（SecureString）＋staging 前綴一組；確認 IAM path 權限。
- Egress 白名單（若有）：`ssl.smse.com.tw`、`einvoice.smilepay.net`。
- `requirements.txt`：`defusedxml`。

## 9. Spike 結果（2026-08-07 測試環境實測，全部完成）

1. **列印頁拿不到 PDF**：`InvoiceDetails.php` 回 `text/html`（18.5KB），PDF 是頁內 **client-side jsPDF/html2pdf** 產生；資產全是**相對路徑**（`../js/*.js`、`Barcode/*.jpg`、`qrcode_generator.php`）→ HTML 轉發資產全破、無法用。**決策：Phase 1 移除 `/print` 代抓 endpoint**（§7.1 原第 6 支砍掉，XSS 面同時消失）。admin 日常看資料用我方詳情頁（號碼/隨機碼/金額齊全）；需正式證明聯的罕見情況走速買配後台人工。未來如需自產證明聯 PDF 另開 issue（QR/barcode 格式工程量不小）。
2. **`ALLAmount` / `AllAmount` 兩種拼法都接受**（ASP 參數不分大小寫）；統一用官方範例的 `ALLAmount`。
3. **SmilePay 是否寄 email**：curl 無法驗證，**staging 驗證時用真實信箱開一張確認**（影響通知信分工，未定案前我方先不自寄）。
4. **測試環境不驗載具**：`3J0002`＋`/ZZZZZZZ` 竟回 `Status=0` 且照存 → 測試環境寬鬆，**-10056 類錯誤只會在 prod 發生**。含義：(a) 我方 regex 預檢是實質防線；(b) 降級分類表保留（prod 行為以官方錯誤碼表為準）；(c) staging 測不到降級路徑，單測要補 fake。
5. **作廢實測成功**（`types=Cancel`）＋兩個文件外發現：**回應 root tag 是 `SmilePayEinvoiceModify`**（非文件寫的 `SmilePayEinvoice`）、`CancelDate` 是 dash 格式 → `_parse()` 必須接受任意 root tag。當期作廢 OK；跨期作廢行為未測（測試帳號無跨期舊票），admin 作廢失敗時把 `-2008`/`Nowstatus` 原样呈現即可。
6. **B2B 不帶 `SalesAmount`/`TaxAmount` 可成功開立**（`UnitTAX=Y`，回 `InvoiceType=B2C2B`，符合文件「有統編可作廢」語意）→ 不帶，由速買配自算。
7. **期別邊界**：無法在單日實測（需跨雙月邊界）。§6 跨期 gate 依文件語意保留（保守設計，成本低）。

實測開出的測試發票：AB59856552（B2C）、AB59856553（B2C，已作廢）、AB59856554（B2C 壞載具）、AB59856555（B2C2B）。spike 腳本在 scratchpad `smilepay_spike.sh`。

## 10. 測試計畫

- 單測：`build_invoice_fields` 對映（B2C 無載具/手機條碼/B2B/加購/金額驗算/Name 清洗）、`classify_invoice_error` 全分支、lease 搶佔與釋放、sweep 撈單（含 next_retry_at=null 防守）、deadline 告警獨立性、跨期 gate、降級重開、settle hook 白名單與吞例外、reissue R{n} 併發、admin endpoints（權限/驗證/audit）。`tests/services/test_invoice_service.py`、`tests/routers/test_admin_orders.py`。
- **Staging 實測**（memory：測試一律上 staging）：SmilePay 測試憑證跑全鏈路——checkout→settle→開票→admin 查看→作廢→修 buyer 重開→列印；驗 DB 與速買配測試後台一致；載具錯誤降級路徑實測一次。
- 高風險驗收：diff 碰 `subscriptions.py`/payment → judgment-rubrics §5 第 4 條：`/security-review`＋fresh-context 第二意見。

## 11. PR 切分（依賴順序）

1. **PR-A 後端核心**：spike（§9）→ `smilepay_service`＋`invoice_repo`＋`invoice_service`＋settle hook＋五處建單快照（含 sku/label、key 對映）＋buyer 驗證三層（§3.3）＋sweep＋單測。
2. **PR-B admin 訂單/發票頁**：6 支 endpoints＋`AdminOrdersView.vue`＋nav/router＋audit＋測試。
3. **PR-C 使用者端**：付款紀錄附發票欄＋BillingPanel＋i18n。
4. **部署待辦**（隨 PR-A 上 staging）：SSM 參數、requirements、egress。

一律 merge commit、feature → main → staging 驗證 → aws。
