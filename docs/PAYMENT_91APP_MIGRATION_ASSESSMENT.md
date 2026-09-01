# 金流遷移評估：NewebPay → 91APP Payments

> 狀態：**評估中（尚未決策）** ｜ 建立：2026-07-15 ｜ 更新：2026-07-19 ｜ 現行金流：藍新 NewebPay
> 依據：91APP Admin API — Payments 官方文件（introduction / API spec / frontend-sdk / error-handling / faq）＋ 本 repo 金流耦合調查。
> **2026-07-19 完成公開文件窮舉驗證**：全站導覽頁（Docusaurus chunk 解析確認無漏頁）＋ 完整 OpenAPI spec（自 webpack chunk 還原）逐欄位檢查 ＋ Web SDK 實檔掃描。本文引述均經逐字比對。
> 兩題「生死題」（續扣免 3DS、cardToken 生命週期）未經 91APP 書面確認前，**不建議啟動遷移**。待確認清單見 `PAYMENT_91APP_VENDOR_QUESTIONS.md`。
>
> **🟢 2026-07-24 更新：生死題已由 91APP 窗口書面確認，核心 go/no-go 閘門通過。**
> ① 續扣**可免 3D**——`request-by-cardToken` 須**同時**帶 `productType=Subscription` **與** `subscriptionType=Renewal`；首筆綁卡仍需 3D。
> ② cardToken **本身無效期、無閒置失效**，可長期保存；惟**實體卡到期/掛失**須重新綁卡並取得**新 cardToken**。
> ③ 續扣為**商戶主動觸發**，91APP **不提供** gateway 端排程。→ 續扣排程器＋dunning＋換卡流程確認為必做（工作量＝高，見 §10）。詳見 VENDOR_QUESTIONS「已由 91APP 窗口確認」。

---

## 1. 總結（TL;DR）

- **複雜度：中偏高。** 不是 adapter 換寫，而是**付款範式(paradigm)轉換**。
- 好消息：現行架構 adapter 邊界乾淨——藍新協定幾乎全鎖在 `src/utils/newebpay_service.py` 一檔，`OrderSettlement` 狀態機已與協定解耦。
- 壞消息：91APP 續扣是**商戶自扣 (merchant-initiated)**，需**自建續扣排程器 + 催收(dunning) + 換卡 + 存量遷移**基礎設施，這是專案目前完全沒有的東西，也是金流出錯代價最高之處。
- 前端要從「form-POST 轉跳」改成「Web SDK tokenize」，並牽動正在收緊中的 **CSP**。

---

## 2. 兩者本質差異（複雜度的真正來源）

| 面向 | NewebPay（現行） | 91APP Payments | 影響 |
|------|------------------|----------------|------|
| 前端付款流程 | 動態建 `<form>` POST 轉跳藍新 gateway 頁 | Web SDK 於 iframe tokenize (`txnToken`) → 後端 server-to-server 收單 | 前端 `submitNewebpayForm()` 整套報廢 |
| **續扣模型** | **gateway 託管委託**（`PeriodNo`，藍新自動扣～8 年並主動送 Notify） | **merchant-initiated**：商戶拿 `cardToken` 自行呼叫 `request-by-cardToken` 續扣 | ⚠️ 需自建排程器 + 失敗重試 |
| 簽章 | AES-CBC + SHA256（含藍新非標準 padding 特例、WAF UA 繞過） | HMAC-SHA256 (`N1-DATA-SIGNATURE`) + 選配冪等鍵 | adapter 整檔重寫，惟機制更標準 |
| 開通 | 對獨立服務友善 | **須簽約 + KYC + 固定出口 IP 白名單** | 見 §7 前置條件 |

