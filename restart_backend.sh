#!/bin/bash

# 重啟腳本：重啟後端服務
# 用法：bash restart_backend.sh

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "🔄 重啟 Whisper 後端服務..."
echo ""

# 停止服務
if [ -f "$SCRIPT_DIR/backend.pid" ]; then
    echo "步驟 1/2：停止現有服務"
    bash "$SCRIPT_DIR/stop_backend.sh"
    echo ""
else
    echo "步驟 1/2：無現有服務需停止"
    echo ""
fi

# 等待 2 秒確保端口釋放
sleep 2

# 啟動服務
echo "步驟 2/2：啟動服務"
bash "$SCRIPT_DIR/start_backend_daemon.sh"
