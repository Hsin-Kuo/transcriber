# XSS 風險盤點與修復待辦

> 盤點日期：2026-07-05（三個 read-only agent 分掃 `frontend/`、`admin-frontend/`、`src/`+`deploy/`，主對話彙整）
> 讀者：執行修復的工程師或 AI model。**每個 TODO 都附了檢查步驟與驗收條件，請逐條照做，不要跳過驗證。**

## 0. 總體結論（先讀這段）

**目前沒有發現可直接利用的 XSS 漏洞。** 三個關鍵事實：

1. `frontend/` 與 `admin-frontend/` **全站零 `v-html`、零 `innerHTML` 注入**（唯一的 `innerHTML` 是 `GoogleSignInButton.vue:114` 清空節點的 `= ''`）。所有使用者可控欄位（任務名、檔名、segment 文字、speaker 名、tag、AI summary、email）一律走 Vue `{{ }}` 插值或 `:attr` 綁定，Vue 會自動 HTML-escape。
2. 後端**零 HTML endpoint**（無 `HTMLResponse`／Jinja2／f-string 拼 HTML 回應）；藍新金流 return 走 303 redirect 不產 auto-submit HTML；上傳有副檔名白名單 + magic bytes 驗證。
3. nginx 三個 server block（主站/app/admin）+ staging 都有 CSP、`X-Content-Type-Options: nosniff`、`X-Frame-Options` 等 headers。

因此下列待辦**全部屬於 defense-in-depth（縱深防禦）與「鎖住乾淨現狀」**，不是修活漏洞。優先級依「一旦失守的影響面 × 失守機率」排序。

### 給執行者的通用護欄

- 改動任何一項後，跑該項的「驗收條件」，貼出實際輸出，不要只說「已完成」。
- 涉及 nginx / CSP 的改動：**先改 staging（`deploy/nginx-staging.conf`）驗證，再改 prod（`deploy/nginx-ec2.conf`）**。本專案禁止 SSH 直接改 EC2 上的檔案，一律改 repo 內 `deploy/` 的 canonical 檔並走部署流程（CLAUDE.md 規範）。
- 只改 TODO 範圍內的檔案；發現需要動其他檔案，先停下回報。
- 每個 TODO 一個獨立 branch + PR（repo 只准 merge commit，禁 squash/rebase）。

---

## 1. 常見 XSS 類型 × 本專案對應攻擊面

| 類型 | 說明 | 本專案對應面 | 現況 |
|------|------|------------|------|
| **Stored XSS** | 惡意內容存入 DB，其他人瀏覽時執行 | 任務名、檔名、speaker 名、tag、轉錄文字 → 公開分享頁 `SharedTranscriptView.vue`（未登入觀眾可見，影響面最大）；同批欄位 → admin 後台（打到管理員 = 權限升級） | 前端全插值渲染，無 sink |
| **Reflected XSS** | URL/表單參數未逃逸反射回頁面 | 金流 return（`payment_return`）、OAuth callback | 後端回 303 redirect / JSON，無反射 |
| **DOM-based XSS** | 前端 JS 把可控資料寫進 DOM sink | `innerHTML`、`v-html`、driver.js popover（description 以 HTML 注入）、`location.href` | 唯一 HTML sink 是 driver.js，文案全 static i18n |
| **File-upload XSS** | 上傳 HTML/SVG，以 inline + `text/html` 服務 | S3 presigned URL、本地 `FileResponse` | 上傳驗證嚴格、content-type 恆 `audio/*`，但 presigned 未上保險（TODO-2） |
| **`javascript:` URL** | 動態 `:href`/`window.open` 綁可控值 | 全站連結 | 全為寫死 URL + `rel="noopener noreferrer"` |
| **CSP bypass** | headers 缺失或含 `unsafe-inline` 使 CSP 失效 | nginx CSP | `script-src` 含 `'unsafe-inline'`（app 另有 `'unsafe-eval'`）（TODO-3） |
| **Email HTML injection** | 使用者可控欄位拼進 HTML 信件 | `email_service.py` f-string 樣板 | 目前插值皆伺服器端常數（TODO-7 防未來） |

---

## 2. 待辦清單

### TODO-1【P1】兩個前端加 `vue/no-v-html` ESLint 規則，鎖住「零 sink」現狀 — ✅ 已完成（PR #246）

