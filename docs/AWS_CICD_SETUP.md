# AWS CI/CD 部署設定

## 概述

當程式碼 merge 進 `aws` 分支時，GitHub Actions 會自動：
1. 打包並部署後端到 EC2
2. 建置並部署前端到 EC2
3. 重啟服務並驗證部署

## 設定 GitHub Secrets

在 GitHub Repository → Settings → Secrets and variables → Actions 添加以下 secrets：

| Secret 名稱 | 說明 | 如何取得 |
|------------|------|----------|
| `EC2_SSH_KEY` | EC2 SSH 私鑰 | `cat ~/.ssh/transcriber-key.pem` |
| `GOOGLE_CLIENT_ID` | Google OAuth Client ID | Google Cloud Console |

### 設定步驟

1. **取得 SSH 私鑰**
   ```bash
   cat ~/.ssh/transcriber-key.pem
   ```
   複製完整內容（包含 `-----BEGIN RSA PRIVATE KEY-----` 和 `-----END RSA PRIVATE KEY-----`）

2. **添加 Secret**
   - 前往 GitHub 專案頁面
   - Settings → Secrets and variables → Actions
   - 點擊 "New repository secret"
   - 添加 `EC2_SSH_KEY` 和 `GOOGLE_CLIENT_ID`

## 建立 aws 分支

```bash
# 從 main 建立 aws 分支
git checkout main
git pull origin main
git checkout -b aws
git push -u origin aws
```

## 部署流程

### 自動部署
```bash
# 在任意功能分支開發完成後
git checkout aws
git merge feature/your-feature
git push origin aws
# GitHub Actions 會自動部署
```

### 監控部署
- 前往 GitHub → Actions 查看部署進度
- 部署成功後會顯示 ✅
- 失敗時可查看詳細日誌排查問題

## 架構說明

```
┌─────────────────┐     ┌─────────────────┐
│   GitHub        │     │   AWS EC2       │
│                 │     │                 │
│  aws branch     │────▶│  Backend        │
│  merge trigger  │     │  (port 8000)    │
│                 │     │                 │
│  GitHub Actions │     │  Frontend       │
│  - Build        │     │  (Nginx :80)    │
│  - Deploy       │     │                 │
└─────────────────┘     └─────────────────┘
```

## 注意事項

1. **敏感資訊**：JWT 密鑰、MongoDB URL 等已存在 AWS SSM Parameter Store，不需要在 GitHub Secrets 設定

2. **首次部署**：需要確保 EC2 已經完成初始設定（systemd 服務、Nginx 等）

3. **回滾**：如果部署出問題，可以在 GitHub Actions 重跑之前成功的部署

## 疑難排解

### 部署失敗
1. 檢查 GitHub Actions 日誌
2. SSH 到 EC2 檢查服務狀態：
   ```bash
   ssh -i ~/.ssh/transcriber-key.pem ec2-user@3.112.209.96
   sudo systemctl status transcriber
   sudo journalctl -u transcriber -n 50
   ```

## 網站網址

- **Production**: https://soundlite.app
- **EC2 Direct**: http://3.112.209.96 (backup)

### SSH 連線失敗
- 確認 EC2 Security Group 允許 GitHub Actions IP
- 或使用 `0.0.0.0/0` 允許所有 IP（測試用）