**續扣責任歸屬（已與 91APP 文件對照確認為商戶自扣）**：
- 首期：`request-by-txnToken` + **`initCardTokenType=BindingCard`** + `merchantConsumerId` → 回可 MIT 續扣的 `cardToken`（**首筆仍需完成 3D**）。⚠️ **不是 `RememberCard`**——RememberCard 產生的是 `txnLastToken`（前端 `ccv.getTxnLastToken()`，續扣需使用者再輸 CVV，屬使用者在場，非 MIT，見 §7.1）。
- 續期：商戶自行呼叫 `request-by-cardToken`，帶 `cardToken` + `merchantConsumerId`（**須與綁卡時相同**），**且同時帶 `productType=Subscription` 與 `extensionInfo.subscriptionType=Renewal`** 才免 3D（MIT）（**兩參數缺一不可**）。
- **2026-07-24 Phase 0 sandbox 實測通過**：續扣回應 `statusCode=Success`、**`isThreeDomainSecure=false`**、`paymentUrl=""`——無人在場、無 CVV 成交。詳見 §12。
- **「何時扣、扣失敗怎麼辦、卡壞了怎麼辦」全由商戶負責。** 91APP 只提供「用 token 續扣的能力」，不提供排程（2026-07-24 已書面確認）。

---

## 3. 91APP API 速查（來源：官方文件）

**認證**：金鑰式（非 OAuth）
- `N1-API-KEY`（必填，簽約後取得）
- `N1-DATA-SIGNATURE`（必填）：`base64(lowercase_hex(HMAC-SHA256(payload, sharedSecret)))`。POST 以 JSON body 為輸入；GET 以 path+query（去掉 `?`）為輸入。`sharedSecret` = 申請回覆檔的 IV Key。⚠️ **簽章無 timestamp 參與**——防重放(replay)能力偏弱，我方 API 呼叫端須自行確保 HTTPS + 冪等鍵。
- `N1-IDEMPOTENCY-KEY`（選配，1 小時冪等；衝突回 HTTP 409）
- `N1-CONNECT-STORE`（推廣商 Agency 模式指定商店）
- **IP 白名單為強制前置**

**Base URL**：正式 `https://api.payments.91app.com`；開發 `https://api.developer.payments.91app.com`

**核心 endpoints**：

| 功能 | Method | Path |
|---|---|---|
| 建立交易(txnToken) | POST | `/v2/payments/request-by-txnToken` |
| 建立交易(cardToken，續扣用) | POST | `/v2/payments/request-by-cardToken` |
| 查詢交易 | GET | `/v2/trades/{tradeId}` |
| 取消交易 | POST | `/v2/trades/{tradeId}/cancel` |
| 請款 | POST | `/v2/trades/{tradeId}/capture` |
| 退款 | POST | `/v2/trades/{tradeId}/refund` |
| 收款連結 | POST | `/v2/pay-pages/url` |
| 綁卡 CRUD | POST/GET/DELETE | `/v2/payments/payment-methods` |

**付款方式**：CreditCard(含 3D/分期/綁卡)、ApplePay、GooglePay、ATM、CVS、LINE Pay、OPPayLater、StoredValue。

---

## 4. 本 repo 金流耦合地圖

### 4.1 可保留（provider-agnostic）— 過去重構的回報

| 資產 | 說明 |
|---|---|
| `OrderSettlement.settle()` 狀態機 | 啟用/續期/降 free/加值/拒重複 的核心邏輯，透過 `PaymentNotification` dataclass 這個乾淨 seam 與協定解耦。**最高價值資產。** |
| `ProcessedWebhookRepository` | 冪等機制，`_id = provider:natural_id`、`payment_provider` 欄位已泛化 |
| `order_repo` / `user_repo` | 訂單生命週期、subscription/quota/usage/extra_quota 寫入 |
| `admin_analytics.revenue()` | 已用注入 `price_of` 解耦 |
| 訂單契約欄位 | `type/status/tier/billing_cycle/amount_twd/extra_*` |
| `user.subscription.payment_provider` | 設計上已預留多 provider |

### 4.2 需重寫（NewebPay-specific）

