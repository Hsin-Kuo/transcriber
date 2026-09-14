# 金流資安體檢 — 上線 Checklist

> 對應體檢報告 `docs/PAYMENT_SECURITY_AUDIT_2026-08-08.md`。程式碼修復已全數合併（PR #322–#331，
> P0×4 + P1×5 + P2×6 共 15 類）。本檔是**程式碼之外**的收尾：secrets seed、資料 migration、
> origin 鎖定、CF 規則、staging 實測。這些是 console / AWS CLI / DB 操作，需人工執行。
>
> **閱讀方式**：每項標了 `[依賴]` 的，前置未完成前不要做。§0 是硬性順序，§5 staging 實測是
> 上 prod 的最後一道 gate。指令裡的 staging/prod 網址、SG、SSM prefix 都已填好，複製即用。
>
> ## 📌 狀態總覽（2026-09-14 更新）
> **金流已於 2026-09-01 go-live**（#356–#358），首筆真實營收 2026-09-02 全鏈路驗證通過
> （訂閱 activated＋自動請款 captureStatus=1＋真發票 FW90881600＋通知信）。上線後演進：
> 三個「sandbox 不驗、正式才炸」hotfix（#359/#362/#365/#367：subscriptionProductInfo、
> 首期金額、cardHolder 電話收集）→ 最終 #383（2026-09-14）**移除訂閱標記改 productType=Normal**
> （帶 spi 會在 91APP 建 gateway 自動扣款排程＝與自管續扣重複扣款；91APP 已改商店設定＋
> 終止首筆排程＋書面確認免 3D 不依賴標記）。
> **未完成**：§5 geo-block 全部、§6 少數殘項（詳各節註記）、⏳ ~10/1 首個真實續扣實戰觀察。

---

## §0 硬性順序（先讀這張圖）

```
1. seed SSM secrets（KEK；金流上線時的 SMILEPAY/PAYMENTS91_ENV）  ── 無前置，先做
2. 部署含修復的碼到 staging → prod                              ── seed KEK（§1a）；缺 KEK 只在 §1b 設 PAYMENTS91_ENV=production 後才 fail-fast
3. origin 鎖定（SG 收斂 CF prefix）                              ── 依賴 2；讓 real_ip 真的拿到真實 IP
4. 跑 card_token migration                                      ── 依賴 2（碼要先含 decrypt 明文相容）
5. 設 INVOICE_GAP_EPOCH env（發票整合全量生效後）               ── 依賴 4 + 發票確認可用
6. CF WAF / Redirect 規則（geo-block）                          ── 依賴 region 頁先上線（SoundLiteMain）
7. staging 真實交易實測（§5）→ 通過才套 prod
```

⚠️ **最容易錯的依賴**：origin 鎖定（3）**必須**在 real_ip conf（PR #329）生效的前提下才有意義——
反過來說，real_ip 信任 `CF-Connecting-IP`，若 origin 還對外開著（SG 沒收斂），任何人可直連
origin 偽造該 header。所以 3 沒做完之前，real_ip 的安全效益是 0（但也不是負——nginx 仍覆寫
X-Real-IP，只是值 = 直連來源）。**staging 先做、驗證通過再碰 prod。**

---

## §1 SSM secrets seed（PR #326 P1-6、#331 P2-10）

### 1a. card_token 加密金鑰（KEK）— PR #331 [無前置，最先做]

**KEK 的 fail-fast 綁在「金流已上線」**：`validate_payment_env()`（startup）在 `PAYMENTS91_ENV=production`
時會呼叫 `_get_kek()`，缺 KEK 直接 `RuntimeError` 擋下啟動；金流尚未上線（PAYMENTS91_ENV 未設）時
KEK 可缺、不擋啟動（此時若有人打 /pay，`encrypt` 失敗會被 F2 的 `_encrypt_card_token_safe` 安全略過，
不會靜默存明文）。因此 **§1b 設 `PAYMENTS91_ENV=production` 之前務必先完成本步 KEK seed**，否則
go-live 那次部署會 fail-fast crash。建議 seed 在部署含 P2-10 的碼之前或同時完成。

```bash
# 產生一把 base64 編碼的 32-byte 金鑰（AES-256）
KEK=$(python3 -c "import base64,os;print(base64.b64encode(os.urandom(32)).decode())")

# prod
aws ssm put-parameter --region ap-northeast-1 --type SecureString \
  --name /transcriber/card-token-kek --value "$KEK"
# staging（獨立一把，別共用）
KEK_STG=$(python3 -c "import base64,os;print(base64.b64encode(os.urandom(32)).decode())")
aws ssm put-parameter --region ap-northeast-1 --type SecureString \
  --name /transcriber-staging/card-token-kek --value "$KEK_STG"
```

