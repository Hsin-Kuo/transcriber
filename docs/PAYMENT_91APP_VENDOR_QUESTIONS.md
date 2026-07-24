# 91APP Payments 技術確認信（草稿）

> 用途：串接 91APP Payments 前，向對方技術/商務窗口書面確認的問題清單。
> 收件建議：`service.payments@91app.com`（商務/申請）、`upd.upd9@91app.com`（訂閱/排程細節）。
> 標 🔴 的兩組為「生死題」——答案會決定本專案訂閱制是否可行，請優先回覆。
>
> **2026-07-19 已對 91APP 公開文件做窮舉驗證**（全站導覽頁 + OpenAPI spec 逐欄位 + SDK 實檔掃描），
> 確認以下每一題公開文件均無答案或僅有部分答案。已有答案的題目已移除，紀錄見文末「已從公開文件確認」。
>
> **🟢 2026-07-24 生死題已由 91APP 窗口書面確認**：A-1（續扣免 3D）、B-3/B-4/B-5（cardToken 生命週期）、C-6（排程責任）皆有答覆——**核心 go/no-go 閘門通過**（續扣可免 3D）。詳見文末「已由 91APP 窗口確認」。以下 A/B/C 題組保留作對接時追問細節用。

---

## 問題分層（決策視角，2026-07-19；同日已取得報價單，見評估文件 §8.5）

**🟢 Tier 0 生死題（2026-07-24 已確認，go/no-go 通過）**：A-1 續扣免 3D ✅、B-3 cardToken 效期 ✅、B-4/B-5 卡到期/失效 ✅、C-6 排程責任 ✅——見文末「已由 91APP 窗口確認」。**剩餘 Tier 0**：A-2（哪些情境續扣仍被要求 3D）、報價衍生兩題（**「訂閱制」項目（原 3 萬）包含什麼**、**「卡號到期自動更新」(Account Updater) 作用機制**）仍待釐清，但已非否決級。
~~F-17 費率~~ → ✅ 已取得報價（信用卡 2.35% D+7、超商 D+15、訂閱制/Token 費/卡號更新本次免收；詳見評估文件 §8.5）。

**🟡 Tier 1 — 簽約談判自然涵蓋**：E-13（結算明細取得方式——撥款天期已知 D+7/D+15）、E-14（請款模式設定）、F-15（IP 白名單細節）、收款額度 100 萬/月超額行為、各「免收」項目的適用期間與恢復條件（**務必入約**）。

**🟢 Tier 2 — 簽約後技術對接再問**：B-4、B-5（卡到期/主動失效——**報價含「卡號到期自動更新」服務，風險已大幅緩解**，細節歸入 Tier 0 衍生題確認）、C-7、C-8（dunning 分流精度）、D-9～D-11（callback——已有不依賴對方答案的防禦設計，見評估文件 §6.1）、E-12（退款到帳天數）、F-16（sandbox 時程）。

**簽約前需自行接受的確定成本（不用問 91APP）**：(1) 自建續扣排程器 + dunning 必然要做（除非「訂閱制」項目意外含排程——Tier 0 衍生題確認）；(2) 存量付費用戶無法搬移，須重新綁卡、過渡期雙金流並行。決策公式＝91APP 的效益（費率已知，可與藍新現約比對 ROI）是否值得這兩項確定成本。

---

## 簽約前短信（Tier 0，可直接複製寄出）

主旨：91APP Payments 導入評估——簽約前關鍵確認（訂閱制自動續扣）

您好，

我們是 SoundLite（語音轉文字訂閱服務），現行金流為藍新 NewebPay，正評估遷移至 91APP Payments，感謝先前提供的報價。核心情境是**訂閱制自動續扣（月繳／年繳）**。已詳讀貴司開發者文件，以下五點是我們**評估是否簽約的前提**，煩請優先回覆：

