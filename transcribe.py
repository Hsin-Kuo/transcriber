import os
import sys
import argparse
from pathlib import Path
import whisper
from pydub import AudioSegment

# —— 可調參數 —— #
DEFAULT_MODEL = "small"          # tiny | base | small | medium
USE_WAV = True
OPENAI_MODEL = "gpt-4o-mini"     # 用來加標點（OpenAI）
GEMINI_MODEL = "gemini-2.0-flash" # 用來加標點（Gemini）
CHUNK_DURATION_MS = 10 * 60 * 1000  # 音檔分段長度（毫秒），預設 10 分鐘


# export GOOGLE_API_KEY="AIzaSyDk8uzpNcvWjp8yPELvcApvABMnehzlT_E"
# python3 transcribe.py -i 574181344843137331.mp4 -m small --punct-provider gemini

# ---------- Audio Chunking ----------

def transcribe_audio_in_chunks(audio_path: Path, model, chunk_duration_ms: int = CHUNK_DURATION_MS) -> str:
    """將音檔分段後逐段轉錄，提高準確度"""
    from pydub import AudioSegment
    from pydub.silence import detect_nonsilent

    print(f"🔊 載入音檔：{audio_path.name}")
    audio = AudioSegment.from_file(audio_path)
    total_duration_ms = len(audio)
    total_minutes = total_duration_ms / 1000 / 60

    print(f"📊 音檔總長度：{total_minutes:.1f} 分鐘")

    # 如果音檔不長，直接轉錄
    if total_duration_ms <= chunk_duration_ms:
        print(f"📝 音檔長度在 {chunk_duration_ms/1000/60:.0f} 分鐘內，直接轉錄...")
        result = model.transcribe(str(audio_path), language="zh", fp16=False)
        return (result.get("text") or "").strip()

    # 長音檔：分段處理
    num_chunks = (total_duration_ms + chunk_duration_ms - 1) // chunk_duration_ms
    print(f"🔄 音檔較長，將分為 {num_chunks} 段處理（每段約 {chunk_duration_ms/1000/60:.0f} 分鐘）...")

    chunks_text = []
    start_ms = 0
    chunk_idx = 1

    while start_ms < total_duration_ms:
        end_ms = min(start_ms + chunk_duration_ms, total_duration_ms)

        # 如果不是最後一段，嘗試在靜音處切分
        if end_ms < total_duration_ms:
            # 在預定切分點前後 30 秒內找靜音
            search_start = max(end_ms - 30000, start_ms)
            search_end = min(end_ms + 30000, total_duration_ms)
            search_segment = audio[search_start:search_end]

            # 偵測非靜音區間（靜音閾值 -40dB，最小靜音長度 500ms）
            nonsilent_ranges = detect_nonsilent(
                search_segment,
                min_silence_len=500,
                silence_thresh=-40
            )

            # 找到最接近預定切分點的靜音間隔
            if nonsilent_ranges:
                target_pos = end_ms - search_start
                best_split = end_ms
                min_diff = float('inf')

                for i in range(len(nonsilent_ranges) - 1):
                    gap_start = nonsilent_ranges[i][1]
                    gap_end = nonsilent_ranges[i + 1][0]
                    gap_mid = (gap_start + gap_end) // 2

                    diff = abs(gap_mid - target_pos)
                    if diff < min_diff:
                        min_diff = diff
                        best_split = search_start + gap_mid

                # 如果找到的切分點在合理範圍內，就使用它
                if abs(best_split - end_ms) < 60000:  # 60 秒內
                    end_ms = best_split

        print(f"   處理第 {chunk_idx}/{num_chunks} 段 ({start_ms/1000/60:.1f}-{end_ms/1000/60:.1f} 分鐘)...")

        # 提取音檔片段
        chunk_audio = audio[start_ms:end_ms]

        # 儲存臨時檔案
        temp_path = audio_path.parent / f"_temp_chunk_{chunk_idx}.wav"
        chunk_audio.export(temp_path, format="wav")

        # 轉錄
        result = model.transcribe(str(temp_path), language="zh", fp16=False)
        chunk_text = (result.get("text") or "").strip()
        chunks_text.append(chunk_text)

        # 刪除臨時檔案
        temp_path.unlink()

        start_ms = end_ms
        chunk_idx += 1

    print("✅ 所有音檔片段轉錄完成")
    return " ".join(chunks_text)

