# 線上監控設定

> 最後更新：2026-05-17
> 對應 LAUNCH_READINESS_PLAN：B6（CloudWatch alarm 部分）

---

## 目前已就位的 alarm

### ap-northeast-1（主 region）

| Alarm | 監控對象 | 閾值 | 動作 |
|-------|---------|------|------|
| `transcriber-ec2-auto-recover` | EC2 系統檢查失敗 | StatusCheckFailed_System ≥ 1，連續 2 個資料點 | 自動 recover instance（搬硬體重啟） |
| `web-cpu-high` | Web Server CPU | > 85% 連續 2 期 | 寄信到 hsinforwork@gmail.com |
| `sqs-queue-depth` | SQS 訊息數 | > 10 條 | 寄信 |
| `transcriber-sqs-messages-alarm` | SQS 訊息數 | ≥ 1 條 | 觸發 Lambda 啟動 GPU |
| **`transcriber-sqs-oldest-message-stuck`** | SQS 最舊訊息存活時間 | > 600 秒（10 分鐘）連續 2 期 | 寄信。**Worker 卡住的最佳指標** |

### us-east-1（Route53 metrics 強制使用）

| Alarm | 監控對象 | 閾值 | 動作 |
|-------|---------|------|------|
| **`transcriber-health-endpoint-down`** | `https://soundlite.app/health` HTTP 狀態 | 連續 2 個 1 分鐘窗口失敗 | 寄信 |

對應的 Route53 health check：
- ID：`fa65c1d9-daa7-4912-8eb7-b3630900b6a5`
- 從 ~15 個 AWS region IP 同時 polling `/health`，30 秒一次
- 失敗閾值 3 次 = ~90 秒判定 unhealthy

---

## SNS topic 訂閱

| Topic ARN | Region | 訂閱者 |
|-----------|--------|--------|
| `arn:aws:sns:ap-northeast-1:696637902131:transcriber-alerts` | ap-northeast-1 | hsinforwork@gmail.com ✅ |
| `arn:aws:sns:ap-northeast-1:696637902131:transcriber-sqs-alarm` | ap-northeast-1 | Lambda `transcriber-gpu-starter` |
| **`arn:aws:sns:us-east-1:696637902131:transcriber-alerts`** | us-east-1 | hsinforwork@gmail.com ⏳ **需點確認信** |

⚠️ **AWS 寄了一封 SNS 訂閱確認信到 hsinforwork@gmail.com**，要點「Confirm subscription」連結，否則 us-east-1 alarm 觸發時收不到通知。

---

## 失敗情境覆蓋對照表

| 故障 | 哪個 alarm 抓到 | 反應時間 |
|------|---------------|---------|
| EC2 硬體故障 / kernel panic | `transcriber-ec2-auto-recover` | 2 分鐘自動 recover |
| EC2 CPU 飆滿 | `web-cpu-high` | 2 分鐘寄信 |
| FastAPI process 卡住 | `transcriber-health-endpoint-down` | ~3 分鐘寄信（90s 判失敗 + 2 期 evaluation） |
| MongoDB 連線斷 | `transcriber-health-endpoint-down`（/health 真檢查 DB） | ~3 分鐘 |
| GPU worker 卡住 / 沒啟動 | `transcriber-sqs-oldest-message-stuck` | 10-15 分鐘 |
| GPU 配額用完 spot 拉不到 | 同上 + Lambda 應自動 fallback 到 on-demand | 10-15 分鐘 |
| Cloudflare → EC2 連線異常 | `transcriber-health-endpoint-down` | ~3 分鐘 |

---

## 沒做的（評估後不需要 / 過早）

- **Worker heartbeat collection 直接監控**：原本想用 Lambda 查 `worker_heartbeats`，但 SQS oldest message age 已能覆蓋同樣故障模式（worker 卡住 → SQS 訊息堆積 → age 上升 → 告警）。Heartbeat 留作 debug 用途，不另設 alarm。
- **MongoDB Atlas 監控**：M0 tier 沒有完整 metric。升 M2 後可開 Atlas 內建的 connection / op latency alarm。
- **Stripe / 藍新 webhook 失敗率**：等真上線跑一陣子，用 Sentry 看就好，不必過早 alarm。

---

## 如何測試 alarm 是否真的會通知

### SQS oldest message age（不建議跑，會佔 GPU 配額）
塞一個假訊息到 SQS，但**不啟動 worker**，等 10 分鐘看會不會收到信。

### Health endpoint（推薦驗證方式）
SSH 進 Web Server 暫停服務 3 分鐘：
```bash
ssh -i ~/.ssh/transcriber-key.pem ec2-user@3.112.209.96
sudo systemctl stop transcriber
# 等 3 分鐘，應收到信
sudo systemctl start transcriber
# 等 3 分鐘，alarm 應恢復 OK
```

---

## CLI 速查（要改設定時）

```bash
# 列出所有 alarm 與狀態
aws cloudwatch describe-alarms --query "MetricAlarms[].[AlarmName,StateValue]" --output table
aws cloudwatch describe-alarms --region us-east-1 --query "MetricAlarms[].[AlarmName,StateValue]" --output table

# 看 Route53 health check 即時結果
aws route53 get-health-check-status --health-check-id fa65c1d9-daa7-4912-8eb7-b3630900b6a5

# 暫停某個 alarm（維護時）
aws cloudwatch disable-alarm-actions --alarm-names transcriber-health-endpoint-down --region us-east-1
aws cloudwatch enable-alarm-actions  --alarm-names transcriber-health-endpoint-down --region us-east-1

# 刪除 health check（停用整個健康監控）
aws route53 delete-health-check --health-check-id fa65c1d9-daa7-4912-8eb7-b3630900b6a5
```

---

## 月費影響

| 項目 | $/月 |
|------|-----|
| Route53 health check（30s 間隔，跨多 region） | $0.50 |
| CloudWatch alarms（前 10 個免費，我們 6 個遠未超） | $0 |
| SNS（前 1000 通知/月免費） | $0 |
| **總計** | **~$0.50** |
