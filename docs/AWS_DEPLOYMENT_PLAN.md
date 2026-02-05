# AWS 部署計畫 (Whisper Transcriber)

> 最後更新：2026-02-04

---

## 目錄

1. [架構概覽](#1-架構概覽)
2. [基礎設施清單](#2-基礎設施清單)
3. [資料流與儲存策略](#3-資料流與儲存策略)
4. [前端部署策略](#4-前端部署策略)
5. [HTTPS 與域名](#5-https-與域名)
6. [即時狀態回報方案](#6-即時狀態回報方案)
7. [密鑰管理](#7-密鑰管理)
8. [Email 服務遷移](#8-email-服務遷移)
9. [CORS 與安全性](#9-cors-與安全性)
10. [靜態加密 (Encryption at Rest)](#10-靜態加密-encryption-at-rest)
11. [監控與日誌](#11-監控與日誌)
12. [CI/CD Pipeline](#12-cicd-pipeline)
13. [關鍵成本控制](#13-關鍵成本控制)
14. [MongoDB Atlas 注意事項](#14-mongodb-atlas-注意事項)
15. [本地開發與 AWS 並行策略](#15-本地開發與-aws-並行策略)
16. [程式碼需調整項目](#16-程式碼需調整項目)
17. [部署步驟](#17-部署步驟)
18. [待辦事項檢查清單](#18-待辦事項檢查清單)

---

## 1. 架構概覽

採用 **Web / AI Worker 分離架構**，以 SQS 解耦，GPU 機器可獨立擴展與關機。

```
                       Route 53 (DNS)
                            │
                       CloudFront (CDN)
                  ┌─────────┼─────────┐
             S3 Bucket      │      S3 Bucket
          (User Frontend) (Admin Frontend)
                            │
              ┌─────── t3.small (Web Server) ───────┐
              │   FastAPI (API / Auth / S3簽名)      │
              │   Caddy (HTTPS reverse proxy)        │
              └──────┬──────────────┬────────────────┘
                     │              │
                  MongoDB       AWS SQS
                  Atlas         (任務佇列)
                     │              │
              ┌──────┴──────────────┴────────────────┐
              │   g4dn.xlarge (AI Worker - Spot)     │
              │   faster-whisper + pyannote.audio     │
              │   監聽 SQS → 下載 S3 → 轉錄 → 寫回 DB │
              └──────────────────────────────────────┘
                                │
                           AWS S3
                      (音檔 uploads/output)
```

**核心設計原則**：
- Web Server 不需要 GPU，用最小規格即可
- GPU Worker 用 Spot Instance 省 70% 成本
- Spot 被回收只影響轉錄，不影響網站運作
- 沒任務時 GPU 機器可完全關機 (Scale to Zero)

---

## 2. 基礎設施清單

| 元件 | 選型 | 規格 | 用途 | 預估月費 (USD) |
|------|------|------|------|----------------|
| **Web Server** | EC2 | `t3.small` | API、Auth、S3 簽名、SQS 發送 | ~$15 |
| **AI Worker** | EC2 Spot | `g4dn.xlarge` | Whisper 轉錄、說話者辨識 | ~$0.20/hr (依用量) |
| **任務佇列** | SQS | Standard Queue | 解耦 Web 與 AI Worker | ~$0 (免費額度內) |
| **資料庫** | MongoDB Atlas | M0 (Free) → M10 | 用戶資料、任務狀態、轉錄文字 | $0 → $57 |
| **檔案儲存** | S3 | Standard + SSE-S3 (AES-256) | MP3 音檔、轉錄結果檔案（預設加密） | 依用量 |
| **前端 CDN** | CloudFront | - | Vue SPA 靜態資源分發 | ~$1-5 |
| **前端靜態檔** | S3 | - | Vue build 產出 | ~$0.5 |
| **DNS** | Route 53 | - | 域名管理 | ~$0.50/zone |
| **SSL 憑證** | ACM | - | HTTPS 憑證 (免費) | $0 |
| **密鑰管理** | SSM Parameter Store | - | 環境變數、API Key | $0 (Standard tier) |
| **Email** | SES | - | 驗證信、密碼重設信 | ~$0 (免費額度內) |
| **日誌** | CloudWatch Logs | - | 雙機器日誌收集 | ~$1-5 |

---

## 3. 資料流與儲存策略

### 儲存位置

| 資料類型 | 儲存位置 | 說明 |
|---------|---------|------|
| 音檔（mp3，已提取音訊） | AWS S3 | `temp/` 7 天自動刪除、`permanent/` 付費用戶保留 |
| 轉錄文字 (segments JSON) | MongoDB Atlas | 支援編輯、搜尋、前端即時讀取 |
| 匯出檔案 (TXT/JSON) | AWS S3 | `output/{task_id}/`，供用戶下載 |
| 下載方式 | S3 Presigned URL | 前端用簽名連結直接從 S3 下載，不經後端 |

### 上傳策略：後端中轉 + 音訊提取

用戶上傳經過 Web Server，由後端完成預處理（格式轉換、合併、配額檢查）後，**只將提取的音訊（mp3）** 存到 S3。

#### 為什麼不讓前端直傳 S3？

用戶上傳的檔案可能是 mp4 影片，但 Whisper 只需要音軌：

```
30 分鐘會議錄影：
  原始 mp4（含影像） ≈ 500MB ~ 2GB
  提取後 mp3（純音訊）≈ 28MB（128kbps × 30min × mono）

差距約 20～70 倍
```

如果讓前端直傳 S3，影片原檔會存到 S3，Worker 再下載整個影片做轉換，**儲存和頻寬都浪費**。
後端中轉可以在上傳 S3 前就完成音訊提取，S3 從頭到尾只存小的 mp3。

此外，後端中轉還能做到：
- **即時配額檢查**：上傳時就用 ffprobe 取得時長，立即判斷是否超額，不用等到 Worker 才發現
- **多檔合併**：現有 ffmpeg 合併邏輯不用動
- **前端零改動**：上傳方式維持 multipart form POST

#### 資料流程

```
┌──────────┐     ┌────────────────────────────────────────────────┐     ┌─────┐
│  Browser  │────▶│  Web Server (t3.small)                         │────▶│  S3 │
│          │     │                                                │     │     │
│ 上傳 mp4 │     │  1. 接收檔案，存到本機 /tmp                    │     │     │
│ 500MB    │     │  2. 多檔？→ ffmpeg 合併成 mp3                  │     │     │
│          │     │  3. 單檔？→ ffmpeg 提取音訊（-vn）→ mp3        │     │     │
│          │     │     ⭐ 500MB mp4 → 28MB mp3（去掉影像軌）       │     │     │
│          │     │  4. ffprobe 取得時長（例：32 分鐘）             │     │     │
│          │     │  5. 檢查用戶配額（32 min < 60 min ✓）          │     │     │
│          │     │  6. 上傳 28MB mp3 到 S3（不是 500MB mp4）       │     │     │
│          │     │  7. 刪除本機暫存的 mp4                         │     │     │
│          │     │  8. 建立 task 記錄（MongoDB）                   │     │     │
│          │     │  9. 發送 SQS 訊息                              │     │     │
└──────────┘     └────────────────────────────────────────────────┘     └─────┘
                                                                           │
                 ┌───────────────────────────────────────────┐             │
                 │  AI Worker (g4dn.xlarge)                  │◀────────────┘
                 │                                           │
                 │ 10. 從 SQS 收到任務                       │
                 │ 11. 從 S3 下載 28MB mp3（不是 500MB）      │
                 │ 12. Whisper 轉錄 + 標點 + 說話者辨識       │
                 │ 13. 結果寫入 MongoDB + 匯出檔上傳 S3       │
                 │ 14. 更新 task status = completed           │
                 └───────────────────────────────────────────┘
```

#### 音訊提取的實作基礎

現有程式碼 `transcription_service.py:_convert_audio_to_mp3()` 已有完整的轉換邏輯：

```python
# 現有程式碼，可直接複用到上傳流程
subprocess.run([
    'ffmpeg', '-y', '-i', str(audio_path),
    '-vn',                  # 去掉影像軌
    '-acodec', 'libmp3lame',
    '-b:a', '128k',         # 128 kbps
    '-ar', '16000',          # 16 kHz（Whisper 推薦）
    '-ac', '1',              # 單聲道
    str(mp3_path)
])
```

只需將此邏輯從 Worker 端（transcription_service）搬到上傳流程（transcriptions.py），在存 S3 之前執行即可。Web Server 本來就需要 ffmpeg（做 ffprobe），不需額外安裝。

#### 程式碼改動量

| 檔案 | 改動 |
|------|------|
| `transcriptions.py` | 上傳流程加入音訊提取（複用現有 `_convert_audio_to_mp3`），再存到 S3 |
| `s3_service.py` | 新增：S3 upload / download / presign 封裝 |
| `worker.py` | 新增：SQS consumer，從 S3 下載 mp3 → 直接轉錄（不再需要轉檔） |
| 前端 | **不改**：上傳方式維持 multipart form |

#### 優點

- **大幅節省 S3 儲存與頻寬**：只存 mp3，影片檔在 Web Server 就被壓縮掉
- **即時回饋**：上傳時就能告訴用戶「檔案 32 分鐘、超出配額」
- **改動最小**：現有的合併、轉檔、ffprobe、配額檢查邏輯都在後端，幾乎不用改
- **Worker 更輕鬆**：收到的已經是 mp3，不需要再做格式轉換

#### 缺點與緩解

| 缺點 | 緩解方式 |
|------|---------|
| 大檔佔 Web Server 頻寬（用戶傳 500MB mp4 到後端） | 實際瓶頸是轉錄速度（分鐘級），上傳幾十秒的差異可忽略 |
| t3.small 記憶體有限（2GB） | ffmpeg 串流處理不會把整個檔案載入記憶體；同時多人上傳時升級到 t3.medium 即可 |
| 同時多人上傳可能阻塞 | 目前 Worker 最多 2 個併發任務，多人上傳也要排隊；規模到了直接升級 instance |

> **備註：前端直傳 S3 方案（Presigned URL）**
> 另一種做法是讓前端直接上傳到 S3，省去 Web Server 的頻寬負擔。
> 但由於影片檔需要提取音訊，直傳 S3 反而會讓原始大檔存入 S3，Worker 再下載轉換，
> 總網路流量更高（500 + 500 + 28 = 1028MB vs 後端中轉的 500 + 28 + 28 = 556MB）。
> 除非產品成長到同時數百人上傳的規模，否則後端中轉 + 升級 instance 是更務實的選擇。

---

## 4. 前端部署策略

兩個 Vue 3 前端 (user frontend + admin frontend) 均部署到 S3 + CloudFront。

### S3 Bucket 設定

- 建立兩個 Bucket（或同一 Bucket 不同 prefix）：
  - `transcriber-frontend` → 用戶端
  - `transcriber-admin` → 管理後台
- 啟用靜態網站託管
- Bucket Policy 允許 CloudFront OAI 讀取

### CloudFront 設定

- **Origins**：指向 S3 Bucket
- **Default Root Object**：`index.html`
- **Error Pages**：403/404 均導向 `index.html`（SPA fallback）
- **Cache Behavior**：
  - `/api/*` → 轉發到 Web Server (t3.small)
  - `/*` → 從 S3 讀取靜態檔案
- **SSL**：使用 ACM 憑證（免費）
- **備用方案**：也可在 t3.small 上用 nginx serve 前端靜態檔（省 CloudFront 費用，但效能差）

### 部署流程

```bash
# User Frontend
cd frontend && npm run build
aws s3 sync dist/ s3://transcriber-frontend/ --delete
aws cloudfront create-invalidation --distribution-id $DIST_ID --paths "/*"

# Admin Frontend
cd admin-frontend && npm run build
aws s3 sync dist/ s3://transcriber-admin/ --delete
aws cloudfront create-invalidation --distribution-id $DIST_ID --paths "/*"
```

---

## 5. HTTPS 與域名

### 方案：Caddy (Web Server 上)

在 t3.small 上使用 Caddy 作為 reverse proxy，自動管理 Let's Encrypt 憑證。

```
Caddyfile 範例：
api.your-domain.com {
    reverse_proxy localhost:8000
}
```

**優點**：
- 成本 $0（不需 ALB ~$22/月）
- 自動續約 SSL 憑證
- 設定簡單

**注意**：
- 需要域名 A record 指向 t3.small 的 Elastic IP
- 如果未來需要多台 Web Server 負載均衡，再改用 ALB

### DNS 設定 (Route 53)

| Record | Type | Target |
|--------|------|--------|
| `your-domain.com` | A (Alias) | CloudFront Distribution |
| `admin.your-domain.com` | A (Alias) | CloudFront Distribution (admin) |
| `api.your-domain.com` | A | EC2 Elastic IP (t3.small) |

---

## 6. 即時狀態回報方案

### 問題

現有架構使用 SSE (`GET /tasks/{task_id}/events`) 推送轉錄進度，依賴 in-memory 的 `transcription_tasks` dict。分離架構後 Web Server 和 AI Worker 在不同機器上，Web Server 無法直接取得 Worker 的進度。

### 解決方案：MongoDB Polling

AI Worker 處理過程中定期更新 MongoDB 的 task document：

```python
# AI Worker 端 - 更新進度
await task_repo.update_task(task_id, {
    "status": "processing",
    "progress": "正在轉錄 (45%)...",
    "progress_percentage": 45
})
```

Web Server 端 SSE endpoint 改為 polling MongoDB：

```python
# Web Server 端 - SSE endpoint
@router.get("/tasks/{task_id}/events")
async def task_events(task_id: str):
    async def event_generator():
        while True:
            task = await task_repo.get_task(task_id)
            yield f"data: {json.dumps(task['status_info'])}\n\n"
            if task["status"] in ("completed", "failed", "cancelled"):
                break
            await asyncio.sleep(2)  # 每 2 秒查一次
    return StreamingResponse(event_generator(), media_type="text/event-stream")
```

**優點**：
- 不需額外元件（不需 Redis）
- 利用現有 MongoDB 連線
- 延遲在 2-3 秒內，對轉錄任務可接受

**未來擴展**：
- 如果需要更即時的回報，可加入 Redis Pub/Sub

---

## 7. 密鑰管理

### 現況

所有密鑰存在 `.env` 檔案中。

### 遷移至 SSM Parameter Store

將敏感資訊存入 AWS Systems Manager Parameter Store（Standard tier 免費）：

| Parameter Name | 類型 | 說明 |
|---------------|------|------|
| `/transcriber/jwt-secret-key` | SecureString | JWT 簽名金鑰 |
| `/transcriber/mongodb-url` | SecureString | MongoDB Atlas 連線字串 |
| `/transcriber/google-api-key-1` | SecureString | Google Gemini API Key |
| `/transcriber/google-api-key-2` | SecureString | Google Gemini API Key |
| `/transcriber/google-api-key-3` | SecureString | Google Gemini API Key |
| `/transcriber/openai-api-key` | SecureString | OpenAI API Key |
| `/transcriber/hf-token` | SecureString | Hugging Face Token |
| `/transcriber/google-client-id` | SecureString | Google OAuth Client ID |
| `/transcriber/smtp-password` | SecureString | SMTP 密碼（過渡期）|

### 程式碼調整

```python
# 新增 config loader，優先從 SSM 讀取，fallback 到 .env
import boto3

def get_parameter(name: str, fallback_env: str = None) -> str:
    try:
        ssm = boto3.client('ssm', region_name='ap-northeast-1')
        response = ssm.get_parameter(Name=name, WithDecryption=True)
        return response['Parameter']['Value']
    except Exception:
        return os.getenv(fallback_env, "")
```

### IAM 權限

EC2 Instance Role 需要：

```json
{
    "Effect": "Allow",
    "Action": [
        "ssm:GetParameter",
        "ssm:GetParameters",
        "ssm:GetParametersByPath"
    ],
    "Resource": "arn:aws:ssm:ap-northeast-1:*:parameter/transcriber/*"
}
```

---

## 8. Email 服務遷移

### 現況

使用 Gmail SMTP（`src/utils/email_service.py`）。

### 遷移至 Amazon SES

**優點**：
- 每月 62,000 封免費（從 EC2 發送）
- 不依賴 Gmail App Password
- 高送達率

**設定步驟**：

1. 在 SES 驗證寄件域名（SPF/DKIM）
2. 申請移出 Sandbox（正式環境需要）
3. 修改 `email_service.py`，新增 SES 發信模式

```python
import boto3

ses_client = boto3.client('ses', region_name='ap-northeast-1')

async def send_email_ses(to: str, subject: str, html_body: str, text_body: str):
    ses_client.send_email(
        Source=f"{FROM_NAME} <{FROM_EMAIL}>",
        Destination={"ToAddresses": [to]},
        Message={
            "Subject": {"Data": subject},
            "Body": {
                "Html": {"Data": html_body},
                "Text": {"Data": text_body}
            }
        }
    )
```

### 過渡期

可保留 SMTP 作為 fallback，新增環境變數 `EMAIL_PROVIDER=ses|smtp` 切換。

---

## 9. CORS 與安全性

### CORS 設定

```python
# 生產環境 CORS_ORIGINS
CORS_ORIGINS="https://your-domain.com,https://admin.your-domain.com"
```

`src/main.py` 已支援此設定，無需改動程式碼。

### Security Group 規則

**Web Server (t3.small)**：
| Port | Source | 用途 |
|------|--------|------|
| 443 | 0.0.0.0/0 | HTTPS (Caddy) |
| 22 | 管理員 IP | SSH |

**AI Worker (g4dn.xlarge)**：
| Port | Source | 用途 |
|------|--------|------|
| 22 | 管理員 IP | SSH |
| (無對外 port) | - | 只透過 SQS 溝通 |

### 網路架構

Web Server 與 AI Worker 都部署在 **Public Subnet**，避免 NAT Gateway 費用 (~$45/月)。
- Web Server：分配 Elastic IP
- AI Worker：分配 Public IP（Spot 重啟會變，但不影響運作）
- 透過 Security Group 嚴格限制存取

---

## 10. 靜態加密 (Encryption at Rest)

所有儲存音檔、轉錄文字、使用者資料的元件都必須啟用 AES-256 靜態加密，確保資料在磁碟上不以明文存在。

### 加密覆蓋範圍

| 元件 | 加密方式 | AES-256 | 說明 |
|------|---------|---------|------|
| **S3 Bucket** | SSE-S3（預設） | ✅ | AWS 自 2023/01 起新建 Bucket 預設啟用 SSE-S3 (AES-256) |
| **MongoDB Atlas (M10+)** | WiredTiger Encrypted Storage Engine | ✅ | M10 以上方案內建 AES-256-CBC，自動加密所有資料檔案 |
| **MongoDB Atlas (M0 Free)** | 共享 Cluster，無獨立加密 | ❌ | Free Tier 不支援 Encryption at Rest |
| **EBS Volumes (EC2)** | AWS EBS Encryption | ✅ | 建立 Volume 時勾選 Encrypted，底層使用 AES-256 |
| **SSM Parameter Store** | SecureString (KMS) | ✅ | 已規劃使用 SecureString 類型，由 AWS KMS 加密 |

### S3 加密設定

AWS S3 自 2023 年 1 月起，所有新建的 Bucket 預設啟用 SSE-S3（AES-256），**不需額外設定也不增加費用**。

如果需要更高安全性（自訂金鑰管理、金鑰輪替稽核），可改用 SSE-KMS：

```bash
# 確認 Bucket 已啟用預設加密（通常已自動啟用）
aws s3api get-bucket-encryption --bucket transcriber-files

# 若需手動啟用 SSE-S3（AES-256）
aws s3api put-bucket-encryption --bucket transcriber-files \
  --server-side-encryption-configuration '{
    "Rules": [{
      "ApplyServerSideEncryptionByDefault": {
        "SSEAlgorithm": "AES256"
      },
      "BucketKeyEnabled": true
    }]
  }'

# （進階）改用 SSE-KMS 自訂金鑰
aws s3api put-bucket-encryption --bucket transcriber-files \
  --server-side-encryption-configuration '{
    "Rules": [{
      "ApplyServerSideEncryptionByDefault": {
        "SSEAlgorithm": "aws:kms",
        "KMSMasterKeyID": "arn:aws:kms:ap-northeast-1:ACCOUNT_ID:key/KEY_ID"
      },
      "BucketKeyEnabled": true
    }]
  }'
```

**拒絕未加密上傳**：加入 Bucket Policy 強制要求所有上傳都帶加密 header：

```json
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Sid": "DenyUnencryptedObjectUploads",
            "Effect": "Deny",
            "Principal": "*",
            "Action": "s3:PutObject",
            "Resource": "arn:aws:s3:::transcriber-files/*",
            "Condition": {
                "StringNotEquals": {
                    "s3:x-amz-server-side-encryption": "AES256"
                }
            }
        }
    ]
}
```

### EBS Volume 加密

Web Server (t3.small) 和 AI Worker (g4dn.xlarge) 的 EBS Volume 都應啟用加密：

```bash
# 方法 1：設定帳號層級預設加密（推薦，一次設定永久生效）
aws ec2 enable-ebs-encryption-by-default --region ap-northeast-1

# 方法 2：建立 EC2 時指定加密 Volume
aws ec2 run-instances \
  --block-device-mappings '[{
    "DeviceName": "/dev/xvda",
    "Ebs": {
      "VolumeSize": 30,
      "VolumeType": "gp3",
      "Encrypted": true
    }
  }]' \
  ...
```

> **注意**：EBS 加密不影響效能，也不增加費用（使用預設 AWS managed key）。建議直接啟用帳號層級預設加密。

### MongoDB Atlas 加密

| 方案 | Encryption at Rest | 說明 |
|------|-------------------|------|
| **M0 (Free)** | ❌ 不支援 | 共享 Cluster，AWS 層面的 EBS 加密由 Atlas 管理，但無法保證 AES-256 |
| **M10+** | ✅ 內建 AES-256-CBC | WiredTiger Encrypted Storage Engine，自動加密所有資料檔案、日誌、快照 |
| **M10+ with CMK** | ✅ AES-256 + 自訂金鑰 | 可整合 AWS KMS，使用自己的 Customer Managed Key |

**建議**：

- **MVP 階段（M0）**：接受 M0 不支援 at-rest 加密的限制。轉錄文字和 segment 資料存在 MongoDB，但 M0 無法啟用獨立加密。音檔本身存在 S3（已加密），風險集中在 MongoDB 中的文字資料。
- **正式環境**：升級到 M10 後，Encryption at Rest 自動啟用，無需額外設定。若需 CMK：
  1. 在 AWS KMS 建立一把 key
  2. MongoDB Atlas → Security → Encryption at Rest → 啟用並指定 KMS Key ARN
  3. Atlas 會用此 key 加密 WiredTiger 的 master key

### 傳輸加密 (Encryption in Transit) — 補充

靜態加密之外，傳輸層也需確保加密：

| 路徑 | 加密方式 | 狀態 |
|------|---------|------|
| Browser → CloudFront | HTTPS (TLS 1.2+) | ✅ ACM 憑證 |
| Browser → API Server | HTTPS (Caddy) | ✅ Let's Encrypt |
| API Server → MongoDB Atlas | TLS | ✅ Atlas 預設強制 TLS |
| API Server → S3 | HTTPS | ✅ AWS SDK 預設 HTTPS |
| API Server → SQS | HTTPS | ✅ AWS SDK 預設 HTTPS |

### 成本影響

| 加密元件 | 額外費用 |
|---------|---------|
| S3 SSE-S3 (AES-256) | **$0**（免費） |
| S3 SSE-KMS | $1/月/key + $0.03/10,000 requests |
| EBS Encryption（預設 key） | **$0**（免費） |
| MongoDB Atlas M10 Encryption | 包含在 M10 月費內 |
| SSM SecureString（預設 key） | **$0**（免費） |

> **結論**：使用 SSE-S3 + EBS 預設加密 + Atlas M10，可以達到完整的 AES-256 at rest 且**不額外增加費用**（M10 月費另計）。MVP 階段使用 M0 時，S3 和 EBS 仍可達到 AES-256，僅 MongoDB 層有缺口。

---

## 11. 監控與日誌

### CloudWatch Logs

在兩台 EC2 安裝 CloudWatch Agent，收集：

| Log Group | 來源 | 說明 |
|-----------|------|------|
| `/transcriber/web-server` | t3.small | FastAPI application logs |
| `/transcriber/ai-worker` | g4dn | Whisper 處理 logs |
| `/transcriber/caddy` | t3.small | HTTPS access logs |

### CloudWatch Alarms

| 警報 | 條件 | 動作 |
|------|------|------|
| Web Server Down | HealthCheck 失敗 2 次 | SNS 通知 |
| Worker CPU > 90% | 持續 10 分鐘 | SNS 通知 |
| SQS Queue Depth | 積壓 > 20 筆 | SNS 通知 |
| Spot Interruption | Instance 被回收 | SNS 通知 |

### Health Check

現有的 `/health` endpoint 可直接使用，無需修改。

---

## 12. CI/CD Pipeline

### GitHub Actions

```yaml
# .github/workflows/deploy.yml（概念）
name: Deploy

on:
  push:
    branches: [main]

jobs:
  deploy-frontend:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: cd frontend && npm ci && npm run build
      - run: aws s3 sync frontend/dist/ s3://transcriber-frontend/ --delete
      - run: aws cloudfront create-invalidation ...

  deploy-admin:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: cd admin-frontend && npm ci && npm run build
      - run: aws s3 sync admin-frontend/dist/ s3://transcriber-admin/ --delete
      - run: aws cloudfront create-invalidation ...

  deploy-backend:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: docker build -t transcriber-backend .
      - run: docker tag ... && docker push ...  # Push to ECR
      - run: ssh web-server "docker pull ... && docker restart ..."

  deploy-worker:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: docker build -f Dockerfile.worker -t transcriber-worker .
      - run: docker tag ... && docker push ...  # Push to ECR
      - run: ssh ai-worker "docker pull ... && docker restart ..."
```

### Docker Image 分離

目前只有一個 Dockerfile，需拆分為：
- `Dockerfile`：Web Server（輕量，不含 ML 套件）
- `Dockerfile.worker`：AI Worker（含 CUDA、whisper、pyannote）

---

## 13. 關鍵成本控制

### 1. AI Worker 使用 Spot Instance

- 設定 EC2 時勾選「Spot Request」
- 目標價格：約 **$0.20 USD/hr**（原價 $0.71），節省約 70%
- 設定 Spot Interruption Handler：收到中斷通知時完成當前 chunk 或標記任務為 pending

### 2. 彈性開關機 (Scale to Zero)

- **初期 (MVP)**：手動開機，或設定 Cron Job（例如僅在 09:00-24:00 運作）
- **後期**：設定 Auto Scaling Group 監控 SQS 佇列數量，沒任務自動縮減為 0 台

```
CloudWatch Alarm (SQS Depth > 0)
    → Auto Scaling Group (min=0, max=1, desired=1)
    → 啟動 g4dn.xlarge Spot Instance
    → 處理完畢、SQS 清空
    → 10 分鐘無任務 → 縮減為 0
```

### 3. 網路架構省錢法（避開 NAT Gateway）

- Web Server 與 AI Worker 都部署在 **Public Subnet**
- 分配 Public IP，透過 Security Group 鎖定端口
- **省下**：NAT Gateway 費用 (~$45 USD/月)

### 4. 預估月費（低用量場景）

| 項目 | 費用 (USD) |
|------|-----------|
| t3.small (24h) | ~$15 |
| g4dn.xlarge Spot (每日 2 小時) | ~$12 |
| MongoDB Atlas M0 | $0 |
| S3 (10GB) | ~$0.25 |
| CloudFront | ~$1-5 |
| Route 53 | ~$0.50 |
| CloudWatch | ~$1-5 |
| SES | ~$0 |
| SQS | ~$0 |
| **合計** | **~$30-38/月** |

---

## 14. MongoDB Atlas 注意事項

### M0 Free Tier 限制

| 項目 | 限制 |
|------|------|
| 儲存 | **512 MB** |
| 連線數 | 500 |
| 網路 | 共享 cluster |
| 自動備份 | 無 |
| Region | 限定選項 |

### 容量估算

- 一筆 30 分鐘轉錄的 segments JSON：約 200KB - 1MB
- 512MB 約可存 **500 - 2000 筆**轉錄紀錄
- 用戶資料、tags、audit logs 額外佔用空間

### 升級時機

當儲存接近 400MB 時，升級到 M10（~$57/月），獲得：
- 10GB 儲存
- 專屬 cluster
- 自動備份
- 更多連線數
- **Encryption at Rest (AES-256-CBC)**：WiredTiger 加密引擎自動加密所有資料檔案

### 建議

- 選擇 **AWS Tokyo (ap-northeast-1)** region，降低延遲
- 設定 VPC Peering 或 Private Endpoint（M10 以上支援）
- 啟用 IP Access List，僅允許 EC2 IP 連線
- **加密**：M0 不支援 Encryption at Rest，升級 M10 後自動啟用（詳見[第 10 節](#10-靜態加密-encryption-at-rest)）

---

## 15. 本地開發與 AWS 並行策略

### 核心思路

用一個環境變數 `DEPLOY_ENV` 控制服務切換，本地開發時完全不需要 AWS 帳號。

```bash
# .env（本地開發）          # AWS 環境變數
DEPLOY_ENV=local            DEPLOY_ENV=aws
```

### 哪些需要切換、怎麼切換

| 服務 | 本地 | AWS | 出現位置 | 切換方式 |
|------|------|-----|---------|---------|
| 檔案儲存 | 本機 `uploads/`、`output/` | S3 | 散佈 4-5 個檔案 | **建立 `storage_service.py`** |
| 資料庫 | localhost MongoDB | Atlas | `mongodb.py` 一處 | 改 `MONGODB_URL` 即可（**不用改程式碼**） |
| 任務派發 | 直接呼叫 service | SQS | `transcriptions.py` 一處 | `if/else` 分支 |
| Model 載入 | 載入 Whisper | 不載入（Web Server） | `main.py` 一處 | `if/else` 分支 |
| SSE 狀態 | in-memory dict | MongoDB polling | `tasks.py` 一處 | `if/else` 分支 |
| Email | Console / SMTP | SES | `email_service.py` 一處 | 已有 fallback，加 SES 分支 |
| 密鑰 | `.env` 檔案 | SSM Parameter Store | `main.py` 載入處 | `config_loader.py` |

**原則**：只有「檔案儲存」散佈在多處，值得建抽象層。其他都只出現一兩個地方，用 `if/else` 就夠。

### 檔案儲存：`storage_service.py`（唯一需要抽象的服務）

檔案操作（`shutil.move`、`Path("uploads/")`、`FileResponse`）散佈在 `transcriptions.py`、`transcription_service.py`、`audio.py`、`tasks.py`。用一個 module 封裝，內部根據 `DEPLOY_ENV` 自動切換：

```python
# src/utils/storage_service.py
import os, shutil
from pathlib import Path

DEPLOY_ENV = os.getenv("DEPLOY_ENV", "local")
S3_BUCKET = os.getenv("S3_BUCKET", "")

if DEPLOY_ENV == "aws":
    import boto3
    _s3 = boto3.client("s3", region_name="ap-northeast-1")


def save_audio(task_id: str, local_path: Path) -> str:
    """儲存音檔（上傳後呼叫）"""
    key = f"uploads/{task_id}.mp3"
    if DEPLOY_ENV == "aws":
        _s3.upload_file(str(local_path), S3_BUCKET, key)
        local_path.unlink(missing_ok=True)
        return f"s3://{S3_BUCKET}/{key}"
    else:
        dest = Path("uploads") / f"{task_id}.mp3"
        dest.parent.mkdir(exist_ok=True)
        shutil.move(str(local_path), str(dest))
        return str(dest)


def get_audio_url(task_id: str) -> str:
    """取得音檔下載連結"""
    key = f"uploads/{task_id}.mp3"
    if DEPLOY_ENV == "aws":
        return _s3.generate_presigned_url(
            "get_object",
            Params={"Bucket": S3_BUCKET, "Key": key},
            ExpiresIn=3600,
        )
    else:
        return f"/api/audio/{task_id}"


def download_audio(task_id: str, dest: Path) -> Path:
    """下載音檔到本機（Worker 用）"""
    if DEPLOY_ENV == "aws":
        _s3.download_file(S3_BUCKET, f"uploads/{task_id}.mp3", str(dest))
    else:
        shutil.copy2(str(Path("uploads") / f"{task_id}.mp3"), str(dest))
    return dest


def delete_audio(task_id: str) -> None:
    """刪除音檔"""
    if DEPLOY_ENV == "aws":
        _s3.delete_object(Bucket=S3_BUCKET, Key=f"uploads/{task_id}.mp3")
    else:
        Path(f"uploads/{task_id}.mp3").unlink(missing_ok=True)


def save_output(task_id: str, filename: str, local_path: Path) -> str:
    """儲存輸出檔案（轉錄結果 TXT/JSON 等）"""
    key = f"output/{task_id}/{filename}"
    if DEPLOY_ENV == "aws":
        _s3.upload_file(str(local_path), S3_BUCKET, key)
        return f"s3://{S3_BUCKET}/{key}"
    else:
        dest = Path("output") / task_id / filename
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(local_path), str(dest))
        return str(dest)


def get_output_url(task_id: str, filename: str) -> str:
    """取得輸出檔案下載連結"""
    key = f"output/{task_id}/{filename}"
    if DEPLOY_ENV == "aws":
        return _s3.generate_presigned_url(
            "get_object",
            Params={"Bucket": S3_BUCKET, "Key": key},
            ExpiresIn=3600,
        )
    else:
        return f"/api/transcriptions/{task_id}/download/{filename}"
```

不需要 Protocol、不需要 class、不需要 factory function。import 這個 module 就能直接用。

### 其他服務：直接 `if/else`（不需要抽象）

每個只出現在一兩個地方，直接在原地加分支即可：

```python
# === transcriptions.py — 任務派發 ===
DEPLOY_ENV = os.getenv("DEPLOY_ENV", "local")

if DEPLOY_ENV == "aws":
    # 發送到 SQS，Worker 會接手
    import boto3, json
    sqs = boto3.client("sqs")
    sqs.send_message(
        QueueUrl=os.getenv("SQS_QUEUE_URL"),
        MessageBody=json.dumps({"task_id": task_id}),
    )
else:
    # 本地模式：直接呼叫（現有行為不變）
    await transcription_service.start_transcription(task_id, ...)


# === main.py — Model 載入 ===
DEPLOY_ENV = os.getenv("DEPLOY_ENV", "local")
APP_ROLE = os.getenv("APP_ROLE", "server")

if DEPLOY_ENV == "local" or APP_ROLE == "worker":
    # 本地開發 或 AWS Worker：載入 Whisper
    model = WhisperModel("medium", device="cuda")
else:
    # AWS Web Server：不載入，省記憶體
    model = None


# === tasks.py — SSE 狀態 ===
if DEPLOY_ENV == "aws":
    # 從 MongoDB 輪詢（Web Server 沒有 in-memory 狀態）
    task = await task_repo.get_task(task_id)
    yield f"data: {json.dumps(task['progress'])}\n\n"
    await asyncio.sleep(2)
else:
    # 本地：用現有的 in-memory dict（不用改）
    ...  # 現有程式碼
```

### .env 範例

```bash
# ===== 通用設定 =====
MONGODB_URL="mongodb://localhost:27017"
MONGODB_DB_NAME="whisper_transcriber"
JWT_SECRET_KEY="your-secret"
CORS_ORIGINS="http://localhost:3000,http://localhost:5173"

# ===== 部署環境 =====
DEPLOY_ENV=local          # local | aws
# APP_ROLE=server         # server | worker（AWS 才需要）

# ===== AWS 設定（DEPLOY_ENV=aws 時才需要）=====
# S3_BUCKET=transcriber-files
# SQS_QUEUE_URL=https://sqs.ap-northeast-1.amazonaws.com/123456/transcriber-tasks
# EMAIL_PROVIDER=ses

# ===== 本地開發設定 =====
EMAIL_PROVIDER=console    # console（印到終端）| smtp | ses
GOOGLE_API_KEY_1="..."
OPENAI_API_KEY="..."
HF_TOKEN="..."
```

### 開發流程不變

```bash
# 本地開發（跟現在完全一樣）
cp .env.example .env        # DEPLOY_ENV=local
python src/main.py           # Whisper + API 全部在同一台

# AWS 部署
# Web Server: DEPLOY_ENV=aws APP_ROLE=server
# AI Worker:  DEPLOY_ENV=aws APP_ROLE=worker
```

---

## 16. 程式碼需調整項目

| 檔案 | 調整內容 | 說明 |
|------|---------|------|
| 新增 `src/utils/storage_service.py` | 檔案儲存封裝（`save_audio`、`get_audio_url`、`download_audio` 等） | 唯一需要獨立模組的服務 |
| 新增 `src/utils/config_loader.py` | SSM Parameter Store 讀取 + .env fallback | AWS 密鑰管理 |
| 新增 `src/worker.py` | AI Worker 主程式（監聽 SQS → 下載 S3 mp3 → 轉錄 → 回寫） | `DEPLOY_ENV=aws APP_ROLE=worker` 時的入口 |
| `src/main.py` | 根據 `DEPLOY_ENV` + `APP_ROLE` 決定是否載入 Whisper | `if/else` 分支 |
| `src/routers/transcriptions.py` | 檔案操作改用 `storage_service`；任務派發加 SQS 分支；加入音訊提取 | 複用現有 `_convert_audio_to_mp3` |
| `src/routers/tasks.py` | AWS 模式下 SSE 改為 MongoDB polling；本地模式保留 in-memory | `if/else` 分支 |
| `src/routers/audio.py` | 音檔存取改用 `storage_service` | 不再直接讀 `/uploads/` |
| `src/services/transcription_service.py` | 檔案讀寫改用 `storage_service` | `_cleanup_temp_files` 等方法 |
| `src/utils/email_service.py` | 新增 SES 發信模式，根據 `EMAIL_PROVIDER` 切換 | 已有 console fallback，加一個分支 |
| `Dockerfile` | 拆成 `Dockerfile`（Web，不含 ML）+ `Dockerfile.worker`（含 CUDA/whisper） | Web ~500MB，Worker ~10GB+ |
| `src/auth/dependencies.py` | 確認 JWT 在分散式環境正常（目前用 DB 驗證，應無問題） | 驗證即可，可能不用改 |

**前端不需要改動** — 上傳方式維持原有的 multipart form POST。

---

## 17. 部署步驟

> 本地開發不需要執行以下步驟，只需 `DEPLOY_ENV=local` 即可照常運作。

### 第一階段：環境準備

- [ ] 申請 AWS 帳號（如果還沒有）
- [ ] MongoDB Atlas 註冊帳號，建立 Free Cluster（AWS Tokyo）
- [ ] AWS S3：建立 Bucket，設定 CORS，設定 Lifecycle Rule（`temp/` 7 天刪除），確認 SSE-S3 加密已啟用
- [ ] AWS SQS：建立 Standard Queue，取得 Queue URL
- [ ] AWS IAM：建立 EC2 Instance Role，授權 S3、SQS、SSM、SES
- [ ] AWS SSM Parameter Store：寫入所有密鑰
- [ ] 購買域名 / 設定 Route 53 Hosted Zone

### 第二階段：程式碼改造

- [ ] 新增 `src/utils/storage_service.py`（檔案儲存封裝）
- [ ] 新增 `src/utils/config_loader.py`（SSM + .env 讀取）
- [ ] 修改 `transcriptions.py`：上傳流程加入音訊提取（mp4→mp3），檔案操作改用 `storage_service`，任務派發加 SQS `if/else`
- [ ] 修改 `tasks.py`：SSE endpoint 加 MongoDB polling `if/else`
- [ ] 修改 `main.py`：根據 `DEPLOY_ENV` + `APP_ROLE` 決定是否載入 Whisper
- [ ] 修改 `audio.py`、`transcription_service.py`：檔案操作改用 `storage_service`
- [ ] 新增 `worker.py`（SQS consumer：下載 S3 mp3 → 轉錄 → 寫回 MongoDB + S3）
- [ ] 拆分 Dockerfile（Web 版 + Worker 版）
- [ ] 本地測試 Web + Worker 分離運作
- [ ] （前端不需要改動，上傳維持 multipart form）

### 第三階段：Web Server 部署

- [ ] 開一台 `t3.small`，分配 Elastic IP
- [ ] 安裝 Docker、Caddy
- [ ] 部署 Web Server container
- [ ] 設定 Caddy HTTPS reverse proxy
- [ ] 測試：API 回應、S3 Presigned URL 產生、SQS 訊息發送

### 第四階段：AI Worker 部署

- [ ] 準備 Worker Dockerfile（Python, ffmpeg, CUDA, faster-whisper, pyannote）
- [ ] 開一台 `g4dn.xlarge` **Spot Instance**
- [ ] 部署 Worker container
- [ ] 測試：丟一個音檔，確認完整流程（上傳 → SQS → 轉錄 → MongoDB 出現結果）

### 第五階段：前端部署

- [ ] 建立 S3 Bucket（frontend + admin）
- [ ] 設定 CloudFront Distribution（SPA fallback、HTTPS）
- [ ] build 前端並上傳 S3
- [ ] 設定 DNS（Route 53）
- [ ] 測試：完整用戶流程

### 第六階段：穩定化

- [ ] 安裝 CloudWatch Agent（雙機器）
- [ ] 設定 CloudWatch Alarms（健康檢查、SQS 積壓、Spot 中斷）
- [ ] Email 遷移至 SES
- [ ] 設定 GitHub Actions CI/CD
- [ ] Spot Interruption Handler（graceful shutdown）
- [ ] 壓力測試、安全性檢查

### 第七階段：自動化擴展（後期）

- [ ] Auto Scaling Group 監控 SQS，自動啟停 GPU Worker
- [ ] MongoDB Atlas 升級評估（根據用量）
- [ ] 成本監控 Dashboard（AWS Cost Explorer）

---

## 18. 待辦事項檢查清單

### 帳號與服務申請
- [ ] AWS 帳號
- [ ] MongoDB Atlas 帳號（M0 Free Cluster, AWS Tokyo）
- [ ] 域名購買 / 轉移

### AWS 資源建立
- [ ] S3 Bucket + CORS + Lifecycle Rule + 確認 SSE-S3 加密
- [ ] SQS Standard Queue
- [ ] IAM Role（EC2 用，含 S3/SQS/SSM/SES 權限）
- [ ] SSM Parameter Store（寫入所有密鑰，使用 SecureString 類型）
- [ ] Route 53 Hosted Zone
- [ ] ACM 憑證（CloudFront 用，需在 us-east-1）
- [ ] CloudFront Distribution x2（frontend + admin）
- [ ] EC2 t3.small + Elastic IP + **EBS 加密啟用**
- [ ] EC2 g4dn.xlarge Spot Request + **EBS 加密啟用**
- [ ] **啟用帳號層級 EBS 預設加密**（`aws ec2 enable-ebs-encryption-by-default`）
- [ ] Security Groups（Web / Worker）
- [ ] SES 域名驗證 + 申請移出 Sandbox

### 程式碼改造
- [ ] `src/utils/storage_service.py` — 檔案儲存封裝（唯一獨立模組）
- [ ] `src/utils/config_loader.py` — SSM + .env 讀取
- [ ] `src/worker.py` — AI Worker 主程式
- [ ] 修改 `transcriptions.py` — 音訊提取 + `storage_service` + SQS 分支
- [ ] 修改 `tasks.py` — SSE polling 分支
- [ ] 修改 `audio.py`、`transcription_service.py` — `storage_service` 替換檔案操作
- [ ] 修改 `main.py` — Whisper 載入分支
- [ ] 修改 `email_service.py` — SES 分支
- [ ] 拆分 Dockerfile（Web / Worker）
- [ ] Google OAuth redirect URI 更新
- [ ] 前端不需改動（維持 multipart 上傳）

### 測試與驗證
- [ ] 本地 `DEPLOY_ENV=local` 完整功能測試（確認沒壞）
- [ ] S3 上傳/下載流程測試
- [ ] SQS 訊息收發測試
- [ ] 完整轉錄流程端到端測試
- [ ] Spot 中斷恢復測試
- [ ] HTTPS 與 CORS 測試
- [ ] Email 發送測試（SES）

### 靜態加密驗證
- [ ] 確認 S3 Bucket 預設加密為 SSE-S3 (AES-256)（`aws s3api get-bucket-encryption`）
- [ ] 確認 EBS Volumes 已加密（`aws ec2 describe-volumes --filters Name=encrypted,Values=true`）
- [ ] 確認帳號層級 EBS 預設加密已啟用
- [ ] 確認 MongoDB Atlas 連線使用 TLS（連線字串含 `tls=true`）
- [ ] 升級 M10 後確認 Encryption at Rest 狀態（Atlas Dashboard → Security）

### 部署後
- [ ] CloudWatch Logs 確認收集正常
- [ ] CloudWatch Alarms 測試告警
- [ ] GitHub Actions CI/CD 設定
- [ ] 成本追蹤（每週檢視 Cost Explorer）
- [ ] 備份策略確認
