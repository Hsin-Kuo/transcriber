# IAM 最小權限 role（canonical）

這裡是 EC2 instance profile 的 **唯一來源**。與 `deploy/` 底下的 nginx / systemd 同理：
**不要在 AWS Console 手改 policy**，改這裡再跑腳本同步。

## 為什麼存在

原本五台 EC2（prod web / prod spot / prod ondemand / staging web / staging gpu）**共用**
`transcriber-ec2-role`，其 policy 同時放行 `/transcriber/*` 與 `/transcriber-staging/*`。
後果是 staging 上任何能執行的程式碼（含 pip 依賴）都能讀到 prod 的 `mongodb-url`、
`jwt-secret`、`card-token-kek`、金流密鑰——等同 prod 全破，且 CloudFront Access
完全擋不到（它只覆蓋 :80 的 HTTP 路徑）。

拆開後，爆炸半徑從「整個 prod」縮小到「單一環境的單一角色」。

## 角色與權限

| | prod-web | prod-worker | staging-web | staging-worker |
|---|---|---|---|---|
| SSM 參數 | `/transcriber/` 11 項（jwt、金流、寄信） | `/transcriber/` 5 項（db、gemini、hf） | `/transcriber-staging/` 同 web | `/transcriber-staging/` 同 worker |
| S3 | prod bucket | prod bucket | staging bucket | staging bucket |
| SQS | **只能 Send** | **只能 Receive/Delete** | 只能 Send | 只能 Receive/Delete |
| `ec2:StopInstances` | ❌ | 限 tag=`transcriber-gpu-worker`/`-ondemand` | ❌ | 限 tag=`transcriber-gpu-staging` |
| `ses:SendEmail` | ❌（生產走 Resend） | ❌ | ❌ | ❌ |

權限清單依據：`WEB` 對應 `src/main.py`、`src/routers/`、`src/utils/{payments91,smilepay,
email_service,card_token_cipher}_*`；`WORKER` 對應 `src/worker_core/{config,model_cache}.py`。
worker 完全沒有引用 email / payment / jwt 任何模組，故結構性拿不到金流密鑰。

## ⚠️ 兩個會讓 policy 靜默失效的陷阱

1. **`AmazonSSMManagedInstanceCore`（Session Manager 必需）內含
   `ssm:GetParameter` 且 `Resource: "*"`**。IAM 多 policy 取聯集，它會把上面的參數範圍
   整個架空。因此每份 policy 都有 `DenyAnyOtherParameter`（explicit Deny 優先於任何
   Allow）。`NotResource` 保留 `arn:aws:ssm:*:*:parameter/aws/*` 給 ssm-agent 讀
   patch baseline 等公開參數。
2. **舊 `transcriber-ec2-policy` 的 `EC2SelfStop` 是 `instance/*` 無 Condition**，
   把 inline policy 漂亮的 tag condition 完全抵銷——任一台可停全帳號 EC2。同型錯誤。

教訓：**policy 寫好不等於生效**。切換任何實例前一律先跑 `verify-isolation.sh`。

## 操作

```bash
# 1. 改權限 → 重新產生 JSON → 推上 AWS（建立新 policy 版本並設為預設）
python3 deploy/iam/generate-policies.py
bash deploy/iam/update-policies.sh

# 2. 驗證隔離真的生效（唯讀，不改任何東西）
bash deploy/iam/verify-isolation.sh

# 3. 切換實例（會自動開機 + reboot）
bash deploy/iam/switch-instance-profile.sh i-01a34a514d56269db transcriber-staging-worker-profile

# 回滾
bash deploy/iam/switch-instance-profile.sh i-01a34a514d56269db transcriber-ec2-profile

# 首次建立（policy + role + instance profile，已執行過，重跑會 EntityAlreadyExists）
bash deploy/iam/create-roles.sh
```

## 切換 SOP

一次一台，每台之間驗證，**staging 先於 prod、worker 先於 web**：

1. `verify-isolation.sh` 全綠
2. `switch-instance-profile.sh <id> <profile>`
3. 驗證：
   - worker → 送真實轉錄任務，log 要有 `Found credentials from IAM Role: <新 role>`、
     `transcription.run.completed`，且 `AccessDenied` 計數為 0
   - web → 登入（jwt）、OAuth（google-client-id）、上傳（S3+SQS）、金流頁、寄信
4. 有問題就回滾（秒級生效），沒問題才切下一台

### 踩雷

- `ReplaceIamInstanceProfileAssociation` **需要實例在 running 狀態**。停機中的 association
  顯示 `associated`，API 仍回 `IncorrectState: not the active association`。腳本會自動先開機。
- `modify-instance-attribute` **沒有** `--iam-instance-profile` 選項。
- 換完 profile **一定要 reboot 或重啟服務**：進程在啟動時就把 SSM 參數讀進記憶體了，
  不重開等於沒驗到新 role。
- **GPU worker 閒置 3 分鐘自關**（`auto_shutdown_minutes: 3`），切換後要立刻送任務，
  否則機器會先關掉。
- simulate `ec2:StopInstances` 時 **tag condition 要自己傳 context**，
  否則恆為 `implicitDeny`（看起來像壞了，其實沒有）。
- 用 zsh 組 ARN 時 `$VAR:role` 的 `:r` 會被當成參數修飾符吃掉（`:t` 同理）——一律寫 `${VAR}`。

## 進度

- ✅ 四組 policy / role / instance profile 已建立（policy v2）
- ✅ 五台皆有 `Env` tag（`prod` / `staging`）
- ✅ staging GPU worker `i-01a34a514d56269db` 已切換，2026-10-01 真實任務驗綠
- ⬜ staging web `i-0e328071b52856681`
- ⬜ prod worker `i-0d133cca8e6ce23c2`、`i-058f381c59210c00a`
- ⬜ prod web `i-099bcb529f335d20b`
- ⬜ 全部切完後刪除 `transcriber-ec2-policy` / `transcriber-ec2-role` / `transcriber-ec2-profile`
      （含其 inline `ec2-self-stop`）

## 後續可做

- SSM SecureString 目前用預設的 `alias/aws/ssm`，IAM 是唯一屏障。改用 customer-managed
  KMS key（prod 一把、staging 一把）可讓 staging 在密碼學上就解不開 prod 參數。
- `/transcriber/google-api-key`（無後綴）是 legacy 殘留，程式只用 `-1`/`-2`，確認後可刪。
- `/transcriber/resend-webhook-secret` 程式有讀但兩個環境的 SSM 都沒有，目前靠 `.env`
  fallback；policy 已預留，seed 進 SSM 即生效。
