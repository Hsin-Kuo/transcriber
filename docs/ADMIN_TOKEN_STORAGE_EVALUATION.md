# Admin/User Access Token 儲存方式評估（XSS audit TODO-8）

> **狀態：已完成並合併（2026-07-12）。** 本文件下方內文是決策前的評估
> 過程，保留原貌供參考；實際採用的方案與評估當時的建議不同，差異記在
> 這裡：
>
> **最終決策：直接做方案 B，跳過方案 A。** §4「建議」原本寫「先做方案
> A、方案 B 排下一週期」，但 A、B 是兩種互斥的實作（記憶體 state vs.
> httpOnly cookie），不是同一個方向上的漸進步驟——做了 A 之後要再做 B，
> A 的 `TokenManager` 替代程式碼會被整個拿掉重寫，等於白工一趟。深挖
> §3.2 之後也發現方案 B 的可行性比最初評估樂觀（CSRF 風險因同源架構+
> 既有 `refresh_token` 的 `SameSite=strict` 先例遠比預期小；後端改動雖
> 是 3 個讀取點而非 1 個，但範圍精確可列舉），因此改為直接投入方案 B。
>
> **實作結果**：後端 `get_current_user`/`get_current_user_sse`/
> `download_audio` 三個讀取點硬切換成只認 httpOnly cookie（不做過渡期
> 雙讀，比照本 repo 既有的 `refresh_token` 遷移先例 commit `342af34`）；
> 兩個前端拿掉 `TokenManager`，SSE/`<audio>` 拿掉 token-in-URL。詳見
> PR #258（向下相容的 cookie 種植階段）、PR #260（硬切換 + 兩輪 8 角度
> code review 揪出的 7 個修復，含一個真實的 race condition bug）。本地
> 端到端驗證含真實瀏覽器測試（`document.cookie` 證實 httpOnly 真的生
> 效、真實 `EventSource` 確認 SSE 走 cookie 自動認證、admin 帳號 vs 一
> 般帳號的權限邊界也驗證過）。全專案 pytest 471 個測試全過。
>
> ---
>
> 原始狀態（決策前）：**評估文件，尚未動工**。決策後再拆 PR。
> 範圍：`admin-frontend/`（風險較高，權限升級面）與 `frontend/`（同模式，一併盤點）。

## 1. 現況

### 1.1 Token 生命週期（後端，兩前端共用同一套）

- Access token：JWT，15 分鐘效期（`ACCESS_TOKEN_EXPIRE_MINUTES`），透過 `Authorization: Bearer` header 驗證（`src/auth/dependencies.py:9-13` `HTTPBearer`）。
- Refresh token：JWT，30 天效期，**已經是 httpOnly cookie**（`src/auth/cookies.py`）：
  ```python
  response.set_cookie(
      key="refresh_token", httponly=True, secure=not _IS_LOCAL,
      samesite="strict", path="/auth", max_age=30*24*3600,
  )
  ```
  `Path=/auth` 把曝露面縮到最小（只有 refresh/logout 端點會收到這個 cookie）。
- `/auth/login`、`/auth/refresh` 都只在 response body 回 `access_token`；refresh_token 全程不進 JS。

### 1.2 Access token 現況：兩前端都存 `localStorage`

`admin-frontend/src/utils/api.ts:19-28` 與 `frontend/src/utils/api.ts:34-44` 幾乎一模一樣：

```ts
export const TokenManager = {
  getAccessToken: (): string | null => localStorage.getItem('access_token'),
  setAccessToken: (accessToken: string): void => { localStorage.setItem('access_token', accessToken) },
  clearTokens: (): void => {
    localStorage.removeItem('access_token')
    localStorage.removeItem('refresh_token')  // 舊版殘留清理，實際上已經沒在用
  },
}
```