- [x] prod KEK seeded（2026-08-23，decode 驗證 32 bytes）
- [x] staging KEK seeded（staging migration 已用它加密 21 筆，實證可用）
- [x] **金鑰已備份到密鑰管理處**（2026-09-01，prod/staging 兩把皆備）

### 1b. 金流環境變數（PR #326 P1-6）— 只在「金流正式對外收款」時做

`deploy/.env.aws` 的 `PAYMENTS91_ENV=production` / `SMILEPAY_ENV=production` 兩行**目前刻意註解著**。
未設時後端 fail-fast 擋下所有金流/開票操作（fail-closed，不會打到測試帳號）。

- [x] 91APP 正式憑證已 seed 到 SSM `/transcriber/91app-*`（4 把，2026-08-31）
- [x] SmilePay 正式憑證已 seed 到 SSM `/transcriber/smilepay-*`（2 把，與 staging 雜湊比對一致）
- [x] 解開 `PAYMENTS91_ENV=production` 註解（#356，2026-09-01 go-live）
- [x] 解開 `SMILEPAY_ENV=production` 註解（#356，與上行同批）
- [x] fail-closed 噪音：已由 #353 sweep lazy-init 根治（空窗期 0 候選即不建 service，不噴）

---

## §2 部署（PR 全部）[依賴 §1a]

- [x] staging 部署最新 main（含 #322–#331；持續隨 promotion 鏈更新）
- [x] staging 後端正常啟動
- [x] prod 部署最新 main（2026-09-01 big-bang #355，115 commits；上線前經完整評估 + fresh-eyes 對抗審）
- [x] prod 後端正常啟動（startup ready、index 全建成、依賴 import 驗證）

---

## §3 origin 鎖定（PR #329/#330 P2-15 前置）[依賴 §2]

目的：SG 只放行 Cloudflare edge，讓 `real_ip` 信任 `CF-Connecting-IP` 有意義（否則可繞過 CF
直連偽造）。完整步驟見 `docs/GEO_BLOCK_CN_PLAN.md §3`，摘要：

### 3a. 建 Cloudflare prefix list（可由 Claude 代跑，需 AWS 憑證）

```bash
aws ec2 create-managed-prefix-list --region ap-northeast-1 \
  --address-family IPv4 --max-entries 20 \
  --prefix-list-name cloudflare-edge-v4 \
  --entries $(curl -s https://www.cloudflare.com/ips-v4 \
      | awk '{printf "Cidr=%s,Description=cf ", $1}')
```

- [x] prefix list 建立：`pl-0c382ca6faf426560`（cloudflare-edge-v4，15 個 IPv4 段，2026-09-01）

### 3b. SG 收斂（危險動作，staging 先做）

SG = `sg-0cbcd8f856d859962`。⚠️ **刪 `0.0.0.0/0` 那一刻**若 CF 段有遺漏 → 全站掛。
（實況更正：原本 prod/staging **共用**此 SG，「staging 先做」不可行 → 先幫 staging 拆出
獨立 SG `sg-05833e9da35681cde`（transcriber-web-staging-sg）再各自收斂。）

- [x] **staging** 拆獨立 SG + 80 只收 CF prefix、22 照舊（2026-09-01）
- [x] staging 驗證：經 CF 200、直連 timeout、SSH 通
- [x] **prod** 收斂（sg-0cbcd8f856d859962：加 CF prefix → 刪 0.0.0.0/0:80 → 刪無用 443，逐步驗證零中斷）
- [x] prod 驗證（my.soundlite.app 200、直連 timeout、admin 200）
- [x] Rollback 一行備妥：`aws ec2 authorize-security-group-ingress --group-id sg-0cbcd8f856d859962 --region ap-northeast-1 --protocol tcp --port 80 --cidr 0.0.0.0/0`

### 3c. 驗 real_ip 生效（origin 鎖定後）

- [x] staging/prod 的 nginx access log 記真實 client IP（realip_probe 實測，兩環境皆驗）
- [ ] （可選）月排程 CF IP drift 偵測 workflow（見 GEO_BLOCK_CN_PLAN §3）——未做

---

## §4 資料 migration / index / env [依賴 §2]

### 4a. card_token 存量加密（PR #331）[依賴 §1a KEK + §2 部署]

**先部署含 decrypt 明文相容的碼**（§2）**再跑**——migration 進行中會新舊混存，讀取端要能同時
處理 `v1:` 密文與 legacy 明文（P2-10 的 decrypt 正是為此設計）。冪等，重跑安全。