| 項目 | 內容 |
|---|---|
| `src/utils/newebpay_service.py` **整檔** | → 新寫 `payments91_service.py`：HMAC 簽章、SDK 收單、退款、續扣、`request-by-cardToken` |
| `src/routers/subscriptions.py` Notify/Return 端點 | `notify/period`、`notify/mpg`、`return` → 改吃 91APP callback 格式（`tradeId`/`recordStatus`/`merchantOrderId`），重寫 `is_first_payment` 判定 |
| 降級期末生效機制 | 現靠藍新特有 `PeriodType=D`+`PeriodStartType=3`+`PeriodFirstdate` 模擬期末首扣；91APP 無此招，改用自建排程觸發 |
| 資料欄位對應 | `period_no` / `newebpay_trade_no` / `auth_times` / `prev_period_no` → 對應 91APP `cardToken` / `tradeId`（建議收進 `subscription.provider_ref` 子物件並做 migration） |
| 前端 | `frontend/src/stores/auth.js:submitNewebpayForm()`、`CheckoutView.vue`、`PaymentReturnView.vue` 全面重寫接 SDK |
| 設定 | `NEWEBPAY_*` env/SSM 參數整組替換 |

### 4.3 建議先做的解耦（即使不換也值得）

- 在 `OrderSettlement` 前抽一層 `PaymentProvider` interface（`create_subscription` / `terminate` / `refund` / `get_price` / `calc_period_end` / `decrypt_notify → PaymentNotification`），把 router 對 `get_newebpay_service()` 的直接依賴改為注入。目前 seam 已接近，缺正式 interface。做完換 provider 就是「實作新 adapter + 前端 + 排程」，不必動狀態機。
- 消除前後端定價雙寫（`frontend/src/constants/pricing.js` vs 後端 `NEWEBPAY_PRICE_*`），改單一來源。

---

## 5. 續扣自建：這是本次遷移的主軸工程

商戶自扣確認後，工作重心從「adapter 重寫」轉為「替訂閱計費從零建一套續扣基礎設施」：

1. **續扣排程器**：專案目前無付款排程基礎設施（`gpu-starter` Lambda 是喚醒 GPU 用，不可直接套）。選項：EventBridge + Lambda / cron / 常駐 worker。**排程本身的冪等**必須設計好（與現有 `processed_webhooks` webhook 冪等是兩回事——這是「主動觸發」端的防重複扣款）。
2. **Dunning（催收）策略**：扣失敗重試幾次、間隔、寬限期(grace period)、幾天後降 free。依 error code 分流（見 §6）。
3. **年繳處理**：藍新年繳是「一次性、不自動續」；91APP 自扣下年繳＝「排一年後扣一次」，續訂邏輯與月繳統一，需重想 UX（要不要自動續年？）。
4. **卡片到期主動提醒**：自扣下需在卡到期前 email 提醒換卡，否則靜默流失。新功能。
5. **🔒 `cardToken` 儲存安全規範**：token 等同支付憑證。加密儲存、存取控制、放哪個 collection、誰能讀——動到 payment 資料，走 `.claude/docs/judgment-rubrics.md` §5 高風險驗收。**切勿明文存、切勿寫入 log。**

**cardToken 生命週期——已確認的事實（2026-07-19 文件驗證 + 2026-07-24 91APP 窗口確認）**：
- 首期 3D 未過 → cardToken **無效**（spec 逐字：「若該次 request-by-txnToken 交易結果為失敗，則對應的 cardToken 會亦無效」；3D 失敗＝交易失敗，測試卡 statusCode=`Failured3DS`）。→ 首期 checkout **必須完成 3D** 才拿得到可續扣 token。
- **cardToken 本身無效期、無「閒置 N 天失效」規則**，可長期保存使用（2026-07-24 91APP 確認）。→ **免做 token 定期展延排程**；先前公開文件的 `CardTokenExpired` 錯誤碼對應的是實體卡到期/失效，非 token 自身 TTL。
- **實體卡到期或掛失** → 原 cardToken **可能無法再授權，需重新綁卡**；更新到期日視為**新卡**並回傳**新的 cardToken**（2026-07-24 91APP 確認）。
- **無換卡/更新 API**：payment-methods 僅綁/查/刪；「刪除後可重新綁定」。換卡＝使用者重新輸卡完成一次新首期交易 → 取得新 cardToken → 更新訂閱綁定。
- **續扣也可能被要求 3D**：`request-by-cardToken` 的 response schema 含 `paymentUrl`（3D 驗證網址）；偵測方式為 `statusCode=Success` 且 `paymentUrl` 非空（無專用碼）。無人值守排程遇到時的處理（暫停訂閱→email 請使用者完成驗證？）需納入 dunning 設計。

