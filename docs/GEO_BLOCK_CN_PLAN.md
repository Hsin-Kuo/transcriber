# 地區封鎖（CN）+ origin 鎖定 執行計畫

> 決策日期：2026-07-26。動機＝**濫用／成本防治**（free tier 每月 180 分鐘 GPU + diarization + Gemini，
> 成本綁在「帳號數 × 轉錄分鐘」上）。不是法遵、不是市場策略 —— 所以 VPN 繞過可接受，
> 目標是止血而非滴水不漏。

## 定案摘要

| 項目 | 決定 |
|------|------|
| 封鎖對象 | `my.soundlite.app` 全擋（白名單例外），國碼 `CN` |
| admin | `admin.soundlite.app` 反向白名單，只允許 `TW` / `JP` |
| 分享頁 | 例外放行，用 CF 路徑白名單（不搬 host） |
| 被擋 UX | 302 導到品牌站新頁 `soundlite.app/region-unavailable` |
| origin | SG 80 收斂到 Cloudflare prefix list、刪無用的 443 規則 |
| 附帶修復 | nginx `real_ip` + 後端統一 `get_client_ip`（拆獨立 PR） |
| 驗證 | staging 用「擋 TW」驗規則邏輯，驗完刪除，prod 套同一份改 CN |
| 分工 | 程式碼 PR + prefix list = Claude；SG 切換 + CF 規則 = hsin |

`CN` 不含 `TW`/`HK`/`MO`（ISO 3166-1 獨立國碼）。CN 幾乎不可能有付費用戶
（91APP 金流只做台灣），所以「全擋」的營收代價趨近於零 —— **此結論僅對 CN 成立，
換國家要重新評估**。

---

## 1. 白名單：為什麼是這幾條

分享頁 `/s/:token` 的實際依賴鏈（已逐條追過原始碼）：

| 請求 | 來源 | 是否必須白名單 |
|---|---|---|
| `/s/{token}` → index.html | nginx `try_files` | ✅ |
| `/assets/*.js\|css` | vite chunks | ✅ |
| `GET /shared/{token}` | `frontend/src/views/SharedTranscriptView.vue:189` | ✅ |
| `GET /shared/{token}/audio` | `src/routers/shared.py:251` | ✅ |
| `GET /auth/me` | `frontend/src/router/index.js:148-150` beforeEach 對 public 頁也呼叫 | ❌ **不需要** |

`/auth/me` 不需要白名單，因為 `frontend/src/stores/auth.js:157-160` 的 `catch` 把錯誤吞掉
（`user.value = null`），被擋只會多一行 `console.error`，分享頁照常運作。

**非分享頁但必須白名單的 server-to-server callback**（漏掉會出事）：

| endpoint | 呼叫者 | 漏掉的後果 |
|---|---|---|
| `POST /subscriptions/callback` (`deploy/nginx-ec2.conf:128`) | 91APP 金流 | **使用者付款成功但訂閱沒開通**，靜默失敗 |
| `POST /webhooks/resend` (`deploy/nginx-ec2.conf:140`) | Resend | bounce/complaint 事件遺失 |
| `/health`, `/readiness` | 外部監控 + `deploy-aws.yml:227` smoke test | 誤報、部署驗證失敗 |

第三方機房 IP 的地理歸屬不受我方控制（雲端 IP geo 資料常註冊在意外國家，供應商換機房
不會通知），所以這幾條**與封鎖哪個國家無關，一律無條件放行**。

---

## 2. Cloudflare 規則（hsin 在 console 執行）

Zone `soundlite.app`。prod / staging / admin 同一個 zone，用 `http.host` 區分。

後端 API 前綴的權威清單來自 `deploy/nginx-ec2.conf:216`：
`auth|tasks|transcriptions|tags|audio|summaries|uploads|shared|subscriptions|health|readiness|webhooks`

下列 regex 刻意**只列會擋的那幾個**，把 `shared` / `health` / `readiness` / `webhooks`
排除在外 —— 它們不在 match 清單裡就自動放行，不用寫 `not`。

### Rule 1 — Block API（Security → WAF → Custom rules）

