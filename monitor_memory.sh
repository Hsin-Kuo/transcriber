#!/bin/bash

# 記憶體監控腳本 - 每 2 秒監控一次後端進程記憶體使用

echo "開始監控後端記憶體使用（每 2 秒更新）..."
echo "時間, PID, VSZ(MB), RSS(MB), %MEM, 狀態"
echo "-------------------------------------------"

while true; do
    # 找到 whisper_server.py 進程
    PID=$(ps aux | grep whisper_server.py | grep -v grep | awk '{print $2}')

    if [ -z "$PID" ]; then
        echo "$(date '+%H:%M:%S'), 後端未運行"
    else
        # 獲取記憶體資訊
        MEM_INFO=$(ps -p $PID -o vsz=,rss=,%mem= | awk '{printf "%.1f, %.1f, %s", $1/1024, $2/1024, $3}')

        # 獲取最新的處理進度（從日誌）
        LAST_PROGRESS=$(tail -5 backend.log | grep "In-memory progress" | tail -1 | sed 's/.*progress: //' || echo "")

        echo "$(date '+%H:%M:%S'), $PID, $MEM_INFO, $LAST_PROGRESS"
    fi

    sleep 2
done
