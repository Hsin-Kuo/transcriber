# 管理後台 RBAC 漸進式導入方案（P0-1）

> 建立日期：2026-07-20
> 對應 roadmap：`docs/ADMIN_ROADMAP.md` P0-1
> 狀態：**Phase 0 已完成**（`src/auth/rbac.py` + `require_permission` + backfill migration + 測試）

## 核心設計原則

1. **保留 `get_current_admin` 當粗閘門不動** — `role == "admin"`（來自 JWT claim）仍是「能不能進後台」第一關，既有程式零改動。
2. **細分權限疊在上層** — 新增 `admin_role`（user 文件欄位）+ permission 檢查，套在粗閘門之後。
3. **權限檢查查 DB、不進 token** — `role` 是 JWT claim（改了要重登才生效、無法即時撤權），故細分角色**不進 token**：`require_permission` 從 DB 即時讀 `admin_role`。admin 流量極低，多一次 DB read 換即時撤權，划算。
4. **以 Permission（能力）為授權單位，不以 Role 綁 endpoint** — Role 只是 Permission 的組合包；加新角色/調能力只改 `rbac.py` 一張表，不動 endpoint。
5. **相容過渡** — 現有 admin 無 `admin_role` → 先一律當 `superadmin`（全開），確保上線當天無人受影響，再逐步收緊。

## 角色與能力矩陣

| Permission | superadmin | billing | support | read_only |
|---|:--:|:--:|:--:|:--:|
| `user:read` | ✅ | ✅ | ✅ | ✅ |
| `user:manage`（停用/啟用） | ✅ | | ✅ | |
| `user:quota`（改配額/補償額度） | ✅ | ✅ | ✅ | |
| `user:password_reset` | ✅ | | | |
| `task:read` | ✅ | ✅ | ✅ | ✅ |
| `task:manage`（取消） | ✅ | | ✅ | |
| `task:delete`（刪除/批次刪） | ✅ | | | |
| `analytics:read` | ✅ | ✅ | ✅ | ✅ |
| `billing:read`（營收/訂單） | ✅ | ✅ | | ✅ |
| `billing:write`（退款/開通，P0-3） | ✅ | ✅ | | |
| `audit:read` | ✅ | ✅ | ✅ | ✅ |
| `audit:export`（P0-4） | ✅ | ✅ | | |
| `admin:grant`（升降 admin/指派角色） | ✅ | | | |
| `ops`（維運清理） | ✅ | | | |

權威定義在 `src/auth/rbac.py` 的 `ROLE_PERMISSIONS`（本表僅為對照，改動以程式為準）。

## 分階段落地

### Phase 0 — 地基（純新增，零行為改變）✅ 已完成
- `src/auth/rbac.py`：`AdminRole` / `Permission` enum + `ROLE_PERMISSIONS` + `role_has()` / `permissions_for()`。
- `src/auth/dependencies.py`：`require_permission(perm)` 依賴工廠——疊在 `get_current_admin` 之後，從 DB 讀 `admin_role`，未 migrate 者暫當 superadmin 並記 `rbac.unmigrated_admin` log。
- `src/database/migrations/backfill_admin_role.py`：把現有 `role=="admin"` 且無 `admin_role` 者 backfill 成 `superadmin`（冪等）。
- `tests/auth/test_rbac.py`：能力表約束 + 依賴行為（含相容/非法角色）共 11 測試。
- **結果**：行為完全不變（所有現有 admin = superadmin = 全開），基礎設施就緒。

### Phase 1 — 把依賴掛上 endpoint（仍沒人被鎖）✅ 後端完成
- ✅ `src/routers/admin.py` 21 支 endpoint 全掛 `Depends(require_permission(Permission.X))`（見下表）。因所有人仍是 superadmin，行為不變。
- ✅ `GET /api/admin/me/permissions`：下發當前 admin 的 role + 能力清單。
- ✅ wiring 測試 `tests/routers/test_admin_rbac.py`：內省每支 route 的依賴樹，斷言掛對能力（endpoint→permission 對照鎖成可執行規格）+ `/me/permissions` 行為。
- ✅ **前端**：`authStore.can(perm)`（fetch `/me/permissions`，未載入/失敗樂觀放行）+ `constants/permissions.js`；AdminNav 依能力隱藏頁籤，UsersView/UserDetailView/AdminTasksView/AdminTaskDetailView 的停用/改角色/改配額/重設密碼/取消/刪除按鈕依能力 v-if。後端仍是真閘門。
  - 已知後續（Phase 2 收緊角色後才會浮現）：AdminDashboard 的營收 widget 走 `billing:read`，support 角色進 Dashboard 會讓 `/revenue` 回 403——屆時需在 Dashboard 內依 `billing:read` 隱藏該區塊或容錯。

