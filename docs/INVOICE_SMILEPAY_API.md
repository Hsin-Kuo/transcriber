# SmilePay（速買配）電子發票 API

> 整理自官方文件，供串接時查找。來源：使用者提供之官方 API 文件（2026-08-07）。
> 相關背景：91APP 金流遷移後的發票開立需求（見 `PAYMENT_91APP_MIGRATION_ASSESSMENT.md`）。
>
> 涵蓋範圍：
> - §1–§9 **開立發票**（`SPEinvoice_Storage.asp`）
> - §10 **發票&折讓單 作廢/註銷/取消執行**（`SPEinvoice_Storage_Modify.asp`）
> - §11 **開立折讓單**（`SPEinvoice_Storage_Allowance.asp`）
> - §12 **列印發票/折讓單**（`InvoiceDetails.php` / `AllowanceDetails.php`，網頁列印畫面）
> - §13 SoundLite 實作備忘
>
> 以上即官方提供的全部 API（2026-08-07 確認）。**沒有發票查詢/狀態 API**——狀態追蹤只能靠我方 DB 落庫與速買配後台，見 §13。

---

# 第一部分：開立發票（SPEinvoice_Storage）

## 1. 基本資訊

| 項目 | 內容 |
|------|------|
| 正式環境 | `https://ssl.smse.com.tw/api/SPEinvoice_Storage.asp` |
| 測試環境 | `https://ssl.smse.com.tw/api_test/SPEinvoice_Storage.asp` |
| 傳輸方式 | POST 或 GET 皆可 |
| 編碼 | 僅 UTF-8 |
| 回應格式 | XML（`<SmilePayEinvoice>`） |
| 參數大小寫 | **區分大小寫** |

**憑證（Grvc / Verify_key）是速買配後台配發的商家專屬機密**——測試與正式共用同一組,
只差 endpoint（`/api_test/` vs `/api/`）。**勿寫入本文件或 repo 任何檔案**;實際值放 SSM
`/transcriber/smilepay-*`（staging 為 `/transcriber-staging/smilepay-*`）。下例佔位僅示格式:
- `Grvc=SEI0000000`（格式:`SEI` + 7 碼）
- `Verify_key=0123456789ABCDEF0123456789ABCDEF`（格式:32 碼 hex）

正式環境的 `Grvc` / `Verify_key` 由速買配提供 → 應存 SSM Parameter Store（`/transcriber/*`），**禁止硬編碼**。

參數分四大區塊：**使用者參數 / 發票資訊 / 商品明細 / 買受人資訊**。

必填標記：Ｏ＝必要、▲＝非必要、Ｘ＝不用填（分 B2C / B2B 兩欄）。

---

## 2. 使用者參數

| 參數 | 名稱 | B2C | B2B | 說明 |
|------|------|-----|-----|------|
| `Grvc` | 電子發票帳號 | Ｏ | Ｏ | 由速買配提供，如 `SEI0000000` |
| `Verify_key` | 驗證碼 | Ｏ | Ｏ | 由速買配提供 |

## 3. 發票資訊

