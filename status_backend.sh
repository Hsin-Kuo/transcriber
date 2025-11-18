#!/bin/bash

# 狀態腳本：檢查後端服務運行狀態
# 用法：bash status_backend.sh

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PID_FILE="$SCRIPT_DIR/backend.pid"
LOG_FILE="$SCRIPT_DIR/backend.log"

echo "📊 Whisper 後端服務狀態"
echo "========================"
echo ""

# 檢查 PID 檔案
if [ ! -f "$PID_FILE" ]; then
    echo "狀態：❌ 未運行"
    echo ""
    echo "啟動服務："
    echo "  bash start_backend_daemon.sh"
    exit 0
fi

PID=$(cat "$PID_FILE")

# 檢查進程是否存在
if ! ps -p $PID > /dev/null 2>&1; then
    echo "狀態：❌ 已停止（PID 檔案過期）"
    rm "$PID_FILE"
    exit 0
fi

# 服務正在運行
echo "狀態：✅ 運行中"
echo "進程 ID：$PID"
echo "API 端點：http://localhost:8000"
echo ""

# 顯示進程資訊
echo "進程資訊："
ps -p $PID -o pid,ppid,%cpu,%mem,etime,command | tail -n 1
echo ""

# 檢查 API 是否響應
if command -v curl > /dev/null 2>&1; then
    echo "API 健康檢查："
    if curl -s http://localhost:8000/health > /dev/null 2>&1; then
        echo "  ✅ API 正常響應"
    else
        echo "  ⚠️  API 無響應（可能正在啟動中）"
    fi
    echo ""
fi

# 顯示最後 10 行日誌
if [ -f "$LOG_FILE" ]; then
    echo "最近日誌（最後 10 行）："
    echo "---"
    tail -n 10 "$LOG_FILE"
    echo "---"
    echo ""
    echo "查看完整日誌：tail -f $LOG_FILE"
fi

echo ""
echo "管理指令："
echo "  停止服務：bash stop_backend.sh"
echo "  重啟服務：bash stop_backend.sh && bash start_backend_daemon.sh"
