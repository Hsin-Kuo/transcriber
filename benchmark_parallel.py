#!/usr/bin/env python3
"""
測試並行 vs 順序執行的效能差異
"""
import time
from pathlib import Path

def test_parallel_vs_sequential():
    """比較並行和順序執行的時間"""

    test_audio = Path("test_audio.mp3")  # 替換為你的測試音檔

    if not test_audio.exists():
        print("❌ 請提供測試音檔路徑")
        return

    print("=" * 50)
    print("測試配置：")
    print(f"  音檔：{test_audio.name}")
    print("=" * 50)

    # TODO: 分別測試以下三種模式
    # 1. 並行模式（目前的實現）
    # 2. 順序模式（先 Diarization 再轉錄）
    # 3. 順序模式（先轉錄再 Diarization）

    print("\n測試 1：並行執行（Diarization + 轉錄同時）")
    print("  轉錄並行度：4 個線程")
    # ... 執行並記錄時間

    print("\n測試 2：順序執行（先 Diarization）")
    print("  轉錄並行度：4 個線程")
    # ... 執行並記錄時間

    print("\n測試 3：順序執行（先轉錄）")
    print("  轉錄並行度：4 個線程")
    # ... 執行並記錄時間

    print("\n測試 4：並行執行，降低轉錄並行度")
    print("  轉錄並行度：2 個線程")
    # ... 執行並記錄時間

if __name__ == "__main__":
    test_parallel_vs_sequential()