| 參數 | 名稱 | B2C | B2B | 格式 | 說明 |
|------|------|-----|-----|------|------|
| `InvoiceNumber` | 發票號碼 | ▲ | ▲ | 英文(2)+數字(8) 共 10 碼，不可有符號 | 營業人自行管理字軌時使用（需與速買配聯繫） |
| `RandomNumber` | 隨機碼 | ▲ | ▲ | 4 字元（數字） | 同上（自管字軌時使用） |
| `InvoiceDate` | 開立發票日期 | Ｏ | Ｏ | `YYYY/MM/DD` | **B2C 僅能開立 48 小時內；B2B 僅能開立 168 小時內** |
| `InvoiceTime` | 開立發票時間 | Ｏ | Ｏ | `HH:MM:SS` | |
| `TrackSystemID` | 自訂字軌系統代號 | ▲ | ▲ | 中/英/數字 | 於後台【字軌管理】設定，帶入可指定字軌 |
| `Intype` | 發票稅率類型 | Ｏ | Ｏ | `07` / `08` | `07`：一般稅額（TaxType 允許 1/2/3/9）；`08`：特種稅額（TaxType 允許 2/3/4/9） |
| `TaxType` | 課稅別 | Ｏ | Ｏ | `1`/`2`/`3`/`4`/`9` | 1 應稅、2 零稅率、3 免稅、4 應稅(特種稅率)、9 混合應稅與免稅（限收銀機發票無法分辨時） |
| `TaxRate` | 稅率 | ▲ | ▲ | 小數 0.00~1.00 | 僅特種稅額有效（`Intype=08` 且 `TaxType=4/9`）。例：0.25、0.15（特種飲食業）、0.01（查定課徵）、0.001（農產品） |
| `BuyerRemark` | 買受人註記 | ▲ | ▲ | `1`~`4` | 可空白。1 得抵扣進貨及費用、2 得抵扣固定資產、3 不得抵扣進貨及費用、4 不得抵扣固定資產 |
| `CustomsClearanceMark` | 通關方式註記 | ▲ | ▲ | `1`/`2` | **零稅率發票必填**。1 非經海關出口、2 經海關出口 |
| `GroupMark` | 彙開註記 | ▲ | ▲ | `Y` | 可空白，彙開發票再填 |
| `BondedAreaConfirm` | 買受人簽署適用零稅率註記 | Ｘ | ▲ | `1`~`4` | 可空白。1 保稅區營業人、2 遠洋漁業營業人、3 自由貿易港區營業人、4 其他。有值時回應 `InvoiceType=B2B` |
| `ZeroTaxRateReason` | 零稅率原因 | ▲ | ▲ | `71`~`79` | **零稅率發票必填**。對應營業稅法第 7 條各款：71 外銷貨物、72 外銷相關勞務/國內提供國外使用、73 免稅商店售過境出境旅客、74 售保稅區營業人供營運、75 國際運輸、76 國際運輸用船舶/航空器/遠洋漁船、77 售前述所用貨物或修繕勞務、78 保稅區售課稅區未輸往課稅區直接出口、79 保稅區售課稅區存入自由港區/保稅倉庫/物流中心供外銷 |
| `MainRemark` | 總備註 | ▲ | ▲ | 200 字元 | 呈現在 A4、A5 紙張格式 |
| `RelateNumber` | 相關號碼 | ▲ | ▲ | 20 字元 | |
| `DonateMark` | 捐贈 | Ｏ | Ｏ | `1`/`0` | 1 捐贈、0 不捐贈。**有 `Buyer_id` 時必須為 0**；捐贈時不可填 `CarrierType` |
| `LoveKey` | 愛心碼 | ▲ | Ｘ | | `DonateMark=1` 時**不可為空** |
| `Visa_Last4` | 信用卡末四碼 | ▲ | ▲ | 4 字元 | 刷卡交易填入卡號末四碼 |
| `data_id` | 自訂發票編號 | ▲ | ▲ | 50 字元 | **同期別內不可重複**（除非該發票已作廢）→ 可當 idempotency key |
| `orderid` | 自訂號碼 | ▲ | ▲ | 30 字元 | 營業人自訂 |
| `PosSystemID` | 營業人自定義系統代號 | ▲ | ▲ | 20 字元（英/數） | 區分不同開立來源 |
| `Certificate_Remark` | 發票證明聯備註 | ▲ | ▲ | 34 字元 | 呈現在熱感紙證明聯與 A4/A5 |
| `Einvoice_Type` | 發票類型 | — | — | `B2B` | 文件僅出現在 B2G 範例：**B2G 發票必須帶 `Einvoice_Type=B2B`** |

## 4. 商品明細

> 除 `AllAmount` / `UnitTAX` 外，**均以半形 `|` 分隔多項商品**，各欄位項數必須相同。

| 參數 | 名稱 | B2C | B2B | 格式 | 說明 |
|------|------|-----|-----|------|------|
| `Description` | 商品明細 | Ｏ | Ｏ | `商品1\|商品2` | 勿填符號，每項最多 256 字 |
| `Quantity` | 數量明細 | Ｏ | Ｏ | `數量1\|數量2` | 純數字，**必須 > 0** |
| `UnitPrice` | 單價明細 | Ｏ | Ｏ | `單價1\|單價2` | 純數字，可 < 0；含稅/未稅由 `UnitTAX` 決定 |
| `Unit` | 單位明細 | ▲ | ▲ | `單位1\|單位2` | 勿填符號，每項最多 6 字 |
| `ProductTaxType` | 商品稅率明細 | ▲ | ▲ | `稅率1\|稅率2` | `TaxType=9`（混合稅率）時**必填**。1 應稅、3 免稅 |
| `Remark` | 商品備註明細 | ▲ | ▲ | `備註1\|備註2` | 勿填符號，每項最多 40 字 |
| `Amount` | 各明細總額 | Ｏ | Ｏ | `金額1\|金額2` | 每項 = 數量×單價；純數字，可 < 0 |
| `AllAmount` | 總金額（含稅） | Ｏ | Ｏ | 整數，≥ 0 | 各 `Amount` 合計，**必須含稅** |
| `SalesAmount` | 應稅銷售額 | ▲ | ▲ | 整數，≥ 0 | `TaxType=9` 時 B2C/B2B 須提供**含稅**銷售額；`TaxType=1` 之 B2B 填**未稅**銷售額 |
| `FreeTaxSalesAmount` | 免稅銷售額 | ▲ | Ｘ | 整數，≥ 0 | 僅 `TaxType=9` 時提供 |
| `ZeroTaxSalesAmount` | 零稅率銷售額 | ▲ | Ｘ | 整數，≥ 0 | |
| `UnitTAX` | 單價含稅 | Ｘ | ▲ | `Y`/`N` | 單價是否含稅。Y 含稅（預設）、N 未稅 |
| `TaxAmount` | 稅金 | Ｘ | ▲ | 整數，≥ 0 | 僅 B2B 生效，營業人自行計算 |

## 5. 買受人資訊

