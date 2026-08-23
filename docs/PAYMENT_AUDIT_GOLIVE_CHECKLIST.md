# 金流資安體檢 — 上線 Checklist

> 對應體檢報告 `docs/PAYMENT_SECURITY_AUDIT_2026-08-08.md`。程式碼修復已全數合併（PR #322–#331，
> P0×4 + P1×5 + P2×6 共 15 類）。本檔是**程式碼之外**的收尾：secrets seed、資料 migration、
> origin 鎖定、CF 規則、staging 實測。這些是 console / AWS CLI / DB 操作，需人工執行。
>
> **閱讀方式**：每項標了 `[依賴]` 的，前置未完成前不要做。§0 是硬性順序，§5 staging 實測是
> 上 prod 的最後一道 gate。指令裡的 staging/prod 網址、SG、SSM prefix 都已填好，複製即用。

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

- [ ] prod KEK seeded（`aws ssm get-parameter --name /transcriber/card-token-kek --with-decryption` 能取回）
- [ ] staging KEK seeded
- [ ] **金鑰本身另外備份到密鑰管理處**（遺失 = 所有已加密 card_token 永久無法解密 = 全部使用者要重新綁卡）

### 1b. 金流環境變數（PR #326 P1-6）— 只在「金流正式對外收款」時做

`deploy/.env.aws` 的 `PAYMENTS91_ENV=production` / `SMILEPAY_ENV=production` 兩行**目前刻意註解著**。
未設時後端 fail-fast 擋下所有金流/開票操作（fail-closed，不會打到測試帳號）。

- [ ] 91APP 正式憑證已 seed 到 SSM `/transcriber/91app-*`（4 把）
- [ ] SmilePay 正式憑證已 seed 到 SSM `/transcriber/smilepay-*`（2 把）
- [ ] 解開 `deploy/.env.aws` 的 `PAYMENTS91_ENV=production` 註解（走 PR 部署，**禁 SSH 手改**）
- [ ] 解開 `SMILEPAY_ENV=production` 註解
- [ ] ⚠️ seed 完成前，prod 的 invoice retry sweep 會定期噴 `required parameter ... unavailable` 錯誤 log——這是**預期的 fail-closed 噪音**，seed + 解註解後消失

---

## §2 部署（PR 全部）[依賴 §1a]

- [ ] staging 部署最新 main（含 #322–#331）
- [ ] staging 後端正常啟動（staging 是 APP_ENV=staging → is_prod_aws() 為 False → validate_payment_env 不檢查 KEK；KEK fail-fast 只在 prod 觸發。staging 金流走 sandbox/test）
- [ ] prod 部署最新 main（若 prod 已設 PAYMENTS91_ENV=production 則 KEK 必須先 seed，否則 fail-fast crash）
- [ ] prod 後端正常啟動

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

- [ ] prefix list 建立，記下 `pl-xxxxxxxx`

### 3b. SG 收斂（危險動作，staging 先做）

SG = `sg-0cbcd8f856d859962`。⚠️ **刪 `0.0.0.0/0` 那一刻**若 CF 段有遺漏 → 全站掛。

- [ ] **staging** 先加 CF prefix list（port 80）→ 刪 `0.0.0.0/0` → 刪無用的 443 規則
- [ ] staging 驗證：
  ```bash
  curl -sI https://staging.soundlite.app/health                                  # 經 CF → 200
  curl -sI --max-time 5 http://52.196.120.189/ -H 'Host: staging.soundlite.app'  # 直連 → timeout
  ```
- [ ] staging 驗證通過後，**prod** 同樣收斂（`3.112.209.96`）
- [ ] prod 驗證（同上，網址換 my.soundlite.app）
- [ ] Rollback 一行備妥：`aws ec2 authorize-security-group-ingress --group-id sg-0cbcd8f856d859962 --region ap-northeast-1 --protocol tcp --port 80 --cidr 0.0.0.0/0`

### 3c. 驗 real_ip 生效（origin 鎖定後）

- [ ] staging/prod 的 nginx access log 的 client IP 不再是 CF edge（`172.68.x.x`），而是真實來源
- [ ] （可選）月排程 CF IP drift 偵測 workflow（見 GEO_BLOCK_CN_PLAN §3）

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

- [ ] 先在 staging 跑一次（估規模 + 驗流程）
- [ ] prod 跑：確認開頭印出的 count 合理，結尾處理數對得上
- [ ] 抽驗：prod DB 隨機幾筆 `users.subscription.card_token` / `orders.card_token` 都是 `v1:` 開頭
- [ ] 抽驗：一筆真實續扣（或 staging sandbox）能正常解密扣款

### 4b. 驗 invoices partial unique index（PR #328 P2-14）[依賴 §2]

建 index 失敗只 log 不 crash（稅務文件不自動修資料），要人工確認建起來了。

- [ ] `db.invoices.getIndexes()` 含 `uniq_active_invoice_per_order`（partial: status ∈ issued/pending/failed）
- [ ] 若沒建起來：查是否有歷史違規資料（同 order 多顆活躍發票），人工清理後重啟

### 4c. 設 INVOICE_GAP_EPOCH（PR #328 P2-13）[依賴 §4a + 發票整合全量生效]