1. **續扣是否免 3D 驗證**：以 `request-by-cardToken`（`subscriptionType=Renewal`）進行商戶主動觸發、無使用者在場的續扣時，是否以 MIT（Merchant-Initiated Transaction）形式送發卡行、免除 3D Secure？什麼情境下續扣仍會被要求 3D（response 回 `paymentUrl`）？
2. **cardToken 效期**：效期多長？從何時起算？成功續扣後是否展延？（我們已知會過期——`CardTokenExpired`。）
3. **續扣排程責任**：續扣排程完全由商戶自行觸發，91APP 不提供 gateway 端自動扣款排程——此理解正確嗎？
4. **報價「訂閱制」項目內容**：貴司報價中的「訂閱制」（原價 30,000，本次免收）具體開通哪些能力？是否包含續扣排程、或 MIT／授權方式的商店端設定？
5. **「卡號到期自動更新」機制**：此服務（原價 8,000，本次免收）的作用方式為何——持卡人卡片到期換卡後，既有 `cardToken` 會自動對應新卡繼續續扣嗎？涵蓋哪些發卡行？計價單位「筆」的定義？

若第 1 點無法支援免 3D 的自動續扣，我們的訂閱模式即不可行，故懇請先行確認。感謝協助。

SoundLite 技術團隊 敬上

---

## 完整技術確認信（簽約後對接用，含全部 17 題）

主旨：91APP Payments 串接技術確認（訂閱制自動續扣情境）

您好，

我們是 SoundLite（語音轉文字訂閱服務），現行金流為藍新 NewebPay，正評估遷移至 91APP Payments。我們的核心情境是**訂閱制自動續扣（月繳／年繳）**，已詳讀貴司開發者文件（introduction / API spec / error-handling / FAQ / Web SDK），以下為文件未涵蓋、需向貴司確認的技術細節。標記 🔴 的兩組對我們最關鍵，煩請優先回覆。

### 🔴 A. 續扣與 3D 驗證（最優先）

1. 以 `request-by-cardToken`（`extensionInfo.subscriptionType=Renewal`）進行**商戶主動觸發、無使用者在場**的續扣時，是否**免除 3D Secure 驗證**（即以 MIT, Merchant-Initiated Transaction 形式送發卡行）？我們注意到 request body 並無 3D 授權方式的指定欄位，而錯誤碼中有「該商品類型不支援指定授權方式」——「指定授權方式」是否為可申請開通的商店設定？
2. 我們已知 `request-by-cardToken` 的 response 也可能回 `paymentUrl`（3D 驗證連結）。請問**什麼情境下續扣會被要求 3D**（風控？發卡行？金額門檻？）？無使用者在場的排程扣款遇到此情況，官方建議的處理方式為何？

### 🔴 B. cardToken 生命週期（最優先）

3. 文件錯誤碼顯示 cardToken 會到期（`CardTokenExpired`）。請問**效期多長？從何時起算？成功續扣後是否展延**？
4. **持卡人信用卡本身到期（expiry date 過期）後，原 `cardToken` 是否隨之失效**，還是仍可能續扣成功（如發卡行支援卡號自動更新）？
5. 91APP 是否會**主動失效** `cardToken`（卡片掛失、風控、發卡行更新）？失效時**有無主動通知機制**，還是商戶只能在下次扣款失敗時發現？

### C. 續扣排程與失敗處理

6. 續扣的**排程觸發完全由商戶負責**，91APP 不提供任何 gateway 端自動扣款排程，對嗎？（我方由 API 清單研判如此，請書面確認。）
7. 續扣時**消費者卡片額度不足**，回傳的 statusCode 為何？（文件 Status Code 清單未見額度相關碼——是否落在 `RefuseTrade`？能否與其他 decline 原因區分，以利我方催收策略分流？）
8. 是否有官方建議的**重試策略**（retryable vs non-retryable statusCode 對照、建議重試間隔與次數）？

### D. Callback（交易結果通知）