| 參數 | 名稱 | B2C | B2B | 格式 | 說明 |
|------|------|-----|-----|------|------|
| `Buyer_id` | 買受人統編 | Ｘ | Ｏ | | **有值 → B2B 發票；空值 → B2C 發票**（切換開關） |
| `CompanyName` | 買受人公司名稱 | Ｘ | ▲ | 30 字元 | 勿填符號 |
| `Name` | 買受人姓名 | ▲ | Ｘ | 30 字元 | 一般發票填買受人姓名；`CarrierType=EJ0113_shopee` 且未提供 `CarrierShopeeID` 時作為蝦皮帳號補位 |
| `Phone` | 電話 | ▲ | ▲ | `0900123456` | 純數字，勿填符號 |
| `Facsimile` | 傳真 | Ｘ | ▲ | | 純數字 |
| `Email` | 信箱 | ▲ | ▲ | 80 字元 | 多組用 `;` 分隔 |
| `Address` | 地址 | ▲ | ▲ | 100 字元 | |
| `CarrierType` | 載具類型 | ▲ | Ｘ | 見下 | 速買配載具 `EJ0113`、速買配載具(蝦皮) `EJ0113_shopee`、手機條碼 `3J0002`、自然人憑證 `CQ0001` |
| `CarrierID` | 載具 ID 明碼 | ▲ | Ｘ | | `CarrierType` 有值時不可為空；但用 `EJ0113` 可透過 Email/Phone 註冊載具，此處可空白 |
| `CarrierID2` | 載具 ID 暗碼 | ▲ | Ｘ | | 規則同 `CarrierID` |
| `CarrierShopeeID` | 蝦皮帳號 | ▲ | Ｘ | 30 字元 | `CarrierType=EJ0113_shopee` 時建議填入，優先用此值建立速買配載具 |

## 6. 開立規則矩陣（互斥規則）

| 欄位 | 個人–捐贈 | 個人–載具 | 公司–統編發票 |
|------|-----------|-----------|----------------|
| `DonateMark` | 填 `1` | Ｘ | 填 `0` |
| `LoveKey` | Ｏ | Ｘ | Ｘ |
| `CarrierType` | Ｘ | Ｏ | Ｘ |
| `CarrierID` | Ｘ | Ｏ | Ｘ |
| `Buyer_id` | Ｘ | Ｘ | Ｏ |

重點互斥規則：
- 有統編（`Buyer_id`）→ `DonateMark` 必為 `0`、不可用載具（錯誤碼 -10022 / -10024）
- 捐贈（`DonateMark=1`）→ `LoveKey` 必填、不可填 `CarrierType`
- 零稅率（`TaxType=2`）→ `CustomsClearanceMark` 與 `ZeroTaxRateReason` 必填

## 7. 範例（測試區）

**B2C**（無統編，`Name` 為買受人姓名）：

```
https://ssl.smse.com.tw/api_test/SPEinvoice_Storage.asp?Grvc=SEI0000000&Verify_key=0123456789ABCDEF0123456789ABCDEF&Name=速買配&Phone=0900000000&Email=Test@testmailserver.net&Intype=07&TaxType=1&LoveKey=&DonateMark=0&Description=商品1|商品2&Quantity=5|8&UnitPrice=10|15&Unit=顆|條&Amount=50|120&ALLAmount=170&InvoiceDate=2026/8/7&InvoiceTime=15:33:33
```

**B2B**（帶 `Buyer_id`、`CompanyName`）：

```
https://ssl.smse.com.tw/api_test/SPEinvoice_Storage.asp?Grvc=SEI0000000&Verify_key=0123456789ABCDEF0123456789ABCDEF&CompanyName=速買配&Phone=0900000000&Email=Test@testmailserver.net&Intype=07&TaxType=1&LoveKey=&DonateMark=0&Description=商品1|商品2&Quantity=5|8&UnitPrice=10|15&Unit=顆|條&Amount=50|120&ALLAmount=170&InvoiceDate=2026/8/7&InvoiceTime=15:33:33&Buyer_id=80129529
```

**B2G**（統編不可空白、金額必須含稅 `UnitTAX=Y`、必帶 `Einvoice_Type=B2B`）：

```
https://ssl.smse.com.tw/api_test/SPEinvoice_Storage.asp?Grvc=SEI0000000&Verify_key=0123456789ABCDEF0123456789ABCDEF&CompanyName=速買配&Phone=0900000000&Email=Test@testmailserver.net&Intype=07&TaxType=1&LoveKey=&DonateMark=0&Description=商品&Quantity=1&UnitPrice=100&Unit=顆&Amount=100&ALLAmount=100&InvoiceDate=2026/8/7&InvoiceTime=15:33:33&Buyer_id=80129529&UnitTAX=Y&Einvoice_Type=B2B
```

> 注意：官方範例中總金額參數寫作 `ALLAmount`，欄位表寫作 `AllAmount`。**2026-08-07 測試環境實測：兩種拼法都接受**（classic ASP 參數名不分大小寫），實作統一用官方範例的 `ALLAmount`。

## 8. 回應格式（XML）

```xml
<SmilePayEinvoice>
  <Status>0</Status>
  <Desc></Desc>
  <Grvc>SEI1000002</Grvc>
  <orderno>order20171231</orderno>
  <data_id>inid00001</data_id>
  <InvoiceNumber>YY00000000</InvoiceNumber>
  <RandomNumber>1234</RandomNumber>
  <InvoiceDate>2017/12/31</InvoiceDate>
  <InvoiceTime>23:59:59</InvoiceTime>
  <InvoiceType>B2C</InvoiceType>
  <CarrierID></CarrierID>
</SmilePayEinvoice>
```