endpoint → permission 對照（Phase 1 施工清單）：

| endpoint | permission |
|---|---|
| `GET /users`、`GET /users/{id}` | `user:read` |
| `PUT /users/{id}/status` | `user:manage` |
| `PUT /users/{id}/quota`、`POST /users/{id}/reset-quota`、`POST /users/{id}/extra-quota` | `user:quota` |
| `POST /users/{id}/reset-password` | `user:password_reset` |
| `PUT /users/{id}/role` | `admin:grant` |
| `GET /tasks`、`GET /tasks/{id}` | `task:read` |
| `POST /tasks/{id}/cancel` | `task:manage` |
| `DELETE /tasks/{id}`、`POST /tasks/batch/delete` | `task:delete` |
| `GET /statistics`、`GET /cost` | `analytics:read` |
| `GET /revenue` | `billing:read` |
| `GET /audit-logs*` | `audit:read` |
| `POST /cleanup/*` | `ops` |

### Phase 2 — 導入真實角色 + 護欄 ✅ 完成
- ✅ 後端：`PUT /users/{id}/admin-role` 指派細分角色（ADMIN_GRANT → superadmin 專屬）；`PUT /users/{id}/role` 升級時套用 `admin_role`（預設 `read_only`）、降級時清 `admin_role`。護欄抽在 `src/services/admin_role_service.py` 純函式：
  - 只有 superadmin 能到這兩支（ADMIN_GRANT）。
  - 禁止移除系統中**最後一個 superadmin**（降級 or 改細分角色皆擋）、禁止改自己的角色/細分角色。
  - `admin_role` 只接受 enum 白名單值。
- ✅ `user_repo.set_admin_role()`：支援 `$unset`（降級清殘值）；`GET /users/{id}` 回傳 `admin_role`。
- ✅ 前端 UserDetailView：顯示當前權限角色 + 指派 modal（4 角色 select）+ 升級時可選角色。
- ✅ 測試：`tests/services/test_admin_role_service.py` 窮舉護欄；wiring 測試納入新 endpoint。
- ⏳ **待做（正式切換）**：實際把客服/財務帳號從 superadmin 改成 `support`/`billing`（一個 admin-role API 呼叫即可），最小權限才真正生效。這是營運動作、非程式。

> **P0-2 剩餘部分**（獨立於本 RBAC 收尾，未做）：管理員邀請流程（email invite）、首登強制改密、移除 `seed_admin.py` 硬編碼帳密、admin 強制 2FA。見 `docs/ADMIN_ROADMAP.md` P0-2。

### Phase 3 — 收緊相容後門
- 全部 admin migrate 後，把 Phase 0 的「未設 admin_role → superadmin」改為**拒絕/最小權限**。
- 翻轉前先確認 `rbac.unmigrated_admin` log 歸零、且 ≥1 個 superadmin 存在。

## 回滾策略
- Phase 0–1 是純新增，回滾 = 移除 endpoint 上的 `Depends(require_permission(...))`；粗閘門 `get_current_admin` 仍在，後台不會失守。
- 過渡後門在時，角色解析異常最壞是「當 superadmin 放行」而非「全員鎖死」——刻意偏向可用性優先，直到 Phase 3 才反轉。

## 風險註記（走 `judgment-rubrics.md §5` 高風險驗收）
- 觸及 auth 授權層，每步都要有測試佐證「該擋的有擋」。
- Phase 3 翻轉後門是唯一可能鎖死的時點，務必先確認上述兩條前提。
- 權限不足的嘗試除了 log 也應進 audit（供事後稽核）。
