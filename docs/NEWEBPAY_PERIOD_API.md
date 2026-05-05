# 藍新金流定期定額 API 技術參考

> 依據文件版本：信用卡定期定額串接技術手冊 NDNP-1.0.7（2026/03/16）

---

## 重要注意事項

1. **`PeriodStartType` 值意義與 MPG 完全不同**，容易搞錯：
   - `1` = 立即十元驗證（授權 NT$10 再取消，用於確認卡片有效性）
   - `2` = 立即首期授權（完整金額，這才是正式訂閱用的值）
   - `3` = 不立即授權，首扣日由 `PeriodFirstdate` 指定
   - **新訂閱請用 `2`，不是 `1`。**

2. **`PeriodFirstdate` 有嚴格限制**：
   - 只在 `PeriodType=D` 且 `PeriodStartType=3` 同時滿足時才有效
   - 月繳（`PeriodType=M`）和年繳（`PeriodType=Y`）**無法使用 PeriodFirstdate**
   - 要實作「指定首扣日」的排程功能，必須改用 `PeriodType=D`

3. **定期定額 Notify 是 AES 加密**，不是 MPG 的 SHA256 簽章格式：
   - Notify POST body 有 `Period` 欄位，內容是 AES-256-CBC 加密的 JSON
   - 解密方式與建立委託的 `PostData_` 相同（同一組 Key/IV）
   - 解密後結構：`{ "Status": "SUCCESS", "Message": "...", "Result": {...} }`

4. **初次 Notify（建立完成）vs 每期 Notify（NPA-N050）的欄位不同**：
   - 建立完成：`Result.AuthTimes` = 合約總期數（非已完成次數）
   - 每期授權：`Result.AlreadyTimes` = 已完成期數（含失敗），`Result.TotalTimes` = 總期數
   - 用 `AlreadyTimes` 是否存在區分兩種 Notify

5. **修改委託狀態 API 的正確端點**：
   - URL：`/MPG/period/AlterStatus`（不是 `/MPG/period/doaction`）
   - 參數：`AlterType`（不是 `ActionType`），Version 固定 `1.0`
   - 表單欄位：`MerchantID_`（有底線）和 `PostData_`

6. **定期定額表單欄位名稱與 MPG 不同**：

   | 定期定額（/MPG/period） | MPG（/MPG/mpg_gateway） |
   |---|---|
   | `MerchantID_`（有底線） | `MerchantID` |
   | `PostData_` | `TradeInfo` + `TradeSha` + `TimeStamp` |
   | 訂單號：`MerOrderNo` | 訂單號：`MerchantOrderNo` |
   | 商品名稱：`ProdDesc` | 商品名稱：`ItemDesc` |
   | Email：`PayerEmail` | Email：`Email` |
   | 金額：`PeriodAmt`（無 `Amt`） | 金額：`Amt` |

7. **`PeriodPoint` for 月繳可用 01～31**：
   - 藍新在當月無此日期時自動以該月最後一天扣款（不需要手動 cap 到 28）

---

## 環境 URLs

| 環境 | 建立委託 | 修改委託狀態 |
|---|---|---|
| 測試（sandbox） | `https://ccore.newebpay.com/MPG/period` | `https://ccore.newebpay.com/MPG/period/AlterStatus` |
| 正式（production） | `https://core.newebpay.com/MPG/period` | `https://core.newebpay.com/MPG/period/AlterStatus` |

---

## 建立委託 POST 表單欄位

提交到藍新的 HTML form 只有兩個欄位（注意底線）：

```
MerchantID_  = 商店代號
PostData_    = AES 加密後的字串（見下方加密規格）
```

---

## 加密規格

與 MPG 完全相同：AES-256-CBC + PKCS7 + hex 輸出。

```python
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad
import urllib.parse

def aes_encrypt(data: str, key: str, iv: str) -> str:
    cipher = AES.new(key.encode(), AES.MODE_CBC, iv.encode())
    return cipher.encrypt(pad(data.encode(), AES.block_size)).hex()

params = urllib.parse.urlencode(request_params)
PostData_ = aes_encrypt(params, HASH_KEY, HASH_IV)
```