| Tag | 說明 |
|-----|------|
| `Status` | 狀態碼（`0` = 成功，其餘見 §9） |
| `Desc` | 詳細原因 |
| `orderno` | 自訂號碼（對應請求的 `orderid`） |
| `data_id` | 自訂發票編號 |
| `InvoiceNumber` | 實際開立的發票號碼 |
| `RandomNumber` | 隨機碼 |
| `InvoiceDate` / `InvoiceTime` | 開立日期 / 時間 |
| `InvoiceType` | `B2C`：無統編一般發票；`B2C2B`：有統編、可接受發票作廢；`B2B`：有統編、無法註銷（`BondedAreaConfirm` 有值時給此） |
| `CarrierID` | 如申請速買配載具會回應載具號碼 |

## 9. 回應代號（錯誤碼）

| 代號 | 說明 | 代號 | 說明 |
|------|------|------|------|
| `0` | 開立成功 | `-1001` | 商家帳號缺少參數 |
| `-10011` | 查無商家帳號 | `-10012` | 尚未開放 B2B 功能 |
| `-10013` | 尚未開放 B2C 功能 | `-10021` | 統一編號(Buyer_id)格式錯誤 |
| `-10022` | 統一編號不可捐贈，DonateMark 必須為 0 | `-10023` | 統一編號(Buyer_id)內容錯誤 |
| `-10024` | 統一編號不可使用其他載具(CarrierType) | `-10025` | 缺少公司名稱(CompanyName) |
| `-10031` | 缺少開立日期(InvoiceDate、InvoiceTime) | `-10032` | 日期格式(InvoiceDate、InvoiceTime)錯誤 |
| `-10033` | B2C 開立需在 48hr 內 | `-10034` | B2B 開立需在 168hr 內 |
| `-10041` | 發票類別(Intype)錯誤 | `-10042` | 買受人註記欄(BuyerRemark)錯誤 |
| `-10043` | 通關方式註記(CustomsClearanceMark) | `-10044` | 捐贈註記(DonateMark)錯誤 |
| `-10045` | 愛心碼(LoveKey)空白 | `-10046` | 愛心碼伺服器異常 |
| `-10047` | 查無此愛心碼(LoveKey) | `-10048` | 課稅別(TaxType)錯誤 |
| `-10049` | 買受人簽署適用零稅率註記(BondedAreaConfirm)錯誤 | `-100410` | 總備註(MainRemark)錯誤 |
| `-100411` | 相關號碼(RelateNumber)錯誤 | `-100412` | 零稅率原因(ZeroTaxRateReason)錯誤 |
| `-10051` | 手機號碼(Phone)格式錯誤 | `-10052` | 載具號碼(CarrierID)錯誤 |
| `-10053` | 查無載具號碼(CarrierID) | `-10054` | 缺少建立載具參數 Email/Phone |
| `-10055` | 建立載具失敗 | `-10056` | 查無手機條碼(CarrierID) |
| `-10057` | 自然人憑證(CarrierID)格式錯誤 | `-10058` | 載具類型(CarrierType)非允許使用 |
| `-10061` | 商品各項目數量不符 | `-10062` | 內容長度不正確（單一品項）：Description 256 字不可空白、Unit 6 字可空白、Remark 40 字可空白 |
| `-10063` | 商品數量(Quantity)內容錯誤 | `-10064` | 商品金額(UnitPrice、Amount)內容錯誤 |
| `-10065` | 商品小計(UnitPrice、Amount)驗算錯誤 | `-10066` | 商品總金額(AllAmount)驗算錯誤 |
| `-10067` | 商品與總金額(ALLAmount)不符合規定 | `-10068` | 混合稅率銷售額明細(SalesAmount、FreeTaxSalesAmount)內容錯誤 |
| `-10069` | 稅金(TaxAmount)與未稅銷售額(SalesAmount)驗算錯誤 | `-100610` | 稅率(TaxRate)內容錯誤 |
| `-100611` | 產品稅率(ProductTaxType)內容錯誤 | `-10071` | 無可用字軌 |
| `-10072` | 自訂發票編號(data_id)重複 | `-10073` | 營業人自定義系統代號(PosSystemID)格式錯誤 |
| `-10081` | 信用卡末四碼(Visa_Last4)格式錯誤 | `-10082` | 發票證明聯備註(Certificate_Remark)格式錯誤 |
| `-10083` | 自訂發票編號(data_id)格式錯誤 | `-10084` | 自訂號碼(orderid)格式錯誤 |
| `-2001` | InvoiceNumber 格式錯誤 | `-2002` | RandomNumber 格式錯誤 |
| `-2003` | InvoiceNumber 不可重複 | | |

# 第二部分：發票&折讓單 作廢/註銷（SPEinvoice_Storage_Modify）

## 10. 作廢/註銷/取消執行

### 10.1 基本資訊

| 項目 | 內容 |
|------|------|
| 正式環境 | `https://ssl.smse.com.tw/api/SPEinvoice_Storage_Modify.asp` |
| 測試環境 | `https://ssl.smse.com.tw/api_test/SPEinvoice_Storage_Modify.asp` |
| 編碼 | 僅 UTF-8 |
| 回應格式 | XML（`<SmilePayEinvoice>`） |
| 參數大小寫 | **區分大小寫** |

一支 API 靠 `types` 參數切四種操作：