---

## 6. 錯誤處理 / Dunning（來源：error-handling 文件）

錯誤分兩層：**系統層 HTTP status**（400 參數/通訊、409 冪等衝突、500 內部）＋ **商業層 statusCode**（HTTP 200 但商業失敗）。

| 分類 | 錯誤碼（節錄） | dunning 動作 |
|---|---|---|
| 可重試（銀行暫時性） | `RefusedTrade`、`BankError`、`NeedContactBank`、`ThirdPartyHttpTimeout`(500)、`IdempotentConflict`(409) | 退避重試 |
| 不可重試（換卡/資料） | `CardExpired`、`CardNumberWrong` | 觸發換卡通知 |
| 不可重試（風控） | `CreditCardBlacklist`、`IPBlacklist` | 停止、轉商務處理 |

**商業層 statusCode 全表（2026-07-19 自 spec 逐字確認）**：
`RefuseTrade / UnknownThirdPartyCode / UnexpectedError / InstallmentsNotSupport / NeedContactBank / BankError / CardNumberWrong / InternalError / CardExpired / InstallmentsDataError / Unavailable`

**缺口（需向 91APP 確認）**：
- **全表無「消費者卡額度不足」專屬碼**——額度不足最可能落在 `RefuseTrade`（「銀行拒絕交易 (Decline)」）但文件未言明；這是續扣最常見失敗原因，dunning 分流精度取決於此，待 91APP 回覆。（注意混淆項：`BalanceInsufficient`/`VirtualAccountReserveFailed`/`RefundableBalanceNotEnough` 皆為**商店側**帳務/退款配額，非消費者卡。）
- 3DS 失敗的具體 statusCode（使用者拒絕/逾時）未詳列（僅測試卡示例 `Failured3DS`）。
- **無官方重試決策表**——retryable/non-retryable 分流需商戶自定並與 91APP 對碼。

### 6.1 Callback 驗證缺口（🔒 資安重點，2026-07-19 發現）

OpenAPI spec 的 callback 端點定義 `security: []`、**無任何 header 參數、payload 無簽章欄位**——即文件層面 **callback 沒有驗簽機制**（與商戶→91APP 方向的 `N1-DATA-SIGNATURE` 不同，那是單向的）。payload 僅 7 欄：`tradeId`\*、`recordStatus`\*、`merchantOrderId`\*、`storeCode`\*、`storedValueToken`、`bindingToken`、`bindingStatus`，**無 eventId／timestamp／序號**。

**我方 webhook 端點設計原則（無論 91APP 回覆為何都適用）**：
1. **不信任 callback payload**：收到通知後一律回查 `GET /v2/trades/{tradeId}`（此請求有我方簽章保護），以查詢結果為準才寫入 `OrderSettlement`。
2. **來源 IP 白名單**：91APP callback IP（簽約後提供）進 nginx/WAF allowlist。
3. **自建冪等**：payload 無 eventId，以 `(tradeId, recordStatus)` 為 natural_id 進 `processed_webhooks`（沿用現有 `provider:natural_id` 機制）。官方已明示同一 `tradeId` 會因 `recordStatus` 演進收到多次通知（如 OPPayLater 審核 8→4/2）。
4. callback 重試次數/間隔文件全無，**不可依賴重送**——需自建對帳補償（定時掃 pending order 主動查 `GET /v2/trades/{tradeId}` 收斂，類似現有孤兒委託收斂）。

---

## 7. 前端 SDK 與 CSP 衝擊（來源：frontend-sdk 文件 ＋ 本 repo 現況）