- **風險**：目前全站零 `v-html` 是最大的安全資產，但沒有任何機制阻止未來的 PR 引入。一旦有人為了渲染 AI summary/markdown 加了 `v-html`，且專案沒有裝任何 sanitizer（兩個 `package.json` 都沒有 DOMPurify），就是即刻的 stored XSS。
- **現況**：`frontend/`、`admin-frontend/` 皆無此 ESLint 規則。
- **修法**：在兩個前端的 ESLint 設定加：
  ```js
  // eslint.config.js（flat config）或 .eslintrc 的 rules 區塊
  rules: {
    'vue/no-v-html': 'error',
  }
  ```
  若專案尚未接 `eslint-plugin-vue`，先確認再裝（看 `package.json` devDependencies；別重複安裝已有的套件）。同時把 lint 加進 CI（若 CI 已跑 lint 就不用動）。
- **檢查步驟**：
  ```bash
  grep -rn "v-html" frontend/src admin-frontend/src        # 應為 0 命中（基線）
  grep -n "no-v-html" frontend/eslint.config.* admin-frontend/eslint.config.* 2>/dev/null
  ```
- **驗收條件**：
  1. 在任一 `.vue` 臨時加一行 `<div v-html="x" />` 跑 lint 必須報 error（驗完移除）。
  2. 兩個前端 `npm run lint`（或對應指令）通過。
- **注意**：不要為了通過 lint 去改任何現有元件——現狀本來就是 0 處，若 lint 報出現有程式碼的 `v-html`，代表盤點後有人加了，停下回報。

### TODO-2【P1】S3 presigned URL 補 `ResponseContentDisposition` / `ResponseContentType` — ✅ 已完成（PR #247）

- **風險**：presigned URL 目前只帶 `Bucket/Key/ExpiresIn`，瀏覽器如何處理檔案完全取決於上傳時寫入的物件 Content-Type。現在安全是因為 `detect_content_type`（`src/utils/storage/backend.py:75-91`）只會回 `audio/*`——這是**單點假設**。未來任何 code path（例如新功能上傳字幕檔、圖片頭像）以非 audio content-type 寫入同 bucket 並被 inline 服務，就變成 stored XSS 載體。
- **現況**：
  - `src/utils/storage/compact.py:74-78` — `get_audio_presigned_url` 未帶 Response* 參數
  - `src/utils/storage/compact.py:174-178` — `get_presigned_url_by_path` 未帶 Response* 參數
  - 呼叫端：`src/routers/transcriptions.py:716-717`、`src/routers/shared.py:283-303`（皆 `RedirectResponse` 到 presigned）
- **修法**：`generate_presigned_url` 的 `Params` 加上：
  ```python
  Params={
      "Bucket": bucket,
      "Key": key,
      "ResponseContentType": "audio/mpeg",          # 或依 key 副檔名對應
      "ResponseContentDisposition": "inline; filename=audio.mp3",
  }
  ```
  注意：這兩個 URL 是給 `<audio :src>` 播放用的，**不能用 `attachment`**（會讓播放器變下載）。`inline` + 強制 `audio/*` Content-Type 已足夠——瀏覽器不會把 `audio/mpeg` 的回應當 HTML 解析。filename 用固定字串，不要拼使用者可控的 custom_name（避免 header injection）。
- **檢查步驟**：先讀兩個函式與所有呼叫端，確認沒有其他 presigned 產生點：
  ```bash
  grep -rn "generate_presigned_url" src/
  ```
- **驗收條件**：
  1. 單元測試或本地實測：產出的 URL query string 含 `response-content-type=audio%2Fmpeg` 與 `response-content-disposition`。
  2. staging 實測：分享頁與任務詳情頁的音檔仍可正常播放（`curl -sI "<presigned-url>" | grep -i content-` 看到覆寫後的 headers）。
- **注意**：presigned URL 的 Response* 參數會參與簽名，改了之後舊測試若有寫死 URL 比對會爆，屬預期。

### TODO-3【P1】收緊 nginx CSP 的 `script-src`（移除 `unsafe-inline` / `unsafe-eval`） — ✅ 已完成（PR #248；staging 實測 unsafe-eval 因 vue-i18n runtime 編譯需求無法移除，已用 hotfix #250 復原，unsafe-inline 改 sha256 hash 成功移除，詳見 memory `project_csp_script_src_hardening`）