| `types` 值 | 操作 | 對象 |
|-----------|------|------|
| `Cancel` | 作廢發票 | 發票 |
| `Void` | 註銷發票 | 發票 |
| `CancelAllowance` | 作廢折讓單 | 折讓單 |
| `StopProcessing` | 取消執行（停止作廢/註銷作業並返回先前狀態） | **限發票**；若大平台已接收則無法執行 |

### 10.2 欄位參數

必填標記：Ｏ＝必要、▲＝非必要、Ｘ＝無法使用。

**使用者參數**

| 參數 | 名稱 | 說明 |
|------|------|------|
| `Grvc` | 商家代號 | 由速買配提供 |
| `Verify_key` | 驗證碼 | 由速買配提供 |

**相關欄位**

| 參數 | 名稱 | 格式 | 說明 |
|------|------|------|------|
| `types` | 服務類型 | `Cancel`/`Void`/`CancelAllowance`/`StopProcessing` | 見 §10.1 |
| `InvoiceNumber` | 發票號碼 | | 需處理的發票號碼 |
| `InvoiceDate` | 發票日期 | | 該筆發票日期 |
| `AllowanceNumber` | 折讓單號碼 | | 需處理的折讓單號碼 |
| `AllowanceDate` | 折讓單日期 | | 該筆折讓單日期 |
| `CancelReason` | 作廢原因 | 20 字元 | 作廢發票/折讓單實際原因 |
| `ReturnTaxDocumentNumber` | 專案作廢核准文號 | 60 字元 | 可空白，如有核准文號請填入 |
| `VoidReason` | 註銷原因 | 20 字元 | 註銷發票實際原因 |
| `Remark` | 備註 | 200 字元 | |

### 10.3 各操作必填規則矩陣

| 欄位 | 作廢發票（Cancel） | 註銷發票（Void） | 作廢折讓單（CancelAllowance） | 取消執行（StopProcessing） |
|------|:---:|:---:|:---:|:---:|
| `InvoiceNumber` | Ｏ | Ｏ | Ｘ | Ｏ |
| `InvoiceDate` | Ｏ | Ｏ | Ｘ | Ｏ |
| `AllowanceNumber` | Ｘ | Ｘ | Ｏ | Ｘ |
| `AllowanceDate` | Ｘ | Ｘ | Ｏ | Ｘ |
| `CancelReason` | Ｏ | Ｘ | Ｏ | Ｘ |
| `ReturnTaxDocumentNumber` | ▲ | Ｘ | Ｘ | Ｘ |
| `VoidReason` | Ｘ | Ｏ | Ｘ | Ｘ |
| `Remark` | ▲ | ▲ | ▲ | Ｘ |

### 10.4 回應格式（XML）

> **⚠️ 2026-08-07 實測：此 API 實際回應的 root tag 是 `<SmilePayEinvoiceModify>`，不是官方文件範例寫的 `<SmilePayEinvoice>`**；且 `CancelDate` 實測為 `2026-08-07`（dash），非範例的 slash 格式。Parser 兩種 root tag 都要吃。

```xml
<SmilePayEinvoice>
  <Status>0</Status>
  <Desc></Desc>
  <Types></Types>
  <Grvc>SEI1000002</Grvc>
  <InvoiceNumber>YY00000000</InvoiceNumber>
  <AllowanceNumber>SMEE000000000000</AllowanceNumber>
  <CancelDate>2017/12/31</CancelDate>
  <CancelTime>23:59:59</CancelTime>
  <VoidDate>2017/12/31</VoidDate>
  <VoidTime>23:59:59</VoidTime>
  <RejectDate>2017/12/31</RejectDate>
  <RejectTime>23:59:59</RejectTime>
</SmilePayEinvoice>
```

| Tag | 說明 |
|-----|------|
| `Status` | 狀態碼（`0` = 成功，其餘見 §10.5） |
| `Desc` | 詳細原因 |
| `Nowstatus` | 物流狀態，**僅在 `-2008` 時提供**（可用來診斷目前發票狀態） |
| `Types` | 服務類型（回填請求的 types） |
| `Grvc` | 商家代號 |
| `InvoiceNumber` | 發票號碼 |
| `AllowanceNumber` | 折讓單號碼 |
| `CancelDate` / `CancelTime` | 作廢日期/時間，僅 `types=Cancel`/`CancelAllowance` 回應 |
| `VoidDate` / `VoidTime` | 註銷日期/時間，僅 `types=Void` 回應 |
| `RejectDate` / `RejectTime` | 出現在回應範例但官方 tag 表未說明（推測與 StopProcessing/退回相關），實測確認 |

### 10.5 回應代號（錯誤碼）

| 代號 | 說明 |
|------|------|
| `0` | 成功 |
| `-1000` | 商家帳號缺少參數 |
| `-1001` | 查無商家帳號 |
| `-1002` | 服務類型錯誤 |
| `-2001` | 缺少發票號碼(InvoiceNumber)或作廢原因(CancelReason) |
| `-2002` | 作廢原因(CancelReason)超過字數 |
| `-2003` | 專案作廢核准文號(ReturnTaxDocumentNumber)超過字數 |
| `-2004` | 備註(Remark)超過字數 |
| `-2005` | 缺少發票號碼(InvoiceNumber)或註銷原因(VoidReason) |
| `-2006` | 註銷原因(VoidReason)超過字數 |
| `-2007` | 缺少折讓單號碼(AllowanceNumber)或作廢原因(CancelReason) |
| `-2008` | **發票目前狀態不允許執行該動作**（此時回應會多帶 `Nowstatus`） |
| `-2009` | **發票有折讓紀錄不允許執行該動作**（須先處理折讓單） |
| `-2010` | 查無該筆發票/折讓單 |