```
(http.host eq "my.soundlite.app"
 and ip.src.country eq "CN"
 and http.request.uri.path matches "^/(auth|tasks|transcriptions|tags|audio|summaries|uploads|subscriptions)"
 and not http.request.uri.path eq "/subscriptions/callback")
```
Action: **Block**

`/subscriptions/callback` 是 `^/subscriptions` 的子路徑，會被 regex 命中，所以要單獨排除。

### Rule 2 — Redirect 頁面（Rules → Redirect Rules → Single Redirects）

```
(http.host eq "my.soundlite.app"
 and ip.src.country eq "CN"
 and not http.request.uri.path matches "^/(auth|tasks|transcriptions|tags|audio|summaries|uploads|subscriptions|shared|webhooks|health|readiness|assets|s/)")
```
Action: **Dynamic redirect → 302 → `https://soundlite.app/region-unavailable`**

**兩條規則的條件是互斥的**（Rule 1 = API 路徑、Rule 2 = 非 API 路徑），這是刻意設計。
若讓兩條同時命中同一請求，WAF custom rules 階段早於 Single Redirects → Block 永遠贏、
redirect 永遠不執行。

regex 檢查：`^/s/` 不會誤配 `/settings`（`s` 後必須緊接 `/`）；`/summaries` 落在 API 清單
被 Block（正確）；`/settings` 不在 API 清單 → Redirect（正確）。

### Rule 3 — admin 反向白名單（Custom rules）

```
(http.host eq "admin.soundlite.app" and not ip.src.country in {"TW" "JP"})
```
Action: **Block**

admin host 上沒有任何 server-to-server callback（`deploy/nginx-ec2.conf:250-314` 只有
`/api` `/auth` 和靜態檔），所以可以無例外全擋。出國時臨時改規則即可。

### Rule 4 — staging 驗證用（**臨時，驗完必刪**）

```
(http.host eq "staging.soundlite.app"
 and ip.src.country eq "TW"
 and http.request.uri.path matches "^/(auth|tasks|transcriptions|tags|audio|summaries|uploads|subscriptions)"
 and not http.request.uri.path eq "/subscriptions/callback")
```
Action: **Block**

額度：CF free plan custom rules = 5 條。穩態用 2 條（Rule 1、3），驗證期間 3 條。
Rule 2 走 Single Redirects，是不同的額度池。

---

## 3. origin 鎖定（Claude 建 prefix list、hsin 切 SG）

現況（`sg-0cbcd8f856d859962` / `transcriber-sg`，實測 `curl -H 'Host: my.soundlite.app'
http://3.112.209.96/` 回 **200**）：

```
80/tcp   ← 0.0.0.0/0    # CF 走這條，但全世界可繞過 CF
443/tcp  ← 0.0.0.0/0    # nginx 沒 listen 443（實測 connection refused）→ 無用規則
22/tcp   ← 0.0.0.0/0    # ⚠️ 見下方「不在本次範圍」
```

web EC2 `i-099bcb529f335d20b` **沒有 IPv6**（`Ipv6Addresses` 為空），所以 CF 的 7 個 IPv6
段不用加，只需 15 個 IPv4 CIDR。

### 建 prefix list（Claude）

```bash
aws ec2 create-managed-prefix-list --region ap-northeast-1 \
  --address-family IPv4 --max-entries 20 \
  --prefix-list-name cloudflare-edge-v4 \
  --entries $(curl -s https://www.cloudflare.com/ips-v4 \
      | awk '{printf "Cidr=%s,Description=cf ", $1}')
```

用 prefix list 而非 15 條散裝 SG 規則的理由：SG 只佔 1 條規則、prod 與 staging 兩台
EC2 共用同一份、修改有 version 可 rollback。

### 切 SG（hsin）

⚠️ **加規則的當下不會有任何行為變化**（`0.0.0.0/0` 還在），風險全部集中在「刪
`0.0.0.0/0`」那一刻。CF 段若有遺漏 → 全站立刻掛。所以 staging 先做。

