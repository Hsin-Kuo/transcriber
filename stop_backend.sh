#!/bin/bash

# 停止腳本：停止背景運行的 Whisper 後端
# 用法：bash stop_backend.sh

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PID_FILE="$SCRIPT_DIR/backend.pid"

# 嘗試從 PID 文件讀取
if [ -f "$PID_FILE" ]; then
    PID=$(cat "$PID_FILE")
    echo "📋 從 PID 檔案讀取：$PID"
else
    # 如果找不到 PID 文件，嘗試自動查找進程
    echo "⚠️  找不到 PID 檔案，嘗試自動查找 uvicorn 進程..."
    PID=$(ps aux | grep "[u]vicorn src.main:app" | awk '{print $2}' | head -1)

    if [ -z "$PID" ]; then
        echo "❌ 找不到運行中的 uvicorn 進程"
        echo ""
        echo "提示：如果服務確實在運行，請檢查："
        echo "  ps aux | grep uvicorn"
        exit 1
    fi
    echo "✅ 找到運行中的進程：$PID"
fi

if ! ps -p $PID > /dev/null 2>&1; then
    echo "⚠️  進程 $PID 不存在，清理 PID 檔案"
    [ -f "$PID_FILE" ] && rm "$PID_FILE"

    # 再次嘗試查找實際運行的進程
    echo "🔍 查找實際運行的 uvicorn 進程..."
    PID=$(ps aux | grep "[u]vicorn src.main:app" | awk '{print $2}' | head -1)

    if [ -z "$PID" ]; then
        echo "✅ 沒有運行中的後端服務"
        exit 0
    fi
    echo "✅ 找到運行中的進程：$PID"
fi

echo "🛑 正在停止後端服務 (PID: $PID)..."

# 嘗試優雅關閉
kill $PID

# 等待最多 10 秒
for i in {1..10}; do
    if ! ps -p $PID > /dev/null 2>&1; then
        echo "✅ 後端服務已停止"
        [ -f "$PID_FILE" ] && rm "$PID_FILE"
        exit 0
    fi
    sleep 1
done

# 如果還在運行，強制終止
echo "⚠️  進程未響應，強制終止..."
kill -9 $PID 2>/dev/null

if ! ps -p $PID > /dev/null 2>&1; then
    echo "✅ 後端服務已強制停止"
    [ -f "$PID_FILE" ] && rm "$PID_FILE"
else
    echo "❌ 無法停止進程 $PID"
    exit 1
fi