未設時開票補洞 sweep 是 no-op（安全預設，防首次部署 retro 補開歷史單造成重複開真發票）。

- [ ] 確認發票整合已全量生效（不再有大量未開票的歷史 paid 單）
- [ ] `deploy/.env.aws` 設 `INVOICE_GAP_EPOCH=<當下 unix 時間戳>`（走 PR 部署）
- [ ] 部署後觀察 gap sweep log：`invoice.gap_sweep.completed`，補洞數應趨近 0

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
- [ ] `claim_paid` / dotted `$set` / `matched_count` 在真 Mongo 的原子語意（本地全 mock）
- [ ] 同一 trade 的 recordStatus 4→5 兩封 callback → 第二封 duplicate，不重複結算
- [ ] `/pay` 立即成交與 `/callback` 同 trade 收斂到同一去重鍵
- [ ] job_leases lease 跨 worker（staging `WEB_CONCURRENCY=1`，需暫調 2 才測得到雙 worker）
- [ ] 使用者端點（cancel/reactivate/change/cancel-plan-change）guard 409 路徑

### 6b. 退款（PR #327 P1-5）
- [ ] 全額退款 rs=7 → 訂閱即時降 free + 發票自動作廢 + Sentry
- [ ] 部分退款 rs=6 → needs_manual + 告警，不動權益
- [ ] rs=6→7 時序 → 全額退款照樣 revoke（不被部分退款的閘門擋掉）
- [ ] 退「重複完成單」→ 不誤殺正常訂閱（H1 回歸）
- [ ] `GET /v2/trades/{id}` 四種交易（首購3D/續扣/加購/換卡）的實際回應形狀 → 回寫 ASSESSMENT §12

### 6c. 對帳 / 開票補洞（PR #325 P1-9、#328 P2-13）
- [ ] callback 遺失的 pending/expired 單被對帳 sweep 主動回查收斂 + Sentry
- [ ] entitlement_pending 旗標被 resettle 消費補施權益
- [ ] （設 EPOCH 後）開票補洞 sweep 對真實漏單補開

### 6d. 綁卡 / card_token（PR #323 P1-8、#331 P2-10）
- [ ] 首購 3D 完成後 order.card_token 有值（用成功測試卡 `4503 0749 6961 8452`）
- [ ] `bindingtoken` fallback 是否為 MIT 可用 token（N3，回寫 ASSESSMENT §12）
- [ ] 加密後的 card_token 能正常解密續扣（4a 已涵蓋）

### 6e. 環境 / IP（PR #326 P1-6、#329/#330 P2-15）
- [ ] staging `APP_ENV=staging` 確實生效（金流走 sandbox/test，未被 P1-6 fail-fast 誤擋）
- [ ] origin 鎖定後 rate limit 的 key 是真實 client IP（per-source 非 per-CF-edge）

---

## §7 電子發票開立上線（SmilePay）

> **前提決策（2026-08-23，owner）**：SmilePay 正式 Verify_key 曾 commit 進 repo（PR#346
> 清工作區、git 歷史仍有）。**owner 已知情並決定「不輪換 key、直接上 prod」，此風險由
> owner 接受**。→ 本節不含「輪換」步驟；後續勿再把此暴露當疏漏重提。殘留風險（repo 歷史/
> clone/CI）壓低靠：repo 維持 private、偶爾巡速買配後台有無非預期作廢/查詢。

- [ ] **先 merge PR#346**（清 repo 工作區真值 + 改 dummy）——與是否輪換無關，純止血未來 commit。
- [ ] **seed SmilePay 憑證到 SSM**（值從速買配後台取，貼進終端機執行，勿寫回 repo）：
  ```bash
  aws ssm put-parameter --region ap-northeast-1 --type SecureString \
    --name /transcriber/smilepay-grvc        --value '<Grvc>'
  aws ssm put-parameter --region ap-northeast-1 --type SecureString \
    --name /transcriber/smilepay-verify-key  --value '<Verify_key>'
  # staging 同一組（測試/正式共用，只差 endpoint）：/transcriber-staging/smilepay-*
  ```
- [ ] **補 prod 後端 `SENTRY_DSN`**（目前沒開，見 §附錄/prod_findings）——開票失敗
  （needs_manual / 跨期 / deadline / read-timeout 結果不明）全走 Sentry，沒開就靜默。
  這比輪不輪換更影響「開票出錯你看不看得到」。
- [ ] **跟速買配確認字軌**已配發（正式帳號每期別的字軌是自動管理還是需申請）。
- [ ] **staging 先真開一張**：staging 設 `SMILEPAY_ENV=production`（打 `/api/` 正式端點）+
  上面 seed 的憑證，開 B2C 載具 / B2C 無載具 / B2B 統編 / 作廢各一，確認都開得出、
  歸到本商家、發票入財政部；dump 開票 response 回寫 `INVOICE_SMILEPAY_API.md`。
- [ ] **prod 切正式**：解 `deploy/.env.aws` 的 `SMILEPAY_ENV=production`——⚠️ **必須和
  `PAYMENTS91_ENV=production` 一起切**（否則對 sandbox 付款開真發票）。走 PR 部署，禁 SSH 手改。
- [ ] 切完觀察頭幾筆真實交易：發票有開出、通知信（#337/#338）有寄、無 needs_manual 堆積。

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
