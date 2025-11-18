#!/bin/bash

# 停止腳本：停止背景運行的 Whisper 後端
# 用法：bash stop_backend.sh

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PID_FILE="$SCRIPT_DIR/backend.pid"

if [ ! -f "$PID_FILE" ]; then
    echo "⚠️  找不到 PID 檔案，後端可能未運行"
    exit 1
fi

PID=$(cat "$PID_FILE")

if ! ps -p $PID > /dev/null 2>&1; then
    echo "⚠️  進程 $PID 不存在，可能已停止"
    rm "$PID_FILE"
    exit 1
fi

echo "🛑 正在停止後端服務 (PID: $PID)..."

# 嘗試優雅關閉
kill $PID

# 等待最多 10 秒
for i in {1..10}; do
    if ! ps -p $PID > /dev/null 2>&1; then
        echo "✅ 後端服務已停止"
        rm "$PID_FILE"
        exit 0
    fi
    sleep 1
done

# 如果還在運行，強制終止
echo "⚠️  進程未響應，強制終止..."
kill -9 $PID 2>/dev/null

if ! ps -p $PID > /dev/null 2>&1; then
    echo "✅ 後端服務已強制停止"
    rm "$PID_FILE"
else
    echo "❌ 無法停止進程 $PID"
    exit 1
fi
