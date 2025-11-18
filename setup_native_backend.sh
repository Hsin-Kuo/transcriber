#!/bin/bash

# 設置腳本：為本地運行後端創建 Python 虛擬環境
# 用法：bash setup_native_backend.sh

set -e

echo "🔧 開始設置原生後端環境..."

# 檢查 Python 版本
if ! command -v python3 &> /dev/null; then
    echo "❌ 找不到 python3，請先安裝 Python 3.10+"
    exit 1
fi

PYTHON_VERSION=$(python3 --version | awk '{print $2}')
echo "✅ 找到 Python $PYTHON_VERSION"

# 創建虛擬環境
if [ ! -d "venv" ]; then
    echo "📦 創建虛擬環境..."
    python3 -m venv venv
else
    echo "ℹ️  虛擬環境已存在"
fi

# 激活虛擬環境
echo "🔌 激活虛擬環境..."
source venv/bin/activate

# 升級 pip
echo "⬆️  升級 pip..."
pip install --upgrade pip

# 安裝依賴
echo "📚 安裝依賴套件..."
pip install -r requirements.txt

# 創建輸出目錄
echo "📁 創建必要目錄..."
mkdir -p output
mkdir -p temp

# 檢查 .env 文件
if [ ! -f ".env" ]; then
    echo "⚠️  警告：找不到 .env 文件"
    echo "📝 請複製 .env.example 並填入 API keys："
    echo "   cp .env.example .env"
    echo "   然後編輯 .env 文件"
else
    echo "✅ .env 文件已存在"
fi

echo ""
echo "✨ 設置完成！"
echo ""
echo "下一步："
echo "1. 確保 .env 文件已配置好 API keys"
echo "2. 運行後端：bash run_native_backend.sh"
echo "3. 在另一個終端運行前端：docker-compose up frontend"