`localStorage` 對任何在該頁面執行的 JS 完全可讀，也**跨分頁、跨頁面重整持久存在**，是 XSS 的標準攻擊目標。目前全站零 `v-html`（TODO-1 已用 ESLint 鎖住），所以「活漏洞」機率低，但這條防線一旦有人繞過（第三方套件、瀏覽器擴充套件、未來的 markdown 渲染需求），access token 是最直接可偷的東西。

**Admin 端風險放大**：admin 是一般使用者資料的觀眾（可看/改任何 user 的 quota、role、狀態），stored XSS 打中 admin session = 直接權限升級到「能操作任何帳號」，後果比一般 user token 被偷嚴重得多。

### 1.3 兩個容易被忽略的呼叫端：`<audio>` 與 SSE 不能用 header

除了 axios 攔截器塞 `Authorization` header 的標準路徑，`frontend/`（admin 沒有這兩個）還有兩處**必須把原始 token 讀出來塞進 URL query string**，因為瀏覽器原生元件不支援自訂 header：

| 呼叫端 | 用途 | 檔案 |
|---|---|---|
| `<audio :src>` | 播放器抓音檔，`?token=<jwt>&t=<timestamp>` | `useAudioPlayer.js:44-49` |
| `EventSource` | SSE 進度推送，`getEventsUrl(taskId, token)` | `TasksView.vue:403-411` |

對應後端也有專門走 query param 驗證的 dependency：`get_current_user_sse`（`src/auth/dependencies.py:51-83`，doc string 明講「EventSource API 不支持自定義 headers」）。

**這點對兩個方案的影響方向不同**：方案 A 不影響這兩處（token 還是 JS 可讀的字串，只是換個地方放）；方案 B 反而能**順便把 token-in-URL 這個做法整個拿掉**（URL 裡帶 token 有自己的風險——會進 server access log、瀏覽器歷史、Referer header），因為 httpOnly cookie 會被瀏覽器對這些原生請求自動夾帶，不需要 JS 讀出來拼 URL。細節見 §3。

## 2. 方案 A：Access token 只存記憶體（Pinia state）

### 2.1 做法

`TokenManager` 的 `getAccessToken`/`setAccessToken`/`clearTokens` 改成讀寫一個模組層級變數（或 Pinia store 的 state），不碰 `localStorage`。頁面重整後記憶體清空，靠 `initialize()` 打一次 `/auth/refresh`（httpOnly refresh cookie 還在，會自動換到新 access token）補回來。

### 2.2 改動面

- **後端：完全不用動**——`Authorization: Bearer` header 這條路徑不變，`get_current_user`/`get_current_user_sse` 都不受影響。
- **前端**：兩邊 `TokenManager` 各改一個檔案（`admin-frontend/src/utils/api.ts`、`frontend/src/utils/api.ts`），把 3 個函式的實作換掉。呼叫端（`stores/auth.js`、`useAudioPlayer.js`、`TasksView.vue`）完全不用改——它們都是透過 `TokenManager.getAccessToken()`/`setAccessToken()` 間接存取，這層抽象已經把儲存細節封裝好了。
- **需要新增的行為**：目前 `router/index.js` 的路由守衛靠 `localStorage.getItem('access_token')` 判斷「要不要跑 `initialize()`」（`admin-frontend/src/router/index.js:87`、`frontend/` 應該同模式）。記憶體方案下這個檢查沒有意義（每次重整記憶體必空），改成「只要 `authStore.user` 是 null 就無條件嘗試 `initialize()`（打一次 `/auth/refresh`，靠 httpOnly cookie 判斷是否已登入）」。這是本方案唯一需要動邏輯（而非搬儲存位置）的地方。
- **多分頁行為變化**：目前 `localStorage` 天然跨分頁共享 token；改記憶體後，開新分頁需要各自向 `/auth/refresh` 換一次 token（多一次 API call，但 refresh cookie 本來就跨分頁共享，使用者無感、不需要重新登入）。

### 2.3 這個方案實際解決了什麼、沒解決什麼