```bash
PL=pl-xxxxxxxx   # 前一步的輸出
SG=sg-0cbcd8f856d859962

# 1) 先加 CF prefix list
aws ec2 authorize-security-group-ingress --group-id $SG --region ap-northeast-1 \
  --ip-permissions "IpProtocol=tcp,FromPort=80,ToPort=80,PrefixListIds=[{PrefixListId=$PL,Description=cloudflare}]"

# 2) 刪 0.0.0.0/0（危險動作，做完立刻驗）
aws ec2 revoke-security-group-ingress --group-id $SG --region ap-northeast-1 \
  --protocol tcp --port 80 --cidr 0.0.0.0/0

# 3) 刪無用的 443 規則
aws ec2 revoke-security-group-ingress --group-id $SG --region ap-northeast-1 \
  --protocol tcp --port 443 --cidr 0.0.0.0/0
```

驗證（staging 版本，prod 把網址與 IP 換掉）：

```bash
curl -sI https://staging.soundlite.app/health                                  # 經 CF → 要 200
curl -sI --max-time 5 http://52.196.120.189/ -H 'Host: staging.soundlite.app'  # 直連 → 要 timeout
```

Rollback（一行）：

```bash
aws ec2 authorize-security-group-ingress --group-id $SG --region ap-northeast-1 \
  --protocol tcp --port 80 --cidr 0.0.0.0/0
```

### 偵測 CF IP 漂移：自動偵測、人工套用

CF IP 範圍極少變動且會提前公告，不需要自動化維運。加一支月排程 workflow 比對差異、
開 issue 通知即可：

```yaml
- run: |
    diff <(curl -s https://www.cloudflare.com/ips-v4 | sort) \
         <(aws ec2 get-managed-prefix-list-entries --prefix-list-id $PL \
             --query 'Entries[].Cidr' --output text | tr '\t' '\n' | sort) \
      || gh issue create --title "Cloudflare IP 範圍有變動，需 review prefix list"
```

**刻意不做全自動更新**：若 `cloudflare.com/ips-v4` 遭 DNS 劫持或回傳污染內容，全自動流程
會把攻擊者網段加進 origin 白名單。偵測交給機器、放行決定留給人，也符合本 repo
「禁止 SSH 手改、一切走 PR」的紀律。

---

## 4. 附帶修復：真實 client IP（兩個既有漏洞）

這兩個跟 geo-block 是同一個目標（濫用防治），而且比 geo-block 更難繞過 ——
geo-block 換 VPN 就過，這個修好之後濫用者得真的取得不同出口 IP。

### 4a. nginx 沒設 `real_ip` → 所有 rate limit 失準

`deploy/nginx-ec2.conf:11-19` 五個 `limit_req_zone` 全部用 `$binary_remote_addr`，
但在 Cloudflare 後面那是 **CF 邊緣節點 IP**：

- `zone=auth rate=3r/m`：同一 CF 節點後面的所有正常使用者共用 3 次/分鐘 → 誤擋
- 攻擊者換 CF 節點就換一個限流桶 → 防暴力破解形同虛設
- access log（預設 `combined` format）記的全是 `172.68.x.x`，**無法分析濫用來源**

修法：`deploy/nginx-ec2.conf` 與 `deploy/nginx-staging.conf` 最上方（`limit_req_zone` 之前）
加入 15 條 `set_real_ip_from` + `real_ip_header CF-Connecting-IP;` + `real_ip_recursive on;`。
部署前 `nginx -t` 確認有 `ngx_http_realip_module`。

### 4b. 後端把可偽造的 `X-Forwarded-For[0]` 當 client IP

`src/routers/auth.py:161,321,417,489,573,1003`、`src/routers/oauth.py:200`、
`src/utils/audit_logger.py:18-23` 都是 `X-Forwarded-For.split(",")[0]`。

Cloudflare 對 XFF 是 **append 不是覆寫**。攻擊者送 `X-Forwarded-For: 1.2.3.4`
→ 到後端變成 `1.2.3.4, <真實IP>, <CF邊緣IP>` → `[0]` 取到攻擊者自填的值。

後果：
- `register_ip` / login / forgot-password 的 DB 層 rate limit 可用亂數 XFF 無限繞過
- `audit_logs.ip_address` 不可信 —— 諷刺的是最可能偽造它的正是想擋的那群人
- 因此**決定封鎖哪些國家時不能用 audit_logs 當依據**，要用 Cloudflare Analytics
  （CF 在邊緣自己算，不經任何使用者可控 header）

