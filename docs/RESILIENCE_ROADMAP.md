# 韌性改善路線圖

> 最後更新：2026-04-22

---

## 風險摘要

| 風險 | 等級 | 說明 |
|------|------|------|
| EC2 t3.small 單點故障 | 🔴 高 | 機器掛掉 → 全站停止，無自動恢復 |
| Spot 被中斷無通知處理 | 🔴 高 | worker.py 無 Spot 預警輪詢，任務直接 failed |
| MongoDB Atlas M0 無備份 | 🔴 高 | 512MB 上限、共享 cluster、無自動備份 |
| /tmp 磁碟空間 | 🟡 中 | 大檔上傳 + ffmpeg 暫存可能撐爆磁碟 |
| SSE 長連線 | 🟡 中 | 每個轉錄中任務維持一條 SSE，用戶多時會到 fd 上限 |
| 一般 API 無 rate limiting | 🟡 中 | 只有密碼重設有保護 |
| SSL 憑證無自動續約 | 🟡 中 | Certbot 若沒設 cron，90 天後 HTTPS 失效 |
| Worker MongoDB 無連線池 | 🟢 低 | 每個任務都新建 MongoClient，資源浪費 |

---

## 第一階段：馬上要做（成本 $0，防止崩潰）

### ✅ 1-A　Spot 中斷預警處理（`src/worker.py`）
- **類型**：Code 改動
- **狀態**：✅ 已完成（2026-04-22）
- 新增函式：`_check_spot_interruption()`、`_handle_spot_interruption()`、`_spot_monitor()`
- 背景執行緒（daemon）每 30 秒輪詢 EC2 metadata `spot/termination-time`，偵測到中斷預警後：
  - 將當前任務 status 重置為 `pending`
  - 縮短 SQS 消息 visibility timeout 至 30 秒，讓另一台 Worker 立即接手
  - 設定 `_shutdown = True` 停止主迴圈
- 防止重複處理：`process_task` 開頭加入 `status == completed` 跳過檢查
- 主迴圈以 `_current_task_id` / `_current_receipt_handle` 追蹤當前任務

### ✅ 1-B　Worker MongoDB 連線池（`src/worker.py`）
- **類型**：Code 改動
- **狀態**：✅ 已完成（2026-04-22）
- 改為 module-level MongoClient 單例（`_mongo_client`，`maxPoolSize=5`），避免每個任務重新建立連線

### ✅ 1-C　EC2 自動恢復（CloudWatch）
- **類型**：AWS Console 操作（約 5 分鐘）
- **成本**：$0
- **狀態**：✅ 已完成（2026-04-22）— alarm `transcriber-ec2-auto-recover` 已建立

### ✅ 1-D　SQS Dead Letter Queue
- **類型**：AWS Console 操作（約 5 分鐘）
- **成本**：$0
- **狀態**：✅ 已完成（2026-04-22）— `transcriber-tasks-dlq` 已建立，maxReceiveCount=3

### ✅ 1-E　Certbot 自動續約 cron
- **類型**：SSH 到 EC2 執行一次
- **成本**：$0
- **狀態**：✅ 不適用（2026-04-22）— SSL 由 Cloudflare 管理，不需 certbot

### ✅ 1-F　CloudWatch 基本警報
- **類型**：AWS Console 操作（約 15 分鐘）
- **成本**：$0（SNS Email 免費）
- **狀態**：✅ 已完成（2026-04-22）— SNS topic `transcriber-alerts` → hsinforwork@gmail.com

  | 警報名稱 | 指標 | 條件 | 狀態 |
  |---------|------|------|------|
  | `web-cpu-high` | EC2 CPUUtilization | > 85%，持續 10 分鐘 | ✅ |
  | `web-disk-high` | disk_used_percent（需 CloudWatch Agent） | > 80% | ⬜ 需裝 Agent |
  | `sqs-queue-depth` | SQS ApproximateNumberOfMessagesVisible | > 10，持續 5 分鐘 | ✅ |

### ⬜ 1-G　EC2 磁碟擴容 + 暫存清理
- **類型**：AWS Console + SSH
- **成本**：30GB gp3 約 $2.4/月（比預設 8GB 多 $1.9）
- AWS Console → EC2 → Volumes → 修改大小為 30GB（線上擴容，不需重開機）
- SSH 後執行：
  ```bash
  sudo growpart /dev/xvda 1
  sudo xfs_growfs /
  # 設定 cron 定期清理暫存
  echo "0 * * * * ec2-user find /tmp -name '*.mp3' -mmin +120 -delete 2>/dev/null" \
    | sudo tee /etc/cron.d/tmp-cleanup
  ```

---

## 第二階段：100～500 活躍用戶（+$60～80/月）

### ⬜ 2-A　MongoDB Atlas 升級至 M10（最重要）
- **成本**：+$57/月
- 獲得：自動每日備份、point-in-time restore、專屬 cluster、encryption at rest、500 連線數
- 操作：MongoDB Atlas → Cluster → Edit → 升級方案（約 5 分鐘，零停機）

### ⬜ 2-B　CloudFront + S3 serve 前端靜態檔
- **成本**：+$1～5/月
- 解放 EC2 頻寬；EC2 掛掉時前端仍可訪問
- 改動：
  - 建 S3 Bucket × 2（user frontend + admin frontend）
  - 建 CloudFront Distribution × 2
  - 更新 `.github/workflows/deploy-aws.yml`：改為 `aws s3 sync` + `cloudfront create-invalidation`

### ✅ 2-C　Nginx API Rate Limiting
- **成本**：$0（Nginx 原生支援）
- **狀態**：✅ 已完成（2026-04-22）— 每 IP 30 req/min，burst 10，超過回 429

### ⬜ 2-D　GPU Worker Auto Scaling Group
- **成本**：$0（停機時不計費）
- CloudWatch Alarm：SQS 深度 > 0 → 啟動 g4dn.xlarge Spot
- 取代目前手動開機的方式

---

## 第三階段：500～2000 活躍用戶（再 +$80～150/月）

### ⬜ 3-A　ALB + 第二台 Web Server（真正 HA）
- **成本**：ALB ~$16/月 + 第二台 t3.small ~$15/月
- 滾動更新（零停機部署）、其中一台掛掉仍服務

### ⬜ 3-B　ElastiCache Redis t3.micro
- **成本**：~$15/月
- 將 rate limiting 從 MongoDB（`rate_limits` collection）移至 Redis
- 未來多機 session 共享、API 回應快取

### ⬜ 3-C　WAF + Shield Standard
- **成本**：WAF ~$5/月起
- 防 DDoS、SQL injection、常見攻擊模式

---

## 費用試算

| 階段 | 新增月費 | 累計月費（含現有 ~$30） |
|------|---------|----------------------|
| 第一階段 | ~$2（磁碟擴容） | ~$32 |
| 第二階段 | +$63～68 | ~$95～100 |
| 第三階段 | +$96～100 | ~$190～200 |
