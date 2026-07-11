# Admin/User Access Token 儲存方式評估（XSS audit TODO-8）

> 狀態：**評估文件，尚未動工**。決策後再拆 PR。
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

**後端（集中、非分散——這是好消息）**：
- `get_current_user`（`src/auth/dependencies.py:12-48`）目前唯一依賴 `HTTPBearer` 讀 header，要改成從 cookie 讀 token（或兩者都接受，過渡期用）。這是**單一 dependency**，FastAPI 全站的認證端點都透過它注入，改一處即全站生效，不用逐一改 router。
- `get_current_user_sse`（同檔 :51-83）可以整個簡化：拿掉 `token: str = Query(...)`，改成直接讀 cookie——**同時把 token-in-URL 這個既有做法也一起移除**（附帶的安全改善：token 不再出現在 SSE 請求的 URL、不會被 server access log / Referer 記錄）。
- `/auth/login`、`/auth/refresh` 兩個端點（`src/routers/auth.py:542-666`, `708-714`）：新增一行 `set_access_cookie(response, access_token)`（仿造 `set_refresh_cookie` 寫一個對應函式），並評估 `TokenResponse` 是否還要在 body 回傳 `access_token`（為了 backward compat 或除錯可以先兩者並存一段時間）。
- `logout` 端點：cookie 清除要新增 access_token 那條（比照 `clear_refresh_cookie`）。

**前端**：
- `TokenManager` 整組拿掉（不再需要 JS 保管 access token），`api.ts` 的 request 攔截器不用再手動加 `Authorization` header——**程式碼反而變簡單**。
- `useAudioPlayer.js`（`frontend/`）：`getAudioUrl()` 不再需要 `?token=` 查詢參數，`<audio>` 請求本來就會自動帶 cookie。
- `TasksView.vue` 的 SSE：`getEventsUrl(taskId, token)` 同樣可以拿掉 token 參數。
- `ensureFreshAccessToken()`（`frontend/src/utils/api.ts:173-184`，大檔上傳分片前的主動 refresh 判斷）：目前靠**解析 JWT payload 的 `exp`** 判斷要不要提前 refresh（`decodeJwtExpMs`，`atob` 解 base64）。httpOnly cookie 下 JS 完全讀不到 token 內容，這個機制會失效，需要換一種方式知道「還剩多久過期」——選項：
  - (a) 後端在 `/auth/login`、`/auth/refresh` 的 response body 額外回一個 `expires_at`（Unix timestamp，不是 token 本身），前端存這個時間戳（這個值不是密鑰，明文存放 localStorage/記憶體都無妨）。
  - (b) 乾脆固定每 N 分鐘（略短於 15 分鐘效期）主動 refresh 一次，不用算精確剩餘時間。
  這是方案 B 除了認證流程本身之外，**唯一需要新設計（不是照抄 refresh_token 現成模式）的地方**。

**CSRF**：
- refresh_token 現有的 `SameSite=strict` 已經證明這個架構下可行——三個網域（`my.soundlite.app`、`admin.soundlite.app`、後端 API）都是**同源反代**（nginx 把 `/auth`、`/api` 等路徑代理到同一台機器的 127.0.0.1:8000，見 `deploy/nginx-ec2.conf`），沒有真正跨站的合法使用情境，`SameSite=strict` 不會誤傷任何現有流程。
- `SameSite=strict` 本身就會**擋掉幾乎所有經典 CSRF**（cookie 不會被夾帶到任何跨站請求，包含 top-level navigation），比 TODO 原文預期的「需要處理 CSRF（SameSite + CSRF token）」風險小很多——這不是「不用管 CSRF」，但額外的 CSRF token round-trip機制大概率不是必要投資，用 `Origin`/`Referer` header 白名單檢查（配置已有的 `CORS_ORIGINS`）作 defense-in-depth 即可，工程量遠小於完整 CSRF token 方案。

### 3.3 這個方案解決了什麼

- ✅ **這是唯一能真正擋掉 active-XSS 偷 access token 的方案**——httpOnly cookie 對任何 JS（不管是不是惡意）都不可讀，`document.cookie` 看不到、`fetch`/`XMLHttpRequest` 也讀不到值本身。
- ✅ 附帶簡化：拿掉 token-in-URL 這個既有的曝露面（SSE、audio player），程式碼量反而減少（前端不用管 header 注入）。
- ⚠️ 唯一新增的風險面是 CSRF，但如上所述，這個架構的同源特性讓 `SameSite=strict` 幾乎打平這個風險，不需要重工程。

## 4. 建議

**先做方案 A，把方案 B 排進下一個週期，不是「二選一」而是「先後順序」：**

1. **方案 A 立即做**：改動面小（前端 2 個檔案的儲存實作 + 1 個路由守衛判斷邏輯），後端零改動，沒有 CSRF 這類需要仔細驗證的新風險面，一天內可以完成並上線。它不能擋 active-XSS，但确实排除了「token 被動躺在 localStorage 被非執行期手段偷走」這個現實存在、方案 B 也不會額外處理得更好的風險（方案 B 換成 cookie 後，一樣要考慮瀏覽器/裝置層級的其他讀取手段，只是 cookie 天生比 localStorage 少一種「JS 可讀」的曝險）。
2. **方案 B 列為下一個週期的架構任務**，理由：
   - 後端改動集中（一個 dependency + 兩個 cookie 寫入點），比一開始想像的分散風險小。
   - 這個架構的同源特性讓 CSRF 疑慮遠比典型「SPA + 獨立 API 網域」場景小，`SameSite=strict` 已有 refresh_token 這個先例證明可行。
   - 唯一需要重新設計的是 `ensureFreshAccessToken` 的到期時間判斷（改讀後端回傳的 `expires_at` 而非解析 JWT payload），工程量可控。
   - 這是全清單裡**唯一能真正防禦「active XSS 竊取 token」**的方案——如果之後真的要對 stored XSS 做到「就算中了也偷不到 token」的等級，只有這條路。

**不建議的組合**：只做方案 A 就永久停在那——要對決策者說清楚方案 A 是暫時性的曝險降低，不是終局方案，避免「做了方案 A 就當作 TODO-8 完全解決」的誤解。

---

*本文件為評估產出，未改動任何程式碼。決策後請回報要採用哪個方案（或兩者都做／都不做），再另開 PR 動工。*