---

# 第三部分：開立折讓單（SPEinvoice_Storage_Allowance）

## 11. 開立折讓單

### 11.1 基本資訊

| 項目 | 內容 |
|------|------|
| 正式環境 | `https://ssl.smse.com.tw/api/SPEinvoice_Storage_Allowance.asp` |
| 測試環境 | `https://ssl.smse.com.tw/api_test/SPEinvoice_Storage_Allowance.asp` |
| 編碼 | 僅 UTF-8 |
| 回應格式 | XML（`<SmilePayEinvoice>`） |
| 參數大小寫 | **區分大小寫** |

必填標記：Ｏ＝必要、▲＝非必要、Ｘ＝不用填。

### 11.2 使用者參數

| 參數 | 名稱 | 說明 |
|------|------|------|
| `Grvc` | 電子發票帳號 | 由速買配提供 |
| `Verify_key` | 驗證碼 | 由速買配提供 |

### 11.3 折讓單資訊

| 參數 | 名稱 | 格式 | 說明 |
|------|------|------|------|
| `InvoiceNumber` | 發票號碼 | | 需折讓的發票號碼 |
| `InvoiceDate` | 發票日期 | | 該發票的開立日期 |
| `AllowanceNumber` | 折讓單號碼 | 15 字元（英/數混合），不可填符號 | **可空白，速買配自動產生**；自填則不可重複（`-10032`） |
| `AllowanceDate` | 折讓日期 | `YYYY-MM-DD` | 可空白。**注意：格式用 dash，與發票的 `YYYY/MM/DD`（slash）不同** |
| `AllowanceType` | 折讓類型 | `1`/`2` | 1：買方開立折讓單；2：賣方開立折讓單（**預設**） |

### 11.4 折讓明細

> 均以半形 `|` 分隔，依折讓明細排列，各欄位項數必須相同。
> **⚠️ 金額一律「未稅」**——與開立發票 API（B2C 含稅）相反，稅金要自行拆算另填 `Tax`。

| 參數 | 名稱 | 格式 | 說明 |
|------|------|------|------|
| `Description` | 商品明細 | `商品1\|商品2` | 勿填符號 |
| `Quantity` | 數量明細 | `數量1\|數量2` | 純數字，**必須 > 0** |
| `UnitPrice` | 單價明細（**未稅**） | `單價1\|單價2` | 純數字，可 < 0 |
| `Unit` | 單位明細 | `單位1\|單位2` | 可空白，勿填符號 |
| `Amount` | 各明細總額（**未稅**） | `金額1\|金額2` | 每項 = 數量 × 單價(未稅)；純數字，可 < 0 |
| `Tax` | 稅金 | `稅金1\|稅金2` | **營業人自行計算**，純數字 |
| `TaxType` | 課稅別 | `課稅別1\|課稅別2` | 1 應稅、2 零稅率、3 免稅、4 應稅(特種稅率)。**每項明細各帶一個**（與開立發票的單一 `TaxType` 不同） |

### 11.5 回應格式（XML）

```xml
<SmilePayEinvoice>
  <Status>0</Status>
  <Desc></Desc>
  <Grvc>SEI1000002</Grvc>
  <InvoiceNumber>YY00000000</InvoiceNumber>
  <AllowanceNumber>YY00000000</AllowanceNumber>
</SmilePayEinvoice>
```

| Tag | 說明 |
|-----|------|
| `Status` | 狀態碼（`0` = 成功，其餘見 §11.6） |
| `Desc` | 詳細原因 |
| `Grvc` | 商家代號 |
| `InvoiceNumber` | 發票號碼 |
| `AllowanceNumber` | 折讓單號碼（自動產生時從這裡取回，**必存 DB**，作廢折讓單要用） |

### 11.6 回應代號（錯誤碼）

| 代號 | 說明 |
|------|------|
| `0` | 成功 |
| `-1001` | 商家帳號缺少參數 |
| `-10011` | 查無商家帳號 |
| `-1002` | 發票號碼(InvoiceNumber)錯誤 |
| `-10021` | 商品不可空白 |
| `-10022` | 商品各項目數量不符 |
| `-10023` | 商品明細(Description)參數異常 |
| `-10024` | 數量明細(Quantity)參數異常 |
| `-10025` | 單價明細(UnitPrice)金額異常 |
| `-10026` | 稅金明細(TaxType)參數異常 |
| `-10027` | 稅率明細(Tax)參數異常 |
| `-10028` | 折讓日期(AllowanceDate)參數異常 |
| `-1003` | 查無此筆發票 |
| `-10031` | **超過可折讓金額**（累計折讓不可超過發票金額） |
| `-10032` | 折讓單號碼(AllowanceNumber)不可重複 |

> 注意：`-10026`/`-10027` 的官方說明文字與參數名對調（-10026 寫 TaxType、-10027 寫 Tax），判斷錯誤時兩個都檢查。