# ---------- Punctuation Providers ----------

def punctuate_with_openai(text: str) -> str:
    """用 OpenAI 幫逐字稿加標點與分段"""
    from openai import OpenAI
    client = OpenAI()  # 讀 OPENAI_API_KEY
    prompt = (
        "請將以下『中文逐字稿』加上適當標點符號並合理分段。"
        "不要省略或添加內容，不要意譯，保留固有名詞與數字。"
        "輸出純文字即可：\n\n"
        f"{text}"
    )
    resp = client.chat.completions.create(
        model=OPENAI_MODEL,
        messages=[
            {"role": "system", "content": "你是嚴謹的逐字稿潤飾助手，只做標點與分段。"},
            {"role": "user", "content": prompt},
        ],
        temperature=0.2,
    )
    return resp.choices[0].message.content.strip()

def punctuate_with_gemini(text: str, chunk_size: int = 3000) -> str:
    """用 Google Gemini 幫逐字稿加標點與分段（支援長文本分段處理）"""
    import google.generativeai as genai
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise RuntimeError("未設定 GOOGLE_API_KEY")
    genai.configure(api_key=api_key)

    model = genai.GenerativeModel(GEMINI_MODEL)

    # 如果文本不長，直接處理
    if len(text) <= chunk_size:
        system_msg = (
            "你是嚴謹的逐字稿潤飾助手。只做『中文標點補全與合理分段』，"
            "不要省略或添加內容，不要意譯，非必要不要用刪節號，保留固有名詞與數字： "
        )
        user_msg = (
            "請為以下中文逐字稿加上適當標點並分段：\n\n" + text
        )
        resp = model.generate_content(
            [{"role": "user", "parts": [system_msg + "\n\n" + user_msg]}],
            generation_config={"temperature": 0.2}
        )
        return (resp.text or "").strip()

    # 長文本：分段處理
    print(f"📊 文本長度 {len(text)} 字，將分段處理（每段約 {chunk_size} 字）...")
    chunks = []
    start = 0

    while start < len(text):
        end = start + chunk_size
        # 避免切斷句子，往前找最近的句號、問號、驚嘆號或換行
        if end < len(text):
            for i in range(end, max(start + chunk_size // 2, end - 200), -1):
                if text[i] in '。？！\n':
                    end = i + 1
                    break
        chunks.append(text[start:end])
        start = end

    print(f"🔄 共分為 {len(chunks)} 段處理...")
    results = []

    for idx, chunk in enumerate(chunks, 1):
        print(f"   處理第 {idx}/{len(chunks)} 段...")
        system_msg = (
            "你是嚴謹的逐字稿潤飾助手。只做『中文標點補全與合理分段』，"
            "不要省略或添加內容，不要意譯，非必要不要用刪節號，保留固有名詞與數字。"
        )
        if idx == 1:
            user_msg = f"請為以下中文逐字稿加上適當標點並分段（這是第 1 段）：\n\n{chunk}"
        elif idx == len(chunks):
            user_msg = f"請為以下中文逐字稿加上適當標點並分段（這是最後一段，接續前文）：\n\n{chunk}"
        else:
            user_msg = f"請為以下中文逐字稿加上適當標點並分段（這是第 {idx} 段，接續前文）：\n\n{chunk}"

        resp = model.generate_content(
            [{"role": "user", "parts": [system_msg + "\n\n" + user_msg]}],
            generation_config={"temperature": 0.2}
        )
        results.append((resp.text or "").strip())

    print("✅ 所有段落處理完成，正在合併...")
    return "\n\n".join(results)

# ---------- Main ----------

def main():
    parser = argparse.ArgumentParser(
        description="Whisper 轉逐字稿 →（OpenAI/Gemini）自動加中文標點與分段"
    )
    parser.add_argument("-i", "--input", required=True, help="輸入音檔路徑（m4a/mp3/mp3/wav 等）")
    parser.add_argument("-m", "--model", default=DEFAULT_MODEL, help="Whisper 模型（tiny/base/small/medium/large-v2）")
    parser.add_argument("--no-wav", action="store_true", help="直接用原檔，不轉成 wav")
    parser.add_argument("--punct-provider", choices=["openai", "gemini", "none"],
                        default="openai", help="選擇加標點提供者（openai|gemini|none）")
    parser.add_argument("--chunk-audio", action="store_true", help="將音檔分段後再轉錄（提高長音檔準確度）")
    parser.add_argument("--chunk-minutes", type=int, default=10, help="音檔分段長度（分鐘），預設 10 分鐘")
    args = parser.parse_args()

    audio_path = Path(args.input).expanduser().resolve()
    if not audio_path.exists():
        print(f"❌ 找不到音檔：{audio_path}")
        sys.exit(1)

    raw_txt_path = audio_path.with_suffix(".raw.txt")
    pretty_txt_path = audio_path.with_suffix(".txt")

    # 若已有最終 txt，直接略過
    if pretty_txt_path.exists():
        print(f"📂 偵測到已存在帶標點逐字稿：{pretty_txt_path.name}，跳過處理。")
        return

    # 若已有 raw.txt，就直接進入標點階段
    if raw_txt_path.exists():
        print(f"📂 偵測到已存在原始逐字稿：{raw_txt_path.name}，跳過轉錄。")
        raw_text = raw_txt_path.read_text(encoding="utf-8")
    else:
        # 需要轉錄
        use_wav = not args.no_wav and USE_WAV
        to_transcribe = audio_path
        if use_wav:
            wav_path = audio_path.with_suffix(".wav")
            if wav_path.exists():
                print(f"📂 偵測到已存在 WAV 檔，直接使用：{wav_path.name}")
            else:
                print(f"🔄 轉檔為 WAV：{wav_path.name}")
                AudioSegment.from_file(audio_path).export(wav_path, format="wav")
            to_transcribe = wav_path

        print(f"🎙 載入 Whisper 模型：{args.model}")
        model = whisper.load_model(args.model)

        # 根據參數選擇分段或整段轉錄
        if args.chunk_audio:
            chunk_duration_ms = args.chunk_minutes * 60 * 1000
            raw_text = transcribe_audio_in_chunks(to_transcribe, model, chunk_duration_ms)
        else:
            print(f"📝 開始轉逐字稿：{to_transcribe.name}")
            result = model.transcribe(str(to_transcribe), language="zh", fp16=False)
            raw_text = (result.get("text") or "").strip()

        raw_txt_path.write_text(raw_text, encoding="utf-8")
        print(f"✅ 已儲存原始逐字稿：{raw_txt_path.name}")

    # 是否加標點
    if args.punct_provider == "none":
        print("ℹ️ 未選擇標點提供者（--punct-provider none），僅輸出原始逐字稿。")
        return

    try:
        if args.punct_provider == "gemini":
            print("✨ 使用 Gemini 加標點與分段 ...")
            pretty = punctuate_with_gemini(raw_text)
        else:
            # 預設 openai
            if not os.getenv("OPENAI_API_KEY"):
                print("⚠️ 未設定 OPENAI_API_KEY，無法使用 OpenAI 標點。你可改用 --punct-provider gemini。")
                return
            print("✨ 使用 OpenAI 加標點與分段 ...")
            pretty = punctuate_with_openai(raw_text)

        pretty_txt_path.write_text(pretty, encoding="utf-8")
        print(f"🎉 已輸出帶標點逐字稿：{pretty_txt_path.name}")
    except Exception as e:
        print(f"⚠️ 加標點失敗（{e}），已保留原始逐字稿：{raw_txt_path.name}")

if __name__ == "__main__":
    main()