```bash
# 帶 prod MONGODB_URL + KEK 執行；會先 print 兩個 collection 的存量 count（dry-run 感）再動手
MONGODB_URL='<prod>' CARD_TOKEN_KEK='<同 SSM 那把 base64>' \
  python -m src.database.migrations.encrypt_existing_card_tokens
```

- [x] staging 跑過（2026-09-01：users 3 筆 + orders 18 筆加密；重跑=0 驗冪等）
- [x] prod 跑（0 筆待加密——prod 從未收款，如預期；migration 即完成）
- [x] 抽驗 `v1:` 格式 + decrypt 還原回原值（staging round-trip 驗證；prod 首筆真實訂閱 token 亦為 v1:）
- [ ] ⏳ 一筆**真實續扣**解密扣款——排 ~10/1 首個續扣週期實戰觀察（含 Normal 標記免 3D 驗證）

### 4b. 驗 invoices partial unique index（PR #328 P2-14）[依賴 §2]

建 index 失敗只 log 不 crash（稅務文件不自動修資料），要人工確認建起來了。

- [x] prod `invoices` index 含 `uniq_active_invoice_per_order`（big-bang 部署後實查確認，2026-09-01）
- [x] N/A：prod invoices 部署前為空，index 乾淨建成，無歷史違規資料

### 4c. 設 INVOICE_GAP_EPOCH（PR #328 P2-13）[依賴 §4a + 發票整合全量生效]

未設時開票補洞 sweep 是 no-op（安全預設，防首次部署 retro 補開歷史單造成重複開真發票）。

- [x] 發票整合全量生效（epoch 設在 go-live 當下，早於首筆真實付款，無歷史漏單問題）
- [x] `INVOICE_GAP_EPOCH=1788274491` 已設（#356，與金流 flip 同批部署）
- [ ] 觀察 gap sweep log `invoice.gap_sweep.completed` 補洞數趨近 0——尚未專門觀察（首筆發票走正常路徑成功，gap sweep 屬補洞備援）

---

## §5 geo-block（PR 之外，CF console + 他 repo）[依賴 region 頁]

完整規則見 `docs/GEO_BLOCK_CN_PLAN.md §1/2/6`。**順序硬依賴：region 說明頁必須先上線，否則
Redirect 規則會 302 到 404。**

- [ ] `SoundLiteMain` repo 加 `/region-unavailable` 頁 → merge 到 `aws` 分支自動部署（GEO_BLOCK_CN_PLAN §5）
- [ ] CF Rule 1（Block API，CN）
- [ ] CF Rule 2（Redirect 非 API 到 region-unavailable）
- [ ] CF Rule 3（admin 反向白名單，只 TW/JP）
- [ ] CF Rule 4（staging 擋 TW，驗證用，**驗完必刪**）
- [ ] 白名單逐條驗（分享頁 /s/、/subscriptions/callback、/health 放行；/tasks 被擋）
- [ ] 觀察 Security Events 命中量，對照註冊數與 GPU 工時確認成本有降

---

## §6 staging 真實交易實測（上 prod 前最後 gate）

本地測試全是 mock / 單機 Mongo；下列行為**只有 staging 真實 91APP sandbox + 真 Mongo 交易**才驗得到。
依 `feedback_test_on_staging`：pipeline 行為驗證一律上 staging 跑真實任務。

### 6a. 併發 / 狀態機（PR #324 P0-1/2/3、#325 P1-9）
- [x] `claim_paid` 真 Mongo 原子語意（staging 併發 8 搶單 → 恰 1 贏，2026-08-23）
- [x] 同 trade 重複 callback → duplicate 擋下（staging 真實 trade 的 processed_webhooks 已登記、re-claim=False）
- [x] `/pay` 立即成交與 `/callback` 收斂同一去重鍵（prod 首筆真實交易兩路徑實戰驗證，settle 恰一次）
- [ ] job_leases lease 跨 worker（需暫調 WEB_CONCURRENCY=2）——未專測；prod 跑 2 workers 至今無雙重執行跡象
- [ ] 使用者端點（cancel/reactivate/change/cancel-plan-change）guard 409 路徑——未專測（低風險殘項）

