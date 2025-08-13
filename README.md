# Whisper 逐字稿 + Gemini 標點（純前端）

1. 進入 `index.html`，把 `GEMINI_API_KEY` 改成你的金鑰。
2. 到 Google Cloud → API Key 設定 → **Application restrictions** 選 **HTTP referrers**，
   加入 `https://<username>.github.io/*`（你的 GitHub Pages 網域）。
3. Push 到 GitHub，打開 GitHub Pages。
4. 首次載入模型較慢；選檔 → 按「轉逐字稿」→ 完成後按「Gemini 加標點」。