9. callback 的**重試機制**為何？重試次數、間隔、退避策略？商戶回應非 2xx 時會重送嗎？多久後放棄？
10. callback 請求是否附帶**簽章或驗證用 header**？（API spec 的 callback 定義未見任何 header 或簽章欄位。）若無簽章，官方建議的驗證方式是否為「來源 IP 白名單 + 收到通知後回查 `GET /v2/trades/{tradeId}`」？
11. 同一筆 `(tradeId, recordStatus)` 組合的通知**是否可能重複投遞**？（payload 無 eventId／序號，我方需自建冪等去重。）

### E. 請款 / 退款 / 帳務

12. 退款後**消費者實際到帳天數**約多久（信用卡刷退／其他支付方式）？
13. 一般商店（非推廣商）**如何取得結算／撥款明細**？撥款週期為何？（我方確認公開 API 無對帳報表端點。）
14. 我們商店開通時會被設定為**自動請款還是手動請款**？若需**部分請款**（文件註明為申請制），申請條件為何？

### F. 開通前置

15. **固定出口 IP 白名單**：我方 API 呼叫來源 IP 可提供幾個？是否支援 CIDR 網段？（我們部署於 AWS，需確認 EIP／NAT 固定出口的規劃。）
16. sandbox（開發者環境）的**申請流程與作業時間**？是否隨簽約一併提供 sandbox 用 API Key／publishableKey？
17. ~~費率／手續費結構~~ → ✅ 2026-07-19 已取得報價單（見 `PAYMENT_91APP_MIGRATION_ASSESSMENT.md` §8.5），本題移除。

以上，感謝協助。期待回覆。

SoundLite 技術團隊 敬上

---

## 已從公開文件確認、不需詢問的事項（2026-07-19 驗證）

驗證方式：窮舉全站導覽頁（Docusaurus chunk 解析確認無漏頁）＋ 還原完整 OpenAPI spec 逐欄位檢查 ＋ 直接下載 SDK 實檔掃描。

| 事項 | 答案 | 依據 |
|---|---|---|
| 首期 3D 未過，cardToken 可用嗎 | **否**——「若該次 request-by-txnToken 交易結果為失敗，則對應的 cardToken 會亦無效」；3D 失敗＝交易失敗（測試卡 statusCode=`Failured3DS`） | API spec `PayByCardTokenRequestEntity.cardToken` |
| 換卡／更新卡片 API | **無 update API**。payment-methods 僅綁/查/刪 4 支；「刪除後可重新綁定」為唯一路徑 | API spec payment-methods operations |
| 續扣被要求 3D 的**偵測方式** | 無專用碼：`statusCode=Success` 且 `paymentUrl` 附 3D 連結 | FAQ |
| auto-capture？ | **商店層級設定**：自動請款則免呼叫 `/capture`；手動則需呼叫。僅支援全額請款（部分請款為申請制 `captureAmount`）；建議授權後 5 天內請款、當日截止 17:29:59 | API spec `/capture` description |
| 部分退款 | **已請款可部分退**；未請款交易、分期付款僅全額退；同日請退款自動延一天送銀行；單日退款筆數有上限 | API spec `/refund` + error codes |
| 對帳報表 API | **不存在**。ledgers 五支全為推廣商（`N1-Agency-API-KEY`）資金劃撥用，非商店對帳 | API spec ledgers |
| Web SDK 是否需 `unsafe-eval` | **不需要**。SDK 3.9.3 實檔（hash 與官方 SRI 相符）掃描：`eval(`/`new Function` 皆 0 次；官方建議 CSP 亦不含 `unsafe-*` | SDK 實檔 + frontend-sdk 頁 |
| API 請求簽章演算法 | `N1-DATA-SIGNATURE` = `base64(lowercase_hex(HMAC-SHA256(payload, sharedSecret)))`；POST 以 JSON body、GET 以 path+query（去 `?`）為輸入；**無 timestamp 參與**（防重放偏弱，資安評估已記） | introduction 簽章範例（C#/PHP） |
| callback payload 欄位 | 僅 7 欄：`tradeId`\*、`recordStatus`\*、`merchantOrderId`\*、`storeCode`\*、`storedValueToken`、`bindingToken`、`bindingStatus`——**無 eventId／簽章欄位**；同一 tradeId 會因 recordStatus 演進收到多次通知 | API spec callback schema + introduction |