- **風險**：CSP 是 XSS 的最後一道防線。`script-src` 含 `'unsafe-inline'` 時，注入的 `<script>` 或 inline event handler 照樣執行，CSP 對 XSS 幾乎無效；`'unsafe-eval'` 再放行 `eval`/`new Function`。前端掃描已確認**程式碼本身無 `eval`/`new Function`/runtime template compiler**（Vite 產出 runtime-only Vue），所以 `unsafe-eval` 很可能是歷史殘留。
- **現況**：
  - `deploy/nginx-ec2.conf:89`（app server）、`deploy/nginx-staging.conf:39` — `script-src` 含 `'unsafe-inline'` 與 `'unsafe-eval'`
  - `deploy/nginx-ec2.conf:244`（admin server）、`deploy/nginx-staging.conf:189-196` — 含 `'unsafe-inline'`
- **修法（分兩步，先易後難）**：
  1. **先移 `unsafe-eval`**（程式碼已證實不用 eval，風險低）。
  2. **再評估移 `unsafe-inline`**：這步較難——需確認 `index.html` 有無 inline `<script>`（Vite 預設 build 無，但 GSI/Sentry 初始化可能有）、Google Sign-In SDK 與 Sentry 的 CSP 需求（GSI 官方文件有 CSP 指引）。做不到全移就先用 `Content-Security-Policy-Report-Only` 並行觀察，蒐集 violation report 再切正式。
- **檢查步驟**：
  ```bash
  grep -rn "unsafe-" deploy/
  grep -rn "<script" frontend/index.html admin-frontend/index.html
  ```
- **驗收條件**：
  1. staging 部署後，登入、Google 登入、上傳、轉錄詳情、金流跳轉、Sentry 回報全部手動走一遍，DevTools console **零 CSP violation**。
  2. `curl -sI https://staging.soundlite.app | grep -i content-security-policy` 確認新值生效。
  3. staging 跑滿一個工作日無異常，才開 prod PR。
- **注意**：**這是本清單風險最高的改動**（改壞 = 全站 JS 掛掉）。務必 staging 先行；`style-src` 的 `unsafe-inline` 可以先留著（Vue 動態 style 常需要，且風險遠低於 script）。一次只動 `script-src`。

### TODO-4【P2】nginx 靜態資源 location 的 `add_header` 蓋掉了 server 層 CSP — ✅ 已完成（PR #252，實際找到 5 處而非只有原文提到的 1 處）

- **風險**：nginx 的 `add_header` 繼承規則是「location 內只要有任何一條 `add_header`，server 層的**全部**丟棄」。靜態資源 location 重貼了 HSTS/nosniff/XFO 等但**漏了 CSP**，該 location 的回應就沒有 CSP。對 `.js/.css` 影響小，但這是 nginx 經典 footgun，順手補齊。
- **現況**：`deploy/nginx-ec2.conf:63-70`（靜態資源 location）。staging 檔需一併檢查同型問題。
- **修法**：在該 location 的 `add_header` 清單補上與 server 層一致的 CSP 行（複製 server 層那行即可）；或把共用 headers 抽成 `include` 檔避免再漂移。
- **檢查步驟**：逐一列出兩個 conf 檔中所有含 `add_header` 的 location block，比對 server 層清單，找出所有「部分重貼」的 block（可能不只這一處）。
- **驗收條件**：staging 部署後 `curl -sI https://staging.soundlite.app/assets/<任一存在的.js> | grep -i content-security` 有值。
- **注意**：只補 headers，不動 proxy/cache 等其他設定。

### TODO-5【P2】`update_speaker_names` 裸 dict 無任何驗證 — ✅ 已完成（PR #254，用 RootModel 維持既有扁平 body 契約，非原文範例假設的包一層 key）

- **風險**：`PUT` speaker names 的 payload 是裸 `dict`，鍵值的長度、型別、數量完全不限，原封不動寫入 DB。目前前端渲染有逃逸所以不是活 XSS，但這是唯一「完全零驗證」的使用者輸入欄位：可塞任意大小 payload（storage 濫用/DoS）、任意內容（依賴下游永遠記得逃逸）。
- **現況**：`src/routers/transcriptions.py:999-1028`（參數型別 `dict`，`:1028` 直接寫入）。對照組：tag 有 Pydantic 長度限制（`src/models/tag.py:31-40`）、custom_name 有 255 上限（`transcriptions.py:196-197`）。
- **修法**：建 Pydantic model 取代裸 dict：
  ```python
  from pydantic import BaseModel, Field

  class SpeakerNamesUpdate(BaseModel):
      speaker_names: dict[str, str] = Field(..., max_length=50)  # 最多 50 位講者

      @field_validator("speaker_names")
      @classmethod
      def validate_entries(cls, v: dict[str, str]) -> dict[str, str]:
          for key, name in v.items():
              if len(key) > 50 or len(name) > 100:
                  raise ValueError("speaker key/name too long")
          return v
  ```
  （鍵格式若有既定慣例——如 `SPEAKER_00`——可加 pattern 驗證；先讀現有資料格式再決定，別憑空收緊到打壞現有資料。）