### 7.1 SDK 整合
- 載入：**僅 CDN**（文件未提 npm/bundler），`<script src="https://checkout.payments.91app.com/sdk/3.9.3/index.js" integrity="sha256-…" crossorigin>`（**有 SRI**）。
- 初始化：`Payments91APP.setupSDK(publishableKey, serverType)`，`serverType='sandbox'|'production'`。
- 信用卡：需 DOM 容器 `#card-number` / `#card-expiration-date` / `#card-ccv`，`card.setup(config)` → `card.on('update', …)` 監聽 `canGetToken` → `await card.getTxnToken()`。
- ApplePay / GooglePay / ATM / CVS / LINE Pay 各自 `create` / `getTxnToken`。
- 「記住卡號」前端流程是 `ccv.getTxnLastToken()`——**仍需使用者本人輸入 CVV**，屬「使用者在場的重複付款」，**非**無人值守 MIT。

### 7.2 CSP 改動（本 repo 現況 `deploy/nginx-ec2.conf`，app server context）

現行（藍新）：
```
frame-src   'self' https://accounts.google.com https://*.newebpay.com
form-action 'self' https://accounts.google.com https://*.newebpay.com https://core.newebpay.com
script-src  (無金流網域)
```

改成 91APP 需：

| directive | 動作 |
|---|---|
| `script-src` | ＋ `https://checkout.payments.91app.com`（用 Apple/Google Pay 再加 `applepay.cdn-apple.com`、`pay.google.com`） |
| `frame-src` | 把 `https://*.newebpay.com` 換成 `https://pay-panel.payments.91app.com`（sandbox：`pay-panel.developer.payments.91app.com`） |
| `connect-src` | ＋ 91APP 網域（＋ Google Pay `pay.google.com`） |
| `form-action` | 移除藍新網域（不再有 form-POST 轉跳） |

**范式差異**：藍新開放面在 `form-action`（表單送 gateway）；91APP 開放面在 `script-src`+`frame-src`（載 SDK、iframe 收卡）。

### 7.3 對 CSP 收緊工作的影響
- ✅ 加的是**具名 origin**，非 `unsafe-*`，不倒退既有收緊（app server 現為 `unsafe-eval`(vue-i18n 需要) + sha256，已無 `unsafe-inline`）。
- ✅ 官方提供 **SRI**，符合專案 SRI 紀律。
- ✅ **SDK 不需 `unsafe-eval`（2026-07-19 實測確認）**：直接下載 `checkout.payments.91app.com/sdk/3.9.3/index.js`（46,749 bytes，SHA-256 與官方 SRI hash 完全相符），靜態掃描 `eval(` / `new Function` / `document.write` 皆 **0 次**；且官方建議 CSP 本身即不含任何 `unsafe-*`。上線前仍應在 sandbox 以真實頁面走一次完整付款流程做動態驗證（含 3D 導頁、`pay-panel` iframe），但靜態層面已排除風險。

---

## 8. 存量訂閱遷移（最大營運坑）

藍新續扣「委託 (`PeriodNo`)」綁在**藍新端**，**無法搬到 91APP**（91APP 沒有使用者的卡）。現有付費用戶只有兩條路：

- **(A) 讓其跑到當期到期**，到期時引導在 91APP 重新綁卡續訂（有斷點、可能流失）
- **(B) 主動請所有付費用戶重新綁卡**（體驗差、轉換有損）

無論哪條，遷移期會**同時運行兩套金流**（藍新續舊約、91APP 收新約），`payment_provider` 欄位需並存（schema 已預留）。此共存期複雜度須提早規劃。

---

## 8.5 商業條件（2026-07-19 取得之 91APP 報價，未稅）

收款額度：**100 萬/月**（超過時的處理方式待確認）

| 項目 | 專案價格 | 單位 | 說明 | 撥款天期 |
|---|---|---|---|---|
| 系統設定費 | 5,880 | 單次 | | |
| 年費 | 專案免收 | 每年 | 原價 13,000 | |
| 信用卡一次（國內） | 2.35% | | | D+7 |
| 信用卡一次（國外） | 3.35% | | | |
| Apple/Google Pay | 2.35% | | | |
| LINE Pay | 2.65% | | LINE 審核/撥款 | |
| ATM | 0.9% | 上限 20 元 | | D+7 |
| 超商代碼 | 27 | 筆 | | D+15 |
| **訂閱制** | **本次免收** | 單次 | **原 30,000**；信卡/行動支付 | |
| **Token 處理費** | **本次免收** | 筆 | 原 1.5 元 | |
| **卡號到期自動更新** | **本次免收** | 筆 | 原 8,000 | |