- ✅ 解決：token 不再是**跨分頁、跨頁面重整持久存在**的明文——瀏覽器擴充套件掃 `localStorage`、裝置端事後鑑識（如筆電遺失後被人翻 profile 目錄）、非執行期的儲存讀取類攻擊都拿不到。
- ❌ 沒解決：如果 XSS payload 是**當下正在該頁面執行**的 active code（不管是 stored 還是 reflected），它跟讀 `localStorage` 一樣可以直接讀記憶體裡的 Pinia state 並回傳給攻擊者——active-XSS 竊取 token 這個核心風險本方案不處理。真正能擋這一類的只有方案 B（token 完全不進 JS runtime）。

這個落差要跟決策者講清楚：方案 A 是「降低曝露面」，不是「解決 XSS 偷 token」。

## 3. 方案 B：Access token 全面改 httpOnly cookie

### 3.1 做法

比照現有 `refresh_token` 的模式，登入/refresh 時後端把 access token 也用 `set_cookie(httponly=True, samesite="strict", secure=..., path="/")` 寫入，response body 不再回傳 `access_token` 明文。前端請求不再手動加 `Authorization` header，靠瀏覽器自動夾帶 cookie（`withCredentials: true` 兩邊 axios 實例都已經設了）。

### 3.2 改動面

**後端：實際是 3 個讀取點，不是 1 個——但範圍精確可控**（第一版評估說「單一 dependency」不夠精確，深挖後訂正）：

| 位置 | 現況 | 需要的改動 |
|---|---|---|
| `get_current_user`（`src/auth/dependencies.py:12-48`） | 唯一依賴 `HTTPBearer` 讀 header | 改成從 cookie 讀（或兩者都接受，過渡期用）。**FastAPI 全站 81 個端點透過 `Depends(get_current_user)`（61 處）/`Depends(get_current_admin)`（20 處，後者本身依賴前者）間接注入**，全部走同一個函式，改一處即全站生效，不用逐一改 router |
| `get_current_user_sse`（同檔 :51-83） | 從 query param 讀 token，只有 `tasks.py:306` 這 1 個 SSE 端點在用 | 拿掉 `token: str = Query(...)`，改直接讀 cookie——**同時把 token-in-URL 這個既有做法也一起移除**（附帶安全改善：token 不再出現在 SSE 請求的 URL、不會被 server access log / Referer 記錄） |
| `download_audio`（`transcriptions.py:642-681`） | **沒有共用上面兩個函式，自己寫了一份雙模式驗證**（`HTTPBearer(auto_error=False)` header 優先，query token 其次） | 同樣改成讀 cookie；這是唯一一處需要**單獨**改的認證邏輯，因為它沒有走共用 dependency |

加上簽發端：`/auth/login`、`/auth/refresh`（`src/routers/auth.py:542-666`, `708-714`）、`/auth/google`（`oauth.py:189-206`）三處要新增 `set_access_cookie(response, access_token)`（仿造 `set_refresh_cookie`）；`logout` 端點要新增對應的清除呼叫。**總計 7 個具體程式碼位置**，每一處都能列出檔名行號，不是模糊的「牽一髮動全身」。

**前端**：
- `TokenManager` 整組拿掉（不再需要 JS 保管 access token），`api.ts` 的 request 攔截器不用再手動加 `Authorization` header——**程式碼反而變簡單**。
- `useAudioPlayer.js`（`frontend/`）：`getAudioUrl()` 不再需要 `?token=` 查詢參數，`<audio>` 請求本來就會自動帶 cookie。
- `TasksView.vue` 的 SSE：`getEventsUrl(taskId, token)` 同樣可以拿掉 token 參數。
- `ensureFreshAccessToken()`（`frontend/src/utils/api.ts:173-184`，大檔上傳分片前的主動 refresh 判斷）：目前靠**解析 JWT payload 的 `exp`** 判斷要不要提前 refresh（`decodeJwtExpMs`，`atob` 解 base64）。httpOnly cookie 下 JS 完全讀不到 token 內容，這個機制會失效，需要換一種方式知道「還剩多久過期」——選項：
  - (a) 後端在 `/auth/login`、`/auth/refresh` 的 response body 額外回一個 `expires_at`（Unix timestamp，不是 token 本身），前端存這個時間戳（這個值不是密鑰，明文存放 localStorage/記憶體都無妨）。
  - (b) 乾脆固定每 N 分鐘（略短於 15 分鐘效期）主動 refresh 一次，不用算精確剩餘時間。
  這是方案 B 除了認證流程本身之外，**唯一需要新設計（不是照抄 refresh_token 現成模式）的地方**。