- **檢查步驟**：先讀 `transcriptions.py:999-1028` 與前端呼叫端（搜 `speaker_names` 的 PUT/PATCH），確認實際 payload 形狀與鍵格式。
- **驗收條件**：
  1. 現有 speaker 改名功能在本地實測正常（改名、存檔、重新整理仍在）。
  2. 超長 payload（name 500 字）回 422。
  3. 相關 pytest 全過。
- **注意**：**不要**做 HTML sanitize/strip（使用者的講者名可以合法含 `<` `>`，例如「王<小>明」；逃逸是輸出端的責任）。只做長度/數量/型別驗證。

### TODO-6【P2】FastAPI 補安全 headers middleware（nginx 被繞過時的第二層） — ✅ 已完成（PR #255；SSE 串流相容性用真實 uvicorn+socket 驗證過，TestClient 對此會有假陽性）

- **風險**：後端本身零安全 header，全押 nginx。生產 SG 已收掉 8000 直連（`src/main.py:100-110` 註解），但本地開發、未來容器化、或 SG 誤開時就裸奔。
- **現況**：`src/main.py` middleware 只有 `RequestIdMiddleware`（:113）與 `CORSMiddleware`（:142）。
- **修法**：加一個輕量 middleware，至少下發：
  ```python
  @app.middleware("http")
  async def security_headers(request: Request, call_next):
      response = await call_next(request)
      response.headers.setdefault("X-Content-Type-Options", "nosniff")
      response.headers.setdefault("X-Frame-Options", "DENY")
      response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
      return response
  ```
  用 `setdefault` 避免與 nginx 層重複時互相衝突（nginx `add_header` 不會去重，但 nginx 在 proxy 模式下是加在自己那層，後端 setdefault 不影響）。**CSP 不要在後端下**（後端只回 JSON，CSP 由前端 host 的 nginx 管）。
- **驗收條件**：`curl -sI http://localhost:8000/docs | grep -iE "x-content-type|x-frame"` 有值；現有測試全過。
- **注意**：SSE endpoint（進度推送）要確認 middleware 不影響 streaming（BaseHTTPMiddleware 與 StreamingResponse 的相容性——若專案 SSE 用 `EventSourceResponse`/`StreamingResponse`，實測一次進度條仍會動）。

### TODO-7【P2】`email_service.py` f-string 插值加 escape 護欄 — ✅ 已完成（PR #256）

- **風險**：信件 HTML 用 f-string 拼接（`src/utils/email_service.py:130` `_render_branded_email`、`:348` `<li>{line}`、`:368` `{admin_email}` 插進 HTML 內文）。目前所有插值都是伺服器端常數或 token，**無活漏洞**；但只要未來有人把任務名/使用者名塞進 `details_lines`，就是 email client 內的 HTML injection。
- **修法**：插值處統一過 `html.escape()`：
  ```python
  import html
  details_html = "".join(f"<li>{html.escape(str(line))}</li>" for line in details_lines)
  ```
  對 `cta_url` 這類 URL 插值改用 `html.escape(url, quote=True)`（屬性值上下文）。
- **檢查步驟**：逐一列出 `email_service.py` 內所有 f-string/`.format` 插進 HTML 的變數，標注來源（常數/token/潛在使用者資料）。
- **驗收條件**：既有寄信測試全過；本地實寄一封驗證信（或 dump HTML）目視版型不變。
- **注意**：escape 後若版型跑掉，代表原本有變數刻意帶 HTML（如 `extra_html`）——那類「本來就是 HTML 的參數」不 escape，但要在函式 docstring 標注「此參數為 raw HTML，呼叫端禁止傳入使用者資料」。

### TODO-8【P2】評估 admin token 從 `localStorage` 改 httpOnly cookie — ✅ 方案 B 已完成並合併（PR #258、#260），2026-07-12