修法：抽一個 `get_client_ip(request)` 單一來源（`audit_logger.py:18` 已有同名 method，
一併合併），改用 `request.client.host`（依賴 4a 的 real_ip 已生效）。
**4a 與 4b 有先後依賴，但拆兩個 PR：4b 動到 auth 路徑，依 CLAUDE.md 要走
`judgment-rubrics.md` §5 高風險驗收流程，不該和基礎建設混在一起 review。**

⚠️ 4a / 4b 都**依賴 origin 已鎖定**。origin 對外開著的話，`CF-Connecting-IP` 一樣可以
直連偽造。

---

## 5. 品牌站說明頁（SoundLiteMain repo）

Repo：`/Users/test/Documents/playground/SoundLiteMain`（`git@github.com:Hsin-Kuo/SoundLiteMain.git`）
Vue 3 + **vite-ssg 預渲染**，部署＝merge 到 **`aws` branch** → GitHub Actions → scp → `/var/www/main`。

- 新增 `src/views/RegionUnavailable.vue`
- `src/router.js` 加 `{ path: '/region-unavailable', name: 'regionUnavailable', component: ... }`
- i18n 只有 `en` / `zh-TW`（`src/locales/`）—— **不新增 `zh-CN`**，繁中對 CN 使用者可讀，
  為單一頁面拉一個 locale 不划算
- 頁面要放 `support@soundlite.app` 讓誤擋的人有申訴管道

SSG 輸出 `/region-unavailable/index.html`，靠 `deploy/nginx-ec2.conf:60` 的 `try_files $uri $uri/`
命中；`absolute_redirect off`（`:35`）確保補斜線的 301 不會把 https 降級成 http。

---

## 6. 執行順序

**順序有硬依賴：說明頁必須先上線，否則 Rule 2 會 302 到 404。**

### Phase 0 — 程式碼（Claude）
1. PR-A `SoundLiteMain`：`/region-unavailable` 說明頁 → merge 到 `aws` 自動部署
2. PR-B `transcriber`：nginx `real_ip`（`nginx-ec2.conf` + `nginx-staging.conf`）
3. PR-C `transcriber`：後端統一 `get_client_ip`（高風險驗收）
4. 建 `cloudflare-edge-v4` managed prefix list

### Phase 1 — staging 驗證（hsin）
5. staging SG 收斂 + 兩條 curl 驗證
6. 上 CF **Rule 4**（擋 TW），逐條驗白名單：
   - `https://staging.soundlite.app/` → 應被 302 導走
   - `https://staging.soundlite.app/s/<token>` → **應正常顯示逐字稿**（含音檔播放）
   - `POST /subscriptions/callback` → 應放行（非 403）
   - `GET /health` → 應 200
   - `GET /tasks` → 應 403
7. 驗證通過 → **刪除 Rule 4**

### Phase 2 — prod（hsin）
8. prod SG 收斂 + 驗證
9. 上 CF Rule 1 / 2 / 3
10. 觀察 Security Events 命中量，對照註冊數與 GPU 工時確認成本有降

---

## 不在本次範圍（已知但刻意不做）

- **SSH 22 對 `0.0.0.0/0` 開放**：三支 workflow（`deploy-aws.yml:114`、`deploy-staging.yml:123`、
  `seed-staging-test-users.yml:56`）都從 GitHub-hosted runner SSH 進去，runner IP 是整段
  動態 Azure 範圍，無法用 SG 收斂。要根治得改走 AWS SSM Session Manager 或 EC2 Instance
  Connect Endpoint，會動到部署流程 → **另案**。
- **admin 上 Cloudflare Access**：free plan 含 50 users，比 IP 白名單正確（不受地點限制）。
  staging 已有 Access 使用經驗。但改登入流程需獨立驗證 → 另案。
- **CN 既有帳號的資料清理**：因為粒度是全擋，CN 既有帳號連不進來就上傳不了新任務，
  每月 180 分鐘消耗自動歸零，不需要另做帳號清理。