---

## 建立委託請求參數（PostData_ 加密前）

| 參數名稱 | 必填 | 說明 |
|---|---|---|
| `RespondType` | ✅ | 固定 `JSON` |
| `Version` | ✅ | 固定 `1.5` |
| `TimeStamp` | ✅ | Unix timestamp（允許 ±120 秒誤差） |
| `MerOrderNo` | ✅ | 商店訂單號，限英數字底線，同商店不重覆，最長 30 字元 |
| `ProdDesc` | ✅ | 商品名稱，限中英數字空格底線，最長 100 字元 |
| `PeriodAmt` | ✅ | 每期金額，正整數 TWD，最長 6 位 |
| `PeriodType` | ✅ | `D`=固定天期 / `W`=每週 / `M`=每月 / `Y`=每年 |
| `PeriodPoint` | ✅ | 扣款時間點（見下方說明） |
| `PeriodStartType` | ✅ | `1`=十元驗證 / `2`=立即首期授權 / `3`=不授權（搭配 PeriodFirstdate） |
| `PeriodTimes` | ✅ | 總授權期數，2～99；CAU 啟用時可填 `NE`（無限期） |
| `PayerEmail` | ✅ | 付款人 email，最長 50 字元 |
| `ReturnURL` | | 首期完成後 Form POST 導回商店的 URL |
| `NotifyURL` | | 每期授權結果幕後通知 URL |
| `BackURL` | | 取消交易時返回商店 URL |
| `PeriodFirstdate` | | 首期授權日，格式 `YYYY/MM/DD`，**只在 PeriodType=D 且 PeriodStartType=3 時有效** |
| `PeriodMemo` | | 備註說明，最長 255 字元 |
| `EmailModify` | | 付款頁是否允許修改 email：`1`=可改 / `0`=不可改（預設 1） |
| `PaymentInfo` | | 是否顯示付款人資訊欄位：`Y`/`N`（預設 Y） |
| `OrderInfo` | | 是否顯示收件人資訊欄位：`Y`/`N`（預設 Y） |
| `LangType` | | 語系：`zh-Tw`（預設）/ `en` |

### PeriodPoint 格式

| PeriodType | PeriodPoint 格式 | 範例 |
|---|---|---|
| `D` | 天數 `2`～`999` | `30` = 每 30 天 |
| `W` | 週幾 `1`～`7`（1=週一） | `7` = 每週日 |
| `M` | 月份日期 `01`～`31` | `05` = 每月 5 號（無此日自動用當月最後一天） |
| `Y` | MMDD | `0503` = 每年 5/3 |

---

## 建立完成 Notify（初次，4.3.2）

**觸發時機**：PeriodStartType=2 首期授權完成後，或 PeriodStartType=3 合約建立後。

**Notify 格式**：HTTP POST，body 包含 `Period` 欄位（AES 加密）。

解密後結構：
```json
{
  "Status": "SUCCESS",
  "Message": "委託單成立，且首次授權成功",
  "Result": {
    "MerchantID": "TEK1682407426",
    "MerchantOrderNo": "myorder1700033460",
    "PeriodType": "M",
    "PeriodAmt": "10",
    "AuthTimes": 12,
    "DateArray": "2023-11-15,2023-12-05,...",
    "TradeNo": "23111515321368339",
    "AuthCode": "230297",
    "RespondCode": "00",
    "AuthTime": "20231115153213",
    "CardNo": "400022******1111",
    "EscrowBank": "HNCB",
    "AuthBank": "KGI",
    "PeriodNo": "P231115153213aMDNWZ",
    "PaymentMethod": "CREDIT"
  }
}
```

**辨識方式**：`Result` 中有 `AuthTimes`（總期數）但沒有 `AlreadyTimes`。

---

## 每期授權完成 Notify（NPA-N050，4.3.3）