- **風險**：`admin-frontend/utils/api.ts:20-26` 把 access_token 存 `localStorage`——XSS 得手即偷 token。這放大所有其他項目的後果（尤其 admin 是一般使用者資料的觀眾，stored XSS 打 admin = 權限升級）。refresh_token 已是 httpOnly cookie（`frontend/src/stores/auth.js:108` 的註解，admin 端同模式），只有 access_token 暴露。
- **修法方向**（這項是評估 + 提案，不是直接動工）：
  - 方案 A：access_token 只存記憶體（Pinia state），頁面重整用 refresh_token 換新——改動小，先做這個評估。
  - 方案 B：全面改 httpOnly cookie——需處理 CSRF（SameSite + CSRF token），工程大。
  - 使用者前端（`frontend/`）大概率同樣模式，一併盤點。
- **驗收條件**：產出一頁評估文件（現況、兩方案改動面、建議），供決策；不改程式碼。
- **注意**：這是架構層變更，**評估完先回報再動工**，不要直接改。
- **評估結論摘要**：兩前端的 access_token 皆存 `localStorage`；`frontend/` 另外有 `<audio>` 播放器與 SSE 兩處把 token 塞進 URL query string（原生元件不支援自訂 header）。評估文件原本建議「先做方案 A、方案 B 排下一週期」，但實際決策是**跳過方案 A、直接做方案 B**——深挖後發現可行性比預期高（CSRF 風險因同源架構+既有 `SameSite=strict` 先例遠比預期小；後端改動雖是 3 個讀取點而非 1 個，但範圍精確可列舉），且 A、B 是兩種互斥實作而非漸進步驟，做 A 再做 B 等於多繞一趟、A 的程式碼還會被 B 整個取代。
- **實際完成內容**：後端 `get_current_user`/`get_current_user_sse`/`download_audio` 三個讀取點硬切換成只認 httpOnly cookie（比照本 repo 既有的 `refresh_token` 遷移先例，commit `342af34`，不做過渡期雙讀）；兩個前端拿掉 `TokenManager`，SSE/`<audio>` 拿掉 token-in-URL。詳見 `docs/ADMIN_TOKEN_STORAGE_EVALUATION.md`（含深挖查證細節與最終決策的完整推理）、PR #258（向下相容的 cookie 種植階段）、PR #260（硬切換 + 兩輪 code review 修復，原 PR #259 因分支刪除被 GitHub 誤關閉後在 #260 重開)。本地端到端驗證含真實瀏覽器測試（`document.cookie` 證實 httpOnly 生效、真實 `EventSource` 確認 SSE cookie 自動認證）。全專案 pytest 471 個測試全過。

### TODO-9【P3】確認藍新 `gateway_url` 信任邊界（open-redirect，非 XSS）

- **風險**：`frontend/src/stores/auth.js:365-378` 建 form 自動 POST，`form.action = formData.gateway_url` 來自後端 API 回傳。若後端這個值可被任何使用者輸入影響，等於把含 TradeInfo 的付款 form POST 到任意網址。
- **檢查步驟**：讀 `src/utils/newebpay_service.py:156/203/251` 與 `src/routers/subscriptions.py:161`，確認 `gateway_url` 是否為設定檔常數（`NEWEBPAY_*` 環境變數）而非任何請求參數拼出。
- **驗收條件**：回報一句結論 + file:line 證據。若是常數 → 關閉此項；若可被輸入影響 → 升級成 P1 修復（後端白名單 `core.newebpay.com` / `ccore.newebpay.com`）。

### TODO-10【P3】driver.js 導覽文案立護欄（規範，非程式碼）

- **風險**：driver.js 的 popover `description` 以 HTML 注入，是全站唯一真正的 HTML sink（`frontend/src/composables/useProductTour.js:30-52`）。目前三個 view 的 steps 全用 static i18n（`TranscriptionView.vue:571-615`、`TasksView.vue:595-597`、`TranscriptDetailView.vue:640-693`），安全；但沒有任何機制防止未來把使用者資料插進去。
- **修法**：在 `useProductTour.js` 檔頭加註警語（「description 會以 innerHTML 注入，禁止插入任何使用者可控資料；動態值先 escape」）；若 driver.js 版本支援 DOM/函式型 popover 內容，可評估改用。
- **驗收條件**：註解到位；grep 三個 view 確認 steps 仍全為 `$t()`/`t()` 靜態文案。

### TODO-11【P3】建立 XSS 回歸掃描小抄（一次建立，之後 CI 或定期跑）