**深挖後排除的疑慮**——追問「方案 B 各方面是否真的可行」後逐一查證：

- **前端沒有其他隱藏繞道**：全專案 grep `Authorization`/`fetch(`/`XMLHttpRequest`，除了 axios 攔截器本身跟上面已知的 audio/SSE 兩處，**沒有任何地方手動組 header 或繞過 axios 實例**。PDF/TXT 匯出走 `api.post()` 拿 blob 後 `URL.createObjectURL()`（本地 blob URL），不是 token-in-URL 模式，不受影響。Google OAuth 走 GSI JS SDK + `POST /auth/google`（不是整頁重導向），不會撞到 `SameSite=Strict` 對「跨站頂層導覽」的限制。`scripts/`、`tests/` 全部搜過，沒有任何自動化腳本或第三方 API 消費者依賴 JSON body 裡的 `access_token`。
- **Cookie 跨網域機制已被 `refresh_token` 驗證過，零新風險**：local dev 的 `CORS_ORIGINS`（`localhost:3000`/`5173`）跟 API 的 `:8000` 是不同 port 但同一個「site」（cookie 判斷不看 port），現有 `refresh_token` cookie 已在這個配置下正常運作；staging/prod 三個網域都是 nginx 同源反代；沒設 `Domain=` attribute，每個子網域各自獨立管理 cookie，跟現況一致——這些都是「借用已驗證過的既有機制」，不是新的未知數。
- **CSRF 的邊界案例：金流 return**——NewebPay 用 top-level 導覽把使用者導回 `my.soundlite.app/payment/return`，是唯一「跨站導覽回來」的流程。但這是 SPA：回來後那次頁面載入本身只是抓 HTML/JS shell，真正的授權 API call 是頁面載入完成後由 JS 發起的**同站**請求（此時 top frame 已經是 `my.soundlite.app`），`SameSite=Strict` 不會擋這類後續請求。這個場景現在就已經在 `refresh_token` 上跑著，方案 B 不會引入新問題。
- **測試套件遷移成本趨近於零**：全專案搜不到任何測試用真實 `Authorization: Bearer <token>` header 打 TestClient/HTTP 端點——幾乎所有認證相關測試都直接呼叫 router 函式、把 `current_user` dict 當參數注入（繞過 HTTP 層的 token 解析，見 `tests/routers/test_batch_gating.py`、`tests/routers/test_speaker_names_update.py` 的既有手法）。換掉 token 解析機制不會讓既有測試大量掛掉。
- **Worker/SQS 認證完全獨立**：`WORKER_SECRET` + HMAC-SHA256（`src/worker_core/sqs_consumer.py`），跟 user JWT 系統零重疊，方案 B 不影響背景任務派工。

### 3.3 這個方案解決了什麼

- ✅ **這是唯一能真正擋掉 active-XSS 偷 access token 的方案**——httpOnly cookie 對任何 JS（不管是不是惡意）都不可讀，`document.cookie` 看不到、`fetch`/`XMLHttpRequest` 也讀不到值本身。
- ✅ 附帶簡化：拿掉 token-in-URL 這個既有的曝露面（SSE、audio player），程式碼量反而減少（前端不用管 header 注入）。
- ⚠️ 曝露面「必然」比 `refresh_token` 大一點：`refresh_token` 用 `Path=/auth` 把自己縮到最小曝露面，但 `access_token` 天生要對每個 API 呼叫可用，只能設 `Path=/`。這不是「方案 B 帶來的新風險」——不管 access_token 存 `localStorage`、記憶體、還是 cookie，它本來就得對每個 API 呼叫可用；用 cookie 只是換個「誰負責夾帶」的角色（瀏覽器 vs JS），`httpOnly` 已經排除「JS 讀取」這個維度、`SameSite=Strict` 已經排除「跨站請求」這個維度，實際風險面沒有變大。
- ⚠️ 剩下真正的新增風險面是 CSRF，但如上所述（含金流 return 邊界案例查證），這個架構的同源特性讓 `SameSite=strict` 幾乎打平這個風險，不需要重工程（額外的 `Origin`/`Referer` header 白名單檢查已有 `CORS_ORIGINS` 可重用，屬 defense-in-depth，不是必要投資）。

