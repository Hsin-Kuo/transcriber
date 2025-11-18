#!/bin/bash

# 啟動腳本：在本地運行 Whisper 後端（不使用 Docker）
# 用法：bash run_native_backend.sh

set -e

# 檢查虛擬環境
if [ ! -d "venv" ]; then
    echo "❌ 找不到虛擬環境，請先運行：bash setup_native_backend.sh"
    exit 1
fi

# 激活虛擬環境
echo "🔌 激活虛擬環境..."
source venv/bin/activate

# 檢查 .env 文件
if [ ! -f ".env" ]; then
    echo "❌ 找不到 .env 文件，請先設置："
    echo "   cp .env.example .env"
    echo "   然後編輯 .env 文件填入 API keys"
    exit 1
fi

# 載入環境變數
echo "📋 載入環境變數..."
export $(cat .env | grep -v '^#' | xargs)

# 創建必要目錄
mkdir -p output
mkdir -p temp

# 啟動後端
echo "🚀 啟動 Whisper 後端服務..."
echo "📍 API 端點：http://localhost:8000"
echo "📍 前端應該連接到：localhost:8000"
echo ""
echo "按 Ctrl+C 停止服務"
echo ""

# 使用 uvicorn 直接運行
cd src
python3 -m uvicorn whisper_server:app --host 0.0.0.0 --port 8000 --reload