## 已由 91APP 窗口書面確認（2026-07-24）

| 題號 | 問題 | 91APP 回覆 | 對接影響 |
|---|---|---|---|
| **A-1** | 續扣是否可免 3D | **可**——`request-by-cardToken` 須**同時**帶 `productType=Subscription` **與** `extensionInfo.subscriptionType=Renewal`。**首筆綁卡（`BindingCard`）仍需 3D。** **✅ 2026-07-24 Phase 0 sandbox 實測通過**：續扣回 `isThreeDomainSecure=false`、`paymentUrl=""`。 | ⚠️ 實作關鍵：兩參數缺一不可；首期用 `BindingCard`+`merchantConsumerId`（非 RememberCard）。實測 body/response 見 ASSESSMENT §12。 |
| **B-3** | cardToken 效期 | cardToken **本身無效期、無「閒置 N 天失效」規則**，可長期保存使用。（先前公開文件的 `CardTokenExpired` 錯誤碼應對應實體卡到期/失效，非 token 自身 TTL。） | 免做 token 定期展延排程；但仍須處理下方 B-4 的卡到期斷點。 |
| **B-4/B-5** | 實體卡到期/掛失後 | 持卡人**實體卡到期或掛失**，原 cardToken **可能無法再授權，需重新綁卡**；更新到期日視為**新卡**並回傳**新的 cardToken**。 | 需做「扣款失敗 → email 請使用者重新綁卡 → 換發新 token → 更新訂閱綁定」的換卡 dunning 流程（無 update API，走刪+重綁）。 |
| **C-6** | 續扣排程責任 | 續扣採**商戶主動觸發**，由商店自行發動即可；**91APP 不提供 gateway 端自動扣款排程。** | ✅ 確認「自建續扣排程器 + dunning」為必做子專案，整體工作量＝**高**（見評估文件 §5、§10）。 |

**go/no-go 結論**：核心閘門（續扣可免 3D）通過，訂閱制自動續扣模式**成立**。剩餘為工程/商務細節，非否決級。

**其他已確認（2026-07-24）**：
- **消費者電子發票**：91APP **不提供**開立管道，須**自接 ezPay**（藍新集團電子發票產品）作為獨立整合。→ 金流離開藍新，但發票仍回藍新體系；ezPay 串接為本次遷移的**新增工作項**（開立/作廢/折讓 API + 財政部上傳）。

## 內部備註（不隨信寄出）

- A、B 兩組是 go/no-go 依據：若續扣不免 3DS 且無 MIT 機制，訂閱制自動扣款不成立 → 遷移應中止。
- C-6 我方已由 API 清單與 sequence diagram 研判為「商戶自扣」，本題求書面確認，作為自建續扣排程器的設計前提。
- D-10 是資安重點：spec 顯示 callback 無簽章定義。無論回覆為何，我方 webhook 端點設計採「不信任 payload，收到即回查 `GET /v2/trades/{tradeId}` 驗證」+ 來源 IP 白名單。
- F-15 對應 memory `project_prod_findings`：prod web EC2 目前非 EIP，需先處理固定出口 IP。
- 原第 19 題（SDK eval/CSP）已實測解決，不需問；上線前仍須在 sandbox 以真實頁面驗證 CSP（勿只信文件與本次靜態掃描）。
- 完整技術評估見 `PAYMENT_91APP_MIGRATION_ASSESSMENT.md`。
