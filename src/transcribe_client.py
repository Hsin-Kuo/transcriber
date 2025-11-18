#!/usr/bin/env python3
"""
Whisper 轉錄服務 - 客戶端腳本
用於向 whisper_server.py 發送音檔進行轉錄
"""

import argparse
import sys
from pathlib import Path
import requests


def transcribe_file(
    audio_path: str,
    server_url: str = "http://localhost:8000",
    punct_provider: str = "gemini",
    chunk_audio: bool = True,
    chunk_minutes: int = 10,
    return_format: str = "text",
    output_path: str = None
):
    """
    上傳音檔到服務端進行轉錄

    Args:
        audio_path: 音檔路徑
        server_url: 服務端 URL
        punct_provider: 標點提供者 (openai/gemini/none)
        chunk_audio: 是否使用分段模式
        chunk_minutes: 分段長度（分鐘）
        return_format: 回傳格式 (text/json)
        output_path: 輸出檔案路徑（可選）
    """
    audio_file = Path(audio_path).expanduser().resolve()

    if not audio_file.exists():
        print(f"❌ 找不到音檔：{audio_file}")
        sys.exit(1)

    print(f"📁 準備上傳：{audio_file.name} ({audio_file.stat().st_size / 1024 / 1024:.2f} MB)")
    print(f"🌐 服務端：{server_url}")

    # 檢查服務是否運行
    try:
        resp = requests.get(f"{server_url}/health", timeout=5)
        if resp.status_code != 200:
            print(f"⚠️ 服務健康檢查失敗：{resp.status_code}")
        else:
            health = resp.json()
            print(f"✅ 服務狀態：{health.get('status')}, 模型：{health.get('model_name')}")
    except requests.exceptions.RequestException as e:
        print(f"❌ 無法連接到服務端：{e}")
        print(f"   請確認服務已啟動：python3 whisper_server.py")
        sys.exit(1)

    # 上傳並轉錄
    print(f"📤 上傳音檔並開始轉錄...")
    print(f"   標點模式：{punct_provider}")
    print(f"   分段模式：{'開啟' if chunk_audio else '關閉'} ({chunk_minutes} 分鐘/段)")

    try:
        with audio_file.open("rb") as f:
            files = {"file": (audio_file.name, f, "audio/mpeg")}
            data = {
                "punct_provider": punct_provider,
                "chunk_audio": str(chunk_audio).lower(),
                "chunk_minutes": chunk_minutes,
                "return_format": return_format
            }

            resp = requests.post(
                f"{server_url}/transcribe",
                files=files,
                data=data,
                timeout=3600  # 60 分鐘超時
            )

        if resp.status_code != 200:
            print(f"❌ 轉錄失敗：{resp.status_code}")
            print(resp.text)
            sys.exit(1)

        # 處理回傳結果
        if return_format == "json":
            result = resp.json()
            print(f"\n✅ 轉錄完成！")
            print(f"   檔案名稱：{result['filename']}")
            print(f"   文字長度：{result['length']} 字")
            print(f"\n{'='*60}")
            print(result['text'])
            print(f"{'='*60}")

            # 如果指定輸出路徑，儲存文字
            if output_path:
                output_file = Path(output_path)
                output_file.write_text(result['text'], encoding='utf-8')
                print(f"\n💾 已儲存至：{output_file}")

        else:
            # text 格式：儲存下載的文字檔
            if output_path:
                output_file = Path(output_path)
            else:
                output_file = audio_file.with_suffix(".txt")

            output_file.write_bytes(resp.content)
            print(f"\n✅ 轉錄完成！")
            print(f"💾 已儲存至：{output_file}")

            # 顯示前 500 字
            content = output_file.read_text(encoding='utf-8')
            print(f"\n{'='*60}")
            print(f"前 500 字預覽：")
            print(content[:500])
            if len(content) > 500:
                print(f"... (共 {len(content)} 字)")
            print(f"{'='*60}")

    except requests.exceptions.Timeout:
        print(f"❌ 請求超時，音檔可能太長或服務繁忙")
        sys.exit(1)
    except requests.exceptions.RequestException as e:
        print(f"❌ 請求失敗：{e}")
        sys.exit(1)
    except Exception as e:
        print(f"❌ 錯誤：{e}")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        description="Whisper 轉錄服務 - 客戶端",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
範例：
  # 基本使用（使用預設設定）
  python3 transcribe_client.py -i audio.m4a

  # 指定服務端地址
  python3 transcribe_client.py -i audio.m4a --server http://192.168.1.100:8000

  # 回傳 JSON 格式
  python3 transcribe_client.py -i audio.m4a --format json

  # 不使用分段模式
  python3 transcribe_client.py -i audio.m4a --no-chunk

  # 指定輸出檔案
  python3 transcribe_client.py -i audio.m4a -o output.txt
        """
    )

    parser.add_argument("-i", "--input", required=True, help="音檔路徑")
    parser.add_argument("-o", "--output", help="輸出檔案路徑（可選）")
    parser.add_argument("--server", default="http://localhost:8000", help="服務端 URL")
    parser.add_argument("--punct-provider", choices=["openai", "gemini", "none"],
                        default="gemini", help="標點提供者")
    parser.add_argument("--no-chunk", action="store_true", help="不使用分段模式")
    parser.add_argument("--chunk-minutes", type=int, default=10, help="分段長度（分鐘）")
    parser.add_argument("--format", choices=["text", "json"], default="text", help="回傳格式")

    args = parser.parse_args()

    transcribe_file(
        audio_path=args.input,
        server_url=args.server,
        punct_provider=args.punct_provider,
        chunk_audio=not args.no_chunk,
        chunk_minutes=args.chunk_minutes,
        return_format=args.format,
        output_path=args.output
    )


if __name__ == "__main__":
    main()