## 4. 建議

**先做方案 A，把方案 B 排進下一個週期，不是「二選一」而是「先後順序」：**（2026-07-11 追加深挖後：方案 B 比第一版評估想像的更可行，但排序建議不變——原因見下）

1. **方案 A 立即做**：改動面小（前端 2 個檔案的儲存實作 + 1 個路由守衛判斷邏輯），後端零改動，沒有 CSRF 這類需要仔細驗證的新風險面，一天內可以完成並上線。它不能擋 active-XSS，但确实排除了「token 被動躺在 localStorage 被非執行期手段偷走」這個現實存在、方案 B 也不會額外處理得更好的風險（方案 B 換成 cookie 後，一樣要考慮瀏覽器/裝置層級的其他讀取手段，只是 cookie 天生比 localStorage 少一種「JS 可讀」的曝險）。
2. **方案 B 列為下一個週期的架構任務**，深挖後的具體理由（§3.2 已逐一查證，不是空泛樂觀）：
   - 後端改動範圍精確可控且可窮舉：3 個讀取點（`get_current_user`、`get_current_user_sse`、`download_audio` 的 inline 驗證）+ 3 個簽發點（`login`/`refresh`/`google`）+ 1 個清除點（`logout`），共 7 個具體位置，都能列出檔名行號。
   - CSRF 疑慮比典型「SPA + 獨立 API 網域」場景小很多：三網域同源反代、`SameSite=strict` 已有 `refresh_token` 這個生產先例、金流 return 的跨站導覽邊界案例也查證過不會有問題（SPA 架構下真正的 API call 是導覽完成後才發起的同站請求）。
   - 前端沒有隱藏的複雜度：全專案 grep 過 `Authorization`/`fetch`/`XMLHttpRequest`，除了已知的 audio/SSE 兩處，沒有其他繞道；PDF 匯出、Google OAuth 都不受影響。
   - 測試套件遷移成本趨近於零：既有測試幾乎都繞過 HTTP 層直接注入 `current_user`，不依賴真實 `Authorization` header。
   - 唯一需要重新設計的是 `ensureFreshAccessToken` 的到期時間判斷（改讀後端回傳的 `expires_at` 而非解析 JWT payload），工程量可控且已有明確做法。
   - 這是全清單裡**唯一能真正防禦「active XSS 竊取 token」**的方案——如果之後真的要對 stored XSS 做到「就算中了也偷不到 token」的等級，只有這條路。
   - **儘管可行性比預期高，仍建議排在方案 A 之後**，理由是流程風險而非架構風險：需要在 staging 仔細走一次 SSE、audio 播放器、金流 return 三個邊界情境（跟 TODO-3 CSP 那次「本地驗證方法跟真實環境不一致」的教訓一樣，這類「牽動全站認證」的改動經不起省略 staging 驗證），值得獨立排一個週期專心做，不跟其他修復擠在一起趕。

**不建議的組合**：只做方案 A 就永久停在那——要對決策者說清楚方案 A 是暫時性的曝險降低，不是終局方案，避免「做了方案 A 就當作 TODO-8 完全解決」的誤解。

---

*本文件為評估產出，未改動任何程式碼。決策後請回報要採用哪個方案（或兩者都做／都不做），再另開 PR 動工。*