---

# 第四部分：列印發票/折讓單（網頁列印畫面）

## 12. 列印發票 / 列印折讓單

> 性質不同於前三支：**不是資料 API，是開啟一個網頁列印畫面**（瀏覽器列印對話框，可 A4/A5/證明聯/PDF 下載）。POST 或 GET 皆可。
> **⚠️ URL 參數含 `Grvc`+`Verify_key`（商家憑證）——絕不可把這種 URL 直接發給終端使用者或嵌進前端**，見 §13 備忘。

### 12.1 端點

| 功能 | 版型 | 環境 | URL |
|------|------|------|-----|
| 列印發票（網頁模式） | A4/A5/證明聯/PDF 下載 | 正式 | `https://einvoice.smilepay.net/einvoice/SmilePayCarrier/InvoiceDetails.php` |
| | | 測試 | `https://einvoice.smilepay.net/einvoice_test/SmilePayCarrier/InvoiceDetails.php` |
| 列印發票（EPSON IP 列印） | 證明聯 | 正式 | `https://einvoice.smilepay.net/einvoice/Invoice_Print/Invoice_Print_EPSON.php` |
| | | 測試 | `https://einvoice.smilepay.net/einvoice_test/Invoice_Print/Invoice_Print_EPSON.php` |
| 列印折讓單（網頁模式） | A4/證明聯/PDF 下載 | 正式 | `https://einvoice.smilepay.net/einvoice/SmilePayCarrier/AllowanceDetails.php` |
| | | 測試 | `https://einvoice.smilepay.net/einvoice_test/SmilePayCarrier/AllowanceDetails.php` |

> 注意網域是 `einvoice.smilepay.net`，與資料 API 的 `ssl.smse.com.tw` 不同。

### 12.2 列印發票參數

| 參數 | 名稱 | 格式 | 說明 |
|------|------|------|------|
| `Grvc` | 電子發票帳號 | 由速買配提供 | |
| `Verify_key` | 驗證碼 | 由速買配提供 | |
| `InNumber` | 發票號碼 | 英文(2)+數字(8) 共 10 碼 | **注意參數名是 `InNumber`，不是開立 API 的 `InvoiceNumber`** |
| `InvoiceDate` | 發票日期 | `YYYY/MM/DD` | |
| `RaNumber` | 發票認證碼 | 數字 | **B2C 發票＝隨機碼（RandomNumber）；B2B 發票＝買受人統編** |
| `DetailPrint` | 呈現交易明細聯 | `Y`／不帶入 | 是否出現交易明細聯 |
| `AutoPrint` | 自動列印 | `Y`／不帶入 | 開啟網頁後自動執行列印 |
| `Printer_ip` | 指定印表機 IP | `192.168.10.10`／不帶入 | 僅適用 EPSON IP 列印 |

### 12.3 列印折讓單參數

| 參數 | 名稱 | 格式 | 說明 |
|------|------|------|------|
| `Grvc` | 電子發票帳號 | 由速買配提供 | |
| `Verify_key` | 驗證碼 | 由速買配提供 | |
| `InNumber` | 發票號碼 | 英文(2)+數字(8) 共 10 碼 | 原發票號碼 |
| `AllowanceNumber` | 折讓單號碼 | 由速買配產生 | 開立折讓單（§11）回應取回的號碼，如 `SM00000001209905` |

### 12.4 範例（測試區）

B2C 發票（`RaNumber`＝隨機碼）：

```
https://einvoice.smilepay.net/einvoice_test/SmilePayCarrier/InvoiceDetails.php?Grvc=SEI0000000&Verify_key=0123456789ABCDEF0123456789ABCDEF&InNumber=HG00631928&InvoiceDate=2024/11/06&RaNumber=7572
```

B2B 發票（`RaNumber`＝買受人統編）：

```
https://einvoice.smilepay.net/einvoice_test/SmilePayCarrier/InvoiceDetails.php?Grvc=SEI0000000&Verify_key=0123456789ABCDEF0123456789ABCDEF&InNumber=HG00631929&InvoiceDate=2024/11/06&RaNumber=80129529
```

折讓單：

```
https://einvoice.smilepay.net/einvoice_test/SmilePayCarrier/AllowanceDetails.php?Grvc=SEI0000000&Verify_key=0123456789ABCDEF0123456789ABCDEF&InNumber=XD65128761&AllowanceNumber=SM00000001209905
```

---

## 13. 串接注意事項（SoundLite 實作備忘）

- **Idempotency**：`data_id` 同期別內不可重複（`-10072`）。建議以我方訂單號（91APP `orderNo` 或內部 order `_id`）當 `data_id`，天然防重複開立；重試同一筆會被擋下。
- **時效**：B2C 48hr / B2B 168hr（`-10033`/`-10034`）。付款成功 webhook 進來後應盡快開立；若走排程補開要注意時窗。
- **金額驗算**：API 會驗 `Quantity×UnitPrice=Amount`、`ΣAmount=AllAmount`（`-10065`/`-10066`）。我方訂閱金額為含稅價，B2C 直接帶含稅即可（B2C 不吃 `UnitTAX`，一律含稅）。
- **B2C/B2B 切換**：靠 `Buyer_id` 有無值，沒有獨立參數（B2G 例外需 `Einvoice_Type=B2B`）。使用者填了統編就必須帶 `CompanyName`（`-10025`），且 `DonateMark=0`、不可帶載具。
- **回應是 XML 不是 JSON**：需用 XML parser 解析（Python 建議 `xml.etree.ElementTree` 或 `defusedxml`——外部輸入用 `defusedxml` 較安全）。
- **無簽名機制**：請求僅靠 `Grvc`+`Verify_key` 明文驗證，務必走 HTTPS、金鑰放 SSM，log 時遮罩 `Verify_key`。
- **字元限制**：品名/單位/備註不可含符號；`|` 是明細分隔符，**品名內含 `|` 會打壞明細對齊**，送出前要過濾或替換。
- **信用卡末四碼**：91APP 付款如可取得末四碼可帶 `Visa_Last4`（選填）。

