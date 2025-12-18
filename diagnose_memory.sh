#!/bin/bash

# 記憶體診斷腳本 - 一次性收集所有相關資訊

echo "========================================="
echo "記憶體診斷報告 - $(date)"
echo "========================================="
echo ""

# 1. 後端進程資訊
echo "1. 後端進程狀態："
PID=$(ps aux | grep whisper_server.py | grep -v grep | awk '{print $2}')
if [ -z "$PID" ]; then
    echo "   ❌ 後端未運行"
else
    echo "   PID: $PID"
    ps -p $PID -o pid,vsz,rss,%mem,%cpu,etime,stat,command
    echo ""
    echo "   記憶體詳情："
    echo "   - VSZ: $(ps -p $PID -o vsz= | awk '{printf "%.1f MB", $1/1024}')"
    echo "   - RSS: $(ps -p $PID -o rss= | awk '{printf "%.1f MB", $1/1024}')"
fi
echo ""

# 2. 所有 Python 相關進程
echo "2. 所有 Python 相關進程："
ps aux | grep -E "python|Python" | grep -v grep | awk '{printf "   PID %s: RSS %.1f MB - %s\n", $2, $6/1024, substr($0, index($0,$11))}'
echo ""

# 3. 系統記憶體狀態
echo "3. 系統記憶體狀態："
vm_stat | perl -ne '/page size of (\d+)/ and $size=$1; /Pages\s+([^:]+)[^\d]+(\d+)/ and printf("   %-20s % 16.2f MB\n", "$1:", $2 * $size / 1048576);'
echo ""

# 4. 目前任務狀態
echo "4. 目前轉錄任務狀態："
tail -30 backend.log | grep -E "(收到檔案|任務已建立|In-memory progress|從記憶體返回|說話者|開始並行轉錄)" | tail -10
echo ""

# 5. MongoDB 連接
echo "5. MongoDB 連接狀態："
lsof -p $PID 2>/dev/null | grep -i mongo | wc -l | awk '{print "   活躍連接數: " $1}'
echo ""

# 6. 暫存檔案
echo "6. 暫存目錄檔案："
if [ -d "temp_transcriptions" ]; then
    du -sh temp_transcriptions/* 2>/dev/null | tail -5
    echo "   總計: $(du -sh temp_transcriptions 2>/dev/null | awk '{print $1}')"
else
    echo "   無暫存目錄"
fi
echo ""

# 7. 記憶體趨勢（最近 1 分鐘）
echo "7. 記憶體趨勢（觀察 30 秒）："
for i in {1..6}; do
    if [ ! -z "$PID" ]; then
        RSS=$(ps -p $PID -o rss= 2>/dev/null | awk '{printf "%.1f", $1/1024}')
        if [ ! -z "$RSS" ]; then
            echo "   ${i}. RSS: ${RSS} MB"
        fi
    fi
    sleep 5
done

echo ""
echo "========================================="
echo "診斷完成"
echo "========================================="