**報價單透露的重要訊號**：
- **「訂閱制」「Token 處理費」「卡號到期自動更新」三項目的存在** = 91APP 有正式的訂閱/token 產品線，非僅「裸 token 續扣」。Tier 0 待確認問題從「有沒有」聚焦為「訂閱制項目包含什麼（是否含排程/免 3DS 授權設定）」。
- **「卡號到期自動更新」= Account Updater 服務**——直接緩解 cardToken 生命週期的最大風險（實體卡到期 ≠ 續扣必斷）。其作用機制（自動更新 cardToken？涵蓋哪些發卡行？）待確認。
- **撥款天期已知**：信用卡/ATM D+7、超商 D+15（原待確認項 E-13 部分解決）。

**⚠️ 合約審閱注意**：
1. 所有「本次免收／專案免收」為**促銷條件**——合約須白紙黑字寫明適用期間與恢復條件（年費原價 13,000、訂閱制 30,000、Token 費 1.5/筆、卡號更新 8,000）。尤其 Token 處理費按「筆」計，恢復原價後為續扣的邊際成本。
2. **收款額度 100 萬/月**：確認超過時的行為（暫停收款？自動升級？需提前多久申請調升？）。
3. 「卡號到期自動更新」計價單位標示「筆」但原價 8,000 元，單位語意不明（單次設定費？年費？）——簽約時釐清。
4. 費率 ROI 比較：需以藍新現行合約費率為基準自行比對（本文件不記藍新費率）。

## 9. 前置條件（開通門檻）

- 須與 91APP Payments **簽約申請** → 取得 API Key + `sharedSecret` + 設定 IP 白名單，屬 gated onboarding（KYC/PCI DSS），非自助即用。
- **固定出口 IP 白名單**：⚠️ 本 repo 記錄 prod web EC2 目前**非 EIP**（見 memory `project_prod_findings`）。串 91APP 前，該台 egress 須先綁固定 IP（EIP 或 NAT），否則簽約條件過不了。
- 窗口：`service.payments@91app.com`；訂閱/排程細節導向 `upd.upd9@91app.com`。
- 時程建議：**先跑商務簽約流程**（可能比開發久），再排開發。

---

## 10. 工作量粗估

| 區塊 | 相對工作量 | 備註 |
|---|---|---|
| `PaymentProvider` interface 抽取 | 小 | 即使不換也值得做 |
| 91APP adapter（簽章/收單/退款） | 中 | 機制標準，好寫 |
| 前端 SDK 整合 | 中 | 非改參數，是重寫 |
| **續扣排程器 + dunning（新基礎設施）** | **大（風險最高）** | 本次主軸 |
| Notify/Return 端點 + 降級排程重設計 | 中 | |
| 資料欄位 migration | 小～中 | |
| 存量用戶遷移（雙金流共存） | 中～大 | 營運複雜度 |
| **電子發票自接 ezPay** | 中 | 2026-07-24 確認 91APP 不開發票 → 須自接 ezPay（藍新集團）：開立/作廢/折讓 API + 財政部上傳；退款須連動開立折讓單 |

**已定案（2026-07-24 91APP 確認純商戶自扣、無 gateway 端排程）→ 續扣排程器為獨立子專案，整體工作量＝「高」。**

---

## 11. 建議路徑

