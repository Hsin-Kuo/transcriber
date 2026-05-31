# Contributing

> 工作流程文件。Repo 設了 branch protection，**任何 code 變更都要走 PR**。

---

## 分支模型

| 分支 | 角色 | 寫入方式 |
|------|------|---------|
| `feature/*`、`fix/*`、`docs/*` | 開發 | 直接 commit |
| `main` | source of truth、隨時 deployable | **只接 PR**，禁止直接 push |
| `aws` | 當前 production 部署版本（push 觸發 deploy） | **只接 fast-forward from main**，禁止其他 commit |

```
feature/* ─► PR ─► main ─► (fast-forward) ─► aws ─► deploy
              ↑              ↑                  ↑
              tests          手動 ff            自動 deploy
              review
```

---

## 日常開發流程

```bash
# 1. 開新分支
git checkout main && git pull
git checkout -b feature/<short-description>

# 2. 開發 + commit
# ...

# 3. push + 開 PR
git push -u origin feature/<short-description>
gh pr create --base main --title "..." --body "..."

# 4. CI 跑（5 個 status check）→ 通過後合併
gh pr merge --squash --delete-branch
```

### Status checks（CI 必須全綠才能 merge）

- `Ruff`（Python lint）
- `Pytest`（Python tests）
- `Nginx conf 文法`（docker run nginx:alpine nginx -t）
- `Frontend ESLint + type-check + test (frontend)`
- `Frontend ESLint + type-check + test (admin-frontend)`

---

## Deploy 流程

每次 deploy 都需要明確的 git 操作（不會 auto-deploy on main merge）：

```bash
# 1. main 已合進 PR
git checkout aws && git pull
git merge --ff-only origin/main

# 2. push 觸發 GitHub Actions deploy
git push origin aws

# 3. 等 CI 跑（看 gh run watch 或 GitHub Actions 頁面）
gh run list --branch aws --limit 1

# 4. 驗證
curl https://my.soundlite.app/health
```

deploy 內容詳見 [`docs/DEPLOYMENT.md`](./docs/DEPLOYMENT.md)。

---

## Branch protection 摘要

設定生效於 2026-05-30：

| 設定 | `main` | `aws` |
|------|--------|------|
| 必走 PR | ✅（0 approvals — solo dev） | ❌（直接 ff push） |
| Status checks | ✅ 5 個必過 | ❌（已在 main 過 check） |
| Linear history | ✅（禁 merge commit） | ✅（只 ff） |
| 禁 force push | ✅ | ✅ |
| 禁 deletion | ✅ | ✅ |
| Admin 可 bypass | ✅（緊急 hotfix，留 audit log） | ✅ |

Admin bypass 紀錄在個人 https://github.com/settings/security-log。

---

## Commit message convention

跟 repo 既有風格一致：
```
<type>(<scope>): <subject>

<body>

Co-Authored-By: ...
```

| Type | 用途 |
|------|------|
| `feat` | 新功能 |
| `fix` | bug 修復 |
| `perf` | 效能改進（不改變行為） |
| `refactor` | 重構（不改變行為、不改效能） |
| `docs` | 文件 |
| `test` | 測試 |
| `chore` | 依賴 / build / CI |

Scope 範例：`upload`、`auth`、`email`、`deploy`、`db`、`frontend`。

Subject 用繁體中文，技術關鍵字保留英文。

---

## 緊急 hotfix

只有在 incident 真正影響 production 時才用 admin bypass：

```bash
git checkout main
git commit --allow-empty -m "hotfix: ..."   # 或實質 commit
git push origin main                         # GitHub warn 但會通過
```

事後**一定**回頭：
1. 補上 test
2. 補上 PR（PR base 後合進 main）標記為 retroactive review
3. 在 audit log 寫個 issue link

---

## 其他

- 開發環境啟動：`docker-compose up -d` 或看 [`CLAUDE.md`](./CLAUDE.md)
- 寫測試：`tests/unit/`、`tests/integration/` 等，需要 MongoDB 的 test 用 `localhost:27020`
- 部署環境的密鑰、infrastructure：見 [`docs/DEPLOYMENT.md`](./docs/DEPLOYMENT.md)
- Architectural tech debt：見 [`docs/IMPROVEMENT_TASKS.md`](./docs/IMPROVEMENT_TASKS.md)
