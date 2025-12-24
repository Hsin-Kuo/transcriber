#!/bin/bash

# 啟動腳本：在背景運行 Whisper 後端（守護進程模式）
# 用法：bash start_backend_daemon.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_FILE="$SCRIPT_DIR/backend.log"
PID_FILE="$SCRIPT_DIR/backend.pid"

# 檢查是否已在運行
if [ -f "$PID_FILE" ]; then
    PID=$(cat "$PID_FILE")
    if ps -p $PID > /dev/null 2>&1; then
        echo "⚠️  後端服務已在運行中 (PID: $PID)"
        echo "   查看日誌：tail -f $LOG_FILE"
        echo "   停止服務：bash stop_backend.sh"
        exit 1
    else
        echo "清理過期的 PID 檔案..."
        rm "$PID_FILE"
    fi
fi

# 檢查虛擬環境
if [ ! -d "$SCRIPT_DIR/venv" ]; then
    echo "❌ 找不到虛擬環境，請先運行：bash setup_native_backend.sh"
    exit 1
fi

# 檢查 .env
if [ ! -f "$SCRIPT_DIR/.env" ]; then
    echo "❌ 找不到 .env 文件，請先設置 API keys"
    exit 1
fi

echo "🚀 啟動 Whisper 後端服務（守護進程模式）..."

# 激活虛擬環境
source "$SCRIPT_DIR/venv/bin/activate"

# 載入環境變數（安全方式，避免特殊字符問題）
set -a
source "$SCRIPT_DIR/.env"
set +a

# 設置 PYTHONPATH
export PYTHONPATH="$SCRIPT_DIR"

# 創建必要目錄
mkdir -p "$SCRIPT_DIR/output"
mkdir -p "$SCRIPT_DIR/temp"

# 在背景啟動服務，輸出到日誌檔（從專案根目錄運行）
cd "$SCRIPT_DIR"
nohup uvicorn src.main:app --host 0.0.0.0 --port 8000 > "$LOG_FILE" 2>&1 &

# 保存 PID
echo $! > "$PID_FILE"

echo "✅ 後端服務已在背景啟動"
echo ""
echo "📍 API 端點："
echo "   - http://localhost:8000"
echo "   - http://100.66.247.23:8000"
echo "📋 日誌檔案：$LOG_FILE"
echo "🔢 進程 ID：$(cat $PID_FILE)"
echo ""
echo "實用指令："
echo "  查看日誌：tail -f $LOG_FILE"
echo "  查看狀態：bash status_backend.sh"
echo "  停止服務：bash stop_backend.sh"
echo ""
echo "💡 提示：現在可以安全關閉終端，服務會持續運行"