**觸發時機**：第二期（含）之後每次扣款完成。

解密後結構（解密 `Period` 欄位）：
```json
{
  "Status": "SUCCESS",
  "Message": "授權成功",
  "Result": {
    "RespondCode": "00",
    "MerchantID": "MS12345678",
    "MerchantOrderNo": "periodi1655708272",
    "OrderNo": "periodi1655708272_2",
    "TradeNo": "22062407181613548",
    "AuthDate": "2022-06-24 07:18:17",
    "TotalTimes": 12,
    "AlreadyTimes": 2,
    "AuthAmt": 20,
    "NextAuthDate": "2022-06-26",
    "AuthCode": "681234",
    "PeriodNo": "P220620145859us4Rlj"
  }
}
```

**辨識方式**：`Result` 中有 `AlreadyTimes`（已完成期數，含失敗次數）。

**注意**：`AlreadyTimes` 包含授權失敗的期數，不是純成功次數。

---

## 修改委託狀態 API（4.4，AlterStatus）

**URL**：`POST /MPG/period/AlterStatus`（測試前綴 `c`）

**表單欄位**：
```
MerchantID_  = 商店代號
PostData_    = AES 加密後的字串
```

**PostData_ 加密前參數**：

| 參數 | 必填 | 說明 |
|---|---|---|
| `RespondType` | ✅ | `JSON` |
| `Version` | ✅ | `1.0`（注意不是 1.5） |
| `TimeStamp` | ✅ | Unix timestamp |
| `MerOrderNo` | ✅ | 原始商店訂單號 |
| `PeriodNo` | ✅ | 藍新委託單號（從建立完成 Notify 取得） |
| `AlterType` | ✅ | `suspend`=暫停 / `terminate`=終止 / `restart`=啟用 |

**限制**：
- 已終止（terminate）的委託無法再次啟用
- 暫停中的委託無法再次暫停；已終止的無法暫停
- 有首期授權日（PeriodFirstdate）的委託，授權日隔日前只能執行終止

**回應**：HTTP body 包含 `period` 欄位（AES 加密，字母全小寫），解密後：
```json
{ "Status": "SUCCESS", "Message": "...", "Result": {...} }
```

---

## 修改委託內容 API（4.5，不常用）

URL：`POST /MPG/period/AlterData`

可修改：每期金額、執行週期、信用卡到期日、總期數、NotifyURL。
不可修改已終止或暫停的委託。

---

## 定期定額 vs MPG 差異對照

| 項目 | 定期定額（/MPG/period） | MPG（/MPG/mpg_gateway） |
|---|---|---|
| 表單商店代號欄位 | `MerchantID_` | `MerchantID` |
| 加密資料欄位 | `PostData_` | `TradeInfo` |
| 需要 TradeSha | 否 | 是 |
| 訂單號參數名 | `MerOrderNo` | `MerchantOrderNo` |
| 商品名稱參數名 | `ProdDesc` | `ItemDesc` |
| Email 參數名 | `PayerEmail` | `Email` |
| 金額參數名 | `PeriodAmt` | `Amt` |
| Version | `1.5` | 無此參數 |
| Notify 加密 | AES（`Period` 欄位） | AES（`TradeInfo`）+ SHA256 驗章 |
| 電子發票 | 待確認（手冊無相關參數） | 支援（`InvoiceStatus` 等） |

---

## 本專案中的實作對應

| API 功能 | 程式碼位置 |
|---|---|
| 建立委託（新訂閱/升級，PeriodStartType=2） | `newebpay_service.create_period_form()` |
| 建立委託（降級排程，PeriodType=D+PeriodStartType=3） | `newebpay_service.create_period_form_scheduled()` |
| 終止委託 | `newebpay_service.terminate_period_contract()` |
| Notify 解密 | `newebpay_service.decrypt_period_notify()` |
| Notify handler | `subscriptions.period_notify()` |
| MPG 一次性付款（額外額度） | `newebpay_service.create_mpg_form()` |
