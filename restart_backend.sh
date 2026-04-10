#!/bin/bash

# 重啟腳本：重啟後端服務
# 用法：bash restart_backend.sh

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "🔄 重啟 Sound Lite 後端服務..."
echo ""

# 停止服務（忽略錯誤碼，確保總是能繼續）
echo "步驟 1/2：停止現有服務"
bash "$SCRIPT_DIR/stop_backend.sh" || true
echo ""

# 等待 2 秒確保端口釋放
sleep 2

# 雙重檢查：確保沒有遺留進程
REMAINING=$(ps aux | grep "[u]vicorn src.main:app" | awk '{print $2}')
if [ -n "$REMAINING" ]; then
    echo "⚠️  發現遺留進程，強制清理..."
    echo "$REMAINING" | xargs kill -9 2>/dev/null || true
    sleep 1
fi

# 啟動服務
echo "步驟 2/2：啟動服務"
bash "$SCRIPT_DIR/start_backend_daemon.sh"