1. ~~**Step 0（零程式碼）**：寄 `PAYMENT_91APP_VENDOR_QUESTIONS.md` 鎖死兩題 🔴~~ → ✅ **2026-07-24 完成**：續扣可免 3D、cardToken 無自身效期、商戶自扣確認，**go/no-go 通過**。剩餘為商務條款（報價「訂閱制/Account Updater」內容、免收恢復條件、100 萬額度）與對接細節（A-2 何時仍需 3D、callback SLA），可於簽約談判與 sandbox 對接時解決，不阻擋啟動。
2. **Step 1**：抽 `PaymentProvider` interface（降風險，解耦既有藍新）。
3. **Step 2**：`Payments91Service` + 前端 SDK + 續扣排程器，在 sandbox 跑通首期/續期/退款/降級/CSP。
4. **Step 3（optional）**：消除前後端定價雙寫。

---

## 12. Phase 0 Sandbox 實測結果（2026-07-24，一手資料）

用 sandbox key 實跑「簽章 → BindingCard 綁卡+3D → MIT 免 3D 續扣」全鏈路,三關全綠。以下為**實測**的欄位形狀（優於文件推測,adapter 直接照這個寫）。

**簽章（實證正確）**：`N1-DATA-SIGNATURE = base64(lowercase_hex(HMAC-SHA256(payload, sharedSecret)))`,HMAC key = sharedSecret **原字串**（非 base64 解碼）。POST 簽 JSON body 原字串,GET 簽 `path+query`（去 `?`,不含 host）。

**request-by-txnToken（首期綁卡）body**：
```jsonc
{
  "txnToken": "<SDK card.getTxnToken()>",
  "initCardTokenType": "BindingCard",          // ★ 非 RememberCard
  "merchantConsumerId": "<商店會員ID>",         // ★ BindingCard 必填,續扣要用同一個
  "merchantOrderId": "<訂單號,≤50字>",
  "paymentMethods": [{"payType": "CreditCard", "amount": 100}],  // amount 在此,單位=元
  "productType": "Subscription",
  "extensionInfo": {
    "subscriptionType": "First",
    // ⚠️ 正式環境必填、sandbox 不驗（2026-09-01 go-live 首筆實測 400
    //   SubscriptionProductInfoRequired 才炸出）。priceName(≤100)/amount 必填；
    //   recurring.type=Day|Week|Month|Year、interval、periods(未帶=無限期) 選填。
    "subscriptionProductInfo": {
      "priceName": "...", "amount": 100,
      "recurring": {"type": "Month", "interval": 1}
    }
  },
  "currency": "TWD",
  "products": [{"name": "...", "totalAmount": 100, "productType": "Subscription"}],
  "cardHolder": {"name": "...", "phoneNumber": "+886...", "email": "..."},
  "redirectUrl": "https://.../ (3D 後導回,https)",   // ★ 欄位名 redirectUrl(非 returnUrl)
  "callbackUrl": "https://.../callback (S2S 通知,https)"
}
```

**request-by-cardToken（MIT 續扣）body**：同上,但 `txnToken`→`cardToken`,`subscriptionType`:`First`→`Renewal`,去掉 `initCardTokenType`。`merchantConsumerId` 須與綁卡相同。僅支援 `CreditCard`、`currency` 固定 `TWD`。

**續扣成功 response 關鍵欄位（實測）**：
```jsonc
{
  "statusCode": "Success",
  "tradeId": "PT0260724700004T",
  "isThreeDomainSecure": false,   // ★ 免 3D 的硬證據
  "paymentUrl": "",               // 空 = 無 3D 導頁
  "authCode": "123456",
  "amount": 100,
  "cardInfo": { "cardBrand": "VISA", "lastFour": "8452", "cardCode": "<HMAC>" },
  "expiryTime": 1784875910998,
  "transactionTime": 1784874110998
}
```

**踩雷紀錄（欄位名/結構,實作避坑）**：
- `amount` 在 `paymentMethods[]` 內,**非頂層**（頂層帶 amount → InternalServerError）。
- 導回欄位是 `redirectUrl`（寫 `returnUrl` → `RedirectUrlRequired`）。
- 訂閱首期用 `BindingCard`+`merchantConsumerId`;`RememberCard` 是「使用者在場+CVV」的 txnLastToken 流程,不可用於無人值守續扣。
- Web SDK `card.setup()` 的 fields key 為 `number`/`expirationDate`/`ccv`,屬性 `element`（非 `selector`）。
- 測試卡:成功 `4503 0749 6961 8452`、`Failured3DS` `4800 8957 3345 1295`、`RefuseTrade` `4720 8940 9183 3605`、`cardExpired` `5442 2801 8461 3035`（期限一律 12/34、CVV 任意）。

