# 測試帳號說明

> 腳本：`scripts/seed_test_users.py`

---

## 帳號列表

密碼一律：`TestUser@123`

| Email | 方案 | 時數用量（上限） | 剩餘時數 | AI 摘要用量（上限） | 剩餘 AI 摘要 | 批次上傳 | 優先處理 |
|---|---|---|---|---|---|---|---|
| test.free@soundlite.app | 免費版 | 170 / 180 分 | 10 分 | 2 / 3 次 | 1 次 | ❌ | ❌ |
| test.basic@soundlite.app | 基礎版 | 595 / 600 分 | 5 分 | 29 / 30 次 | 1 次 | ✅ | ❌ |
| test.pro@soundlite.app | 專業版 | 2995 / 3000 分 | 5 分 | 99 / 100 次 | 1 次 | ✅ | ✅ |
| test.enterprise@soundlite.app | 企業版 | 0 / 無上限 | 無上限 | 0 / 無上限 | 無上限 | ✅ | ✅ |

usage 預設接近上限，可直接測試配額邊界行為（超量拒絕、剩最後一次等）。

---

## 各方案功能差異

| 功能 | 免費版 | 基礎版 | 專業版 | 企業版 |
|---|---|---|---|---|
| 每月時數 | 180 分 | 600 分 | 3,000 分 | 無上限 |
| 每月 AI 摘要 | 3 次 | 30 次 | 100 次 | 無上限 |
| 同時任務數 | 1 | 2 | 5 | 10 |
| 說話者辨識 | ✅ | ✅ | ✅ | ✅ |
| 標點強化 | ✅ | ✅ | ✅ | ✅ |
| 批次上傳 | ❌ | ✅ | ✅ | ✅ |
| 優先處理 | ❌ | ❌ | ✅ | ✅ |
| 音檔保留天數 | 3 天 | 7 天 | 7 天 | 7 天 |
| 手動保留音檔額度 | 0 | 10 | 30 | 無上限 |

---

## 示範任務

每個帳號各有一筆已完成的 mock 示範任務：

- **名稱**：示範轉錄（SoundLite 功能展示）
- **檔名**：soundlite_demo.mp3（約 60 秒）
- **語言**：中文（zh）
- **說話者辨識**：開啟，2 位說話者（主持人 / 來賓）
- **時間軸**：9 段

任務 ID 格式為 `test-demo-task-{tier}`（例：`test-demo-task-free`）。

---

## 指令

### 本地開發

```bash
source venv/bin/activate

# 初次建立帳號與示範任務
python scripts/seed_test_users.py

# 查看目前狀態
python scripts/seed_test_users.py --list

# 重置（usage / session / 示範任務 還原）
python scripts/seed_test_users.py --reset

# 確認會做什麼但不寫入
python scripts/seed_test_users.py --dry-run
python scripts/seed_test_users.py --reset --dry-run
```

### Staging 環境

```bash
ssh -i ~/.ssh/transcriber-key.pem ec2-user@52.196.120.189
cd /opt/transcriber

python3.11 scripts/seed_test_users.py --list
python3.11 scripts/seed_test_users.py --reset
```

Staging 網址：https://staging.soundlite.app（需 Cloudflare Access 授權）

---

## 重置說明

`--reset` 會還原以下內容，**帳號密碼與方案設定不變**：

| 項目 | 重置後狀態 |
|---|---|
| 時數用量 | 還原到近上限（如帳號列表所示） |
| AI 摘要用量 | 還原到近上限 |
| 額外額度 | 清零 |
| 登入 session | 全部登出（refresh_tokens 清空） |
| 示範任務 | 刪除重建（tasks / transcriptions / segments 一起） |
| 帳號密碼 | 不變 |
| 方案 / 配額 | 不變 |

若帳號不存在，`--reset` 會提示先執行不帶旗標的 seed 指令建立帳號。