### 6b. 退款（PR #327 P1-5）
> ⚠️ 2026-08-31 實證：**sandbox 產不出真實 rs6/7**——退款前提=「請款成功(rs5)」而 sandbox
> 到不了 rs5；對「請款已請求」的單後台只給「取消請款」(captureStatus 1→0、rs 仍 4)。
> 收斂程式碼已有完整單元測試覆蓋；**端到端只能在 prod 真請款成功後驗**（排入 prod 首月觀察）。
- [ ] 全額退款 rs=7 → 降 free + 作廢發票 + Sentry——⏳ 待 prod 真請款成功後實測
- [ ] 部分退款 rs=6 → needs_manual——⏳ 同上
- [ ] rs=6→7 時序——⏳ 同上（單元測試已覆蓋閘門邏輯）
- [ ] 退「重複完成單」不誤殺——⏳ 同上（單元測試已覆蓋）
- [x] `GET /v2/trades/{id}` 實際回應形狀（首購3D/加購/取消/請款前後）已實測並回寫 ASSESSMENT §12（captureStatus 0/1 語意、expiryTime=+30min 等）

### 6c. 對帳 / 開票補洞（PR #325 P1-9、#328 P2-13）
- [x] 對帳 sweep 端到端可跑（staging 實跑 `run_reconciliation_sweep`，errored=0；當時無卡住單可收斂，「真實遺失單收斂」屬 prod 觀察項）
- [ ] entitlement_pending 被 resettle 消費——未造測試資料專測（單元測試已覆蓋）
- [ ] gap sweep 對真實漏單補開——尚無漏單可驗（正常路徑開票成功）

### 6d. 綁卡 / card_token（PR #323 P1-8、#331 P2-10）
- [x] 首購 3D 完成後 card_token 有值（staging + **prod 首筆真實訂閱**皆驗，settle 後搬進 subscription、`v1:` 加密）
- [ ] `bindingtoken` fallback 是否為 MIT 可用 token（N3）——未驗（正常路徑 cardToken 都有拿到，fallback 未觸發過）
- [x] 加密 card_token 解密 round-trip 驗證（staging decrypt 還原原值；真實續扣 ⏳ ~10/1）

### 6e. 環境 / IP（PR #326 P1-6、#329/#330 P2-15）
- [x] staging `APP_ENV=staging` 生效（金流 sandbox、startup 未被 fail-fast 誤擋，多次部署實證）
- [x] origin 鎖定後 real_ip = 真實 client IP（兩環境 realip_probe 實測；rate limit key 隨 $remote_addr 同步生效）

---

## §7 電子發票開立上線（SmilePay）

> **前提決策（2026-08-23，owner）**：SmilePay 正式 Verify_key 曾 commit 進 repo（PR#346
> 清工作區、git 歷史仍有）。**owner 已知情並決定「不輪換 key、直接上 prod」，此風險由
> owner 接受**。→ 本節不含「輪換」步驟；後續勿再把此暴露當疏漏重提。殘留風險（repo 歷史/
> clone/CI）壓低靠：repo 維持 private、偶爾巡速買配後台有無非預期作廢/查詢。

- [x] merge PR#346（清 repo 工作區真值 + 改 dummy，2026-08-23）
- [x] SmilePay 憑證 seed 到 SSM（prod 兩把，2026-08-23，與 staging 雜湊比對一致）
- [x] prod 後端 `SENTRY_DSN` 已補（#348）＋ web 端 sentry-sdk 依賴補齊（#362——原只在
  worker requirements，prod web 曾靜默無 SDK）
- [x] 字軌確認：已配發、每期自動延續（速買配確認，2026-08-23）
- [x] staging 真開一張：B2C 載具 / B2C 無載具 / B2B 統編各一 + 全數作廢（DV14188900-902，
  2026-08-23）；response 形狀已回寫 `INVOICE_SMILEPAY_API.md` §8.1（含 InvoiceDate 不補零陷阱）
- [x] prod 切正式：`SMILEPAY_ENV=production` 與 `PAYMENTS91_ENV=production` 同批解註解
  （#356，2026-09-01）
- [x] 頭幾筆真實交易觀察：首筆訂閱（2026-09-02）發票 FW90881600 開出、首購通知信寄達、
  無 needs_manual 堆積。

---

## 附錄：ops 待辦速查（誰做什麼）

| 項 | 負責 | 前置 |
|----|------|------|
| KEK / 金流憑證 seed（§1） | hsin（AWS 憑證） | 無 |
| 部署（§2） | CI/CD（push staging/aws） | §1a |
| prefix list（§3a） | Claude 或 hsin | 無 |
| SG 收斂（§3b） | hsin（危險動作） | §2 |
| card_token migration（§4a） | hsin（帶 prod MONGODB_URL） | §1a + §2 |
| INVOICE_GAP_EPOCH（§4c） | hsin | §4a + 發票生效 |
| geo-block CF 規則（§5） | hsin（CF console）+ Claude（region 頁 PR） | region 頁 |
| staging 實測（§6） | hsin + Claude | §2 |