**尚未在 spike 驗的**（Phase 2 sandbox 補）：退款/請款/取消、callback 實際 payload 與重試、`Failured3DS`/`RefuseTrade` 的完整 dunning 分流、A-2（哪些情境續扣仍被要求 3D）。

## 待確認清單現況（2026-07-19 文件窮舉驗證後）

| 項目 | 狀態 |
|---|---|
| dunning 錯誤碼語意 | ✅ statusCode 全表已確認（缺「卡額度不足」專屬碼，見 §6） |
| CSP / 前端 SDK 整合方式 | ✅ 已釐清（含具體 directive 改動） |
| SDK 本身是否需 unsafe-eval/inline | ✅ **實測不需**（SDK 3.9.3 靜態掃描 0 命中，hash 符 SRI） |
| 首期 3D 未過 → cardToken 無效 | ✅ 文件明載（首期必須完成 3D） |
| 換卡 API | ✅ 確認不存在（刪除+重綁；換卡＝新首期交易換新 token） |
| 請款模式(auto-capture?) | ✅ 商店層級設定（自動/手動皆有；部分請款為申請制） |
| 部分退款 | ✅ 已請款可部分退；未請款/分期僅全退 |
| 對帳/結算報表 API | ✅ 確認不存在（ledgers 為推廣商資金劃撥） |
| callback 有無簽章 | ⚠️ spec 顯示**無**——已定防禦設計（§6.1），待 91APP 確認 |
| 續扣免 3DS (MIT) | ✅ **2026-07-24 91APP 確認可免 3D**：`request-by-cardToken` 須同時帶 `productType=Subscription` + `subscriptionType=Renewal`；首筆綁卡仍需 3D |
| cardToken 效期長度 / 實體卡到期影響 | ✅ **2026-07-24 91APP 確認**：token 本身無效期、無閒置失效，可長期保存；實體卡到期/掛失須重新綁卡並取回新 token |
| 續扣排程責任 | ✅ **2026-07-24 91APP 確認**：商戶主動觸發，無 gateway 端排程 → 自建排程器必做（工作量高） |
| 消費者電子發票 | ✅ **2026-07-24 確認**：91APP 不提供 → 須自接 ezPay（藍新集團），為新增工作項（見 §10） |
| 消費者卡額度不足 statusCode | ⚠️ 待問（研判 `RefuseTrade` 但未言明） |
| callback 重試 SLA | ⚠️ 待問（文件全無；已定「不依賴重送、自建對帳補償」原則） |
| **費率 / 撥款週期** | ✅ **已取得報價（2026-07-19，見 §8.5）**：信用卡 2.35% D+7、超商 D+15 等 |
| 實體卡到期 → token 命運 | 🟡 **報價含「卡號到期自動更新」(Account Updater) 服務**——風險大幅緩解，作用機制待確認 |
| 「訂閱制」項目包含內容 | ⚠️ 新增待問：報價的「訂閱制」（原 3 萬）具體開通什麼？是否含排程/MIT 授權設定？ |
| 退款到帳天數 | ⚠️ 待問（客服話術用） |
| IP 白名單數量/CIDR、sandbox 申請時程 | ⚠️ 待問 |
| 收款額度 100 萬/月超額行為 | ⚠️ 簽約時釐清 |
| 固定出口 IP（prod 非 EIP） | ⚠️ 部署前置，待處理 |

> 驗證方法備註：頁面清單經 Docusaurus runtime chunk 解析窮舉（確認指南區無 callback/退款/綁卡/訂閱獨立專頁——該等主題僅散見 introduction/faq/error-handling 與 API spec）；OpenAPI spec（v2.0.0, 234KB）自 webpack chunk 還原後逐欄位檢查；SDK 為實檔下載掃描。