- **風險**：本次盤點的「零 sink」結論是時間點快照；沒有回歸機制的話，任何一個未來 PR 都可能無聲引入 `v-html`/`innerHTML` 而沒人發現，整份盤點失效。
- **修法**：把下方 grep 收進 repo（本檔即可當小抄；進一步可包成 script 掛 CI），任何大型前端 PR 後跑一輪。
- **驗收條件**：下方五條 grep 在當前 main 分支的輸出符合各行註解的預期（0 命中，或僅 `GoogleSignInButton.vue:114` 一處例外）；兩條 curl 在 staging/prod 都看得到 CSP 與 nosniff headers。

```bash
# 前端 sink（預期全部 0 命中；GoogleSignInButton.vue 的 innerHTML='' 除外）
grep -rn "v-html" frontend/src admin-frontend/src
grep -rnE "innerHTML|outerHTML|insertAdjacentHTML|document\.write" frontend/src admin-frontend/src
grep -rnE "\beval\(|new Function" frontend/src admin-frontend/src

# 後端 HTML 輸出（預期 0 命中）
grep -rnE "HTMLResponse|text/html|Jinja2|TemplateResponse" src/

# sanitizer 依賴變化（若未來出現 v-html，必須同時出現 DOMPurify）
grep -n "dompurify" frontend/package.json admin-frontend/package.json

# 線上 headers 抽查
curl -sI https://staging.soundlite.app | grep -iE "content-security|x-content-type|x-frame"
curl -sI https://soundlite.app | grep -iE "content-security|x-content-type|x-frame"
```

---

## 3. 已檢查、確認無風險的項目（避免重工，修復時不用再碰）

| 項目 | 證據 | 結論 |
|------|------|------|
| 公開分享頁渲染他人資料 | `SharedTranscriptView.vue:31/89/94/102-118/128/141/143` 全 `{{ }}` 插值 | Vue 自動 escape，安全 |
| admin 後台渲染使用者 email/檔名/audit path | `UsersView.vue:94`、`AdminTasksView.vue:135-139`、`AuditLogsView.vue:86-98` 等全插值 | 安全 |
| 量測 div 塞 segment 文字 | `useSegmentMarkers.js:256` 用 `textContent` 賦值（主對話已複核原始碼） | 安全 |
| 檔案下載檔名 | `useTranscriptDownload.js:213-218` 等，檔名只進 `link.download` 屬性與純文字 Blob | 非 XSS 面 |
| 動態 `:href`/`window.open` | 全站皆寫死 URL + `rel="noopener noreferrer"` | 安全 |
| markdown 渲染 | 兩前端皆無 marked/markdown-it；AI summary 走結構化 JSON 插值 | 無此攻擊面 |
| 金流 return 反射 | `subscriptions.py:734-772` 回 303 redirect，NotifyURL 回 JSON | 無反射 XSS |
| OAuth callback | `oauth.py:101-206` 回 JSON | 無反射 XSS |
| 上傳驗證 | `audio_validator.py:45/65` 副檔名白名單 + magic bytes，不信任 client content-type | 嚴格 |
| S3 物件 Content-Type | `backend.py:75-91` `detect_content_type` 只回 `audio/*` | 現況安全（TODO-2 補保險） |
| 音檔合併下載 | `audio.py:362-366` `attachment` + 固定 `audio/mpeg` + path traversal 防護 | 安全 |
| TXT/PDF 匯出 | `transcriptions.py:532-534`（text/plain+attachment）、ReportLab 產 PDF 非 HTML | 無 HTML 產出 |
| CORS | `main.py:118-147` 白名單 + 生產缺設定即拒啟動，無 `*`+credentials | 安全 |
| local FileResponse 音檔 | `transcriptions.py:753-761` content-type 強制 `audio/*` fallback | 安全 |

## 4. 盤點範圍聲明

- 已掃：`frontend/src`、`admin-frontend/src` 全部原始碼；`src/`（FastAPI 全部 routers/services/utils）；`deploy/` nginx conf（prod + staging）。
- 未掃：`dist/` 建置產物、`node_modules/`、線上環境實際 headers（TODO-11 有 curl 指令可補測）、email client 端的渲染行為。
- 本盤點針對 **XSS 及其直接周邊**（headers、檔案服務、open-redirect 信任邊界）；SQLi/NoSQLi、SSRF、auth 邏輯等不在本次範圍。