### 作廢/註銷（退款連動）相關

- **退款流程對應**：91APP 退款成功後應連動處理發票——同期別全額退款走「作廢」（`types=Cancel`）；跨期或部分退款走「折讓單」（§11）。
- **作廢 vs 註銷的語意**：「作廢 Cancel」是買賣雙方合意取消交易（一般退款用這個）；「註銷 Void」是發票已上傳大平台後的撤銷程序，需 `VoidReason`。開立 API 的回應 `InvoiceType` 已標明：`B2C2B`（有統編）可接受作廢、`B2B`（BondedAreaConfirm 有值）**無法註銷**。
- **狀態機防呆**：`-2008`（狀態不允許）會多回 `Nowstatus` 可診斷；`-2009` 表示發票已有折讓紀錄，須先作廢折讓單才能動發票——退款服務要按「先折讓單、後發票」的順序清理。
- **StopProcessing 有時窗**：只能在大平台接收前反悔，且限發票；不要把它當可靠的 undo 來設計流程。
- **原因欄位限 20 字**：`CancelReason`/`VoidReason` 超長回 `-2002`/`-2006`，程式端組原因字串（如「訂單 xxx 退款」）要截斷。

### 折讓單相關

- **⚠️ 金額基準不同**：開立發票（B2C）帶**含稅**，折讓單帶**未稅** + 自算 `Tax`。我方定價是含稅價，開折讓要反推：`未稅 = round(含稅 / 1.05)`、`Tax = 含稅 - 未稅`。注意四捨五入後「未稅+Tax」須等於實際退款額，且累計不可超過發票金額（`-10031`）。
- **日期格式不一致**：折讓 `AllowanceDate` 用 `YYYY-MM-DD`（dash），發票 `InvoiceDate` 用 `YYYY/MM/DD`（slash）——別共用同一個 formatter。
- **`AllowanceNumber` 留空讓速買配自動產生**，從回應取回後**必存 DB**（orders/發票紀錄），作廢折讓單（`types=CancelAllowance`）要用它；自填則須自管唯一性（`-10032`）。
- **折讓的 `TaxType` 是每項明細各一**（pipe 分隔），與開立發票的單一 `TaxType` 結構不同，勿共用組參數的程式。

### 列印（發票 PDF）相關

- **🔴 安全：列印 URL 含 `Grvc`+`Verify_key` 商家憑證**，而這組憑證同時能開立/作廢發票。**絕不可**把列印 URL 直接給終端使用者（Email、前端連結、window.open 都不行）——等於把開票權限外洩。正確做法：後端持憑證向 SmilePay 抓取頁面/PDF，經我方**帶登入驗證的 endpoint** 轉發給使用者（比照既有付款收據 PDF 的模式，見 `docs/` 收據相關實作）。
- **參數名不一致**：列印 API 用 `InNumber`（非 `InvoiceNumber`）；`RaNumber` 語意隨發票類型變——B2C 帶開立時回傳的 `RandomNumber`、B2B 帶買受人統編。開立時 `InvoiceNumber`+`RandomNumber` 都要存 DB 才印得出來。
- **網域不同**：列印在 `einvoice.smilepay.net`，資料 API 在 `ssl.smse.com.tw`——若後端出口有 egress 白名單或前端 CSP 要放行，兩個網域都要列。
- **`AutoPrint`/`DetailPrint` 是給收銀情境的**，我們走 PDF 下載/轉發即可，不需帶。

### 沒有查詢 API 的因應

官方 API 只有四支（開立/作廢註銷/折讓/列印），**無發票查詢、無狀態回查、無對帳匯出 API**。因應設計：

- **我方 DB 是唯一可程式化的狀態來源**：每次呼叫的完整回應（`InvoiceNumber`、`RandomNumber`、`InvoiceType`、`AllowanceNumber`、作廢/註銷時間、`Status`/`Desc`）都必須落庫（建議掛在 `orders` 或獨立 `invoices` collection），漏存就只能上速買配後台人工查。
- **冪等靠 `data_id` 而非回查**：網路逾時等不確定結果的情況，無法像 91APP 那樣回查交易——重試時帶同一個 `data_id`，若吃 `-10072`（重複）即代表前次其實已開立成功，但**號碼要上速買配後台撈**（API 拿不回來）。因此開立請求務必設計成「同步等回應、完整落庫後才結束」，盡量避免走到這條路。
- **對帳**：定期用速買配後台人工核對；月結時比對我方 `invoices` 紀錄與後台清單。
