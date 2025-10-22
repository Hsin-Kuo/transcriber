import os
import sys
import argparse
from pathlib import Path

# —— 可調參數 —— #
GEMINI_MODEL = "gemini-2.0-flash"  # Gemini 模型
CHUNK_SIZE = 3000  # 每段處理的字數

def refine_with_gemini(text: str, style: str = "book_guide", chunk_size: int = CHUNK_SIZE) -> str:
    """用 Google Gemini 潤飾逐字稿，刪除不重要內容並重新組織"""
    import google.generativeai as genai

    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise RuntimeError("未設定 GOOGLE_API_KEY")
    genai.configure(api_key=api_key)

    model = genai.GenerativeModel(GEMINI_MODEL)

    # 根據不同風格設定不同的提示詞
    style_prompts = {
        "book_guide": {
            "system": (
                "你是專業的文字編輯。你的任務是將課堂的口語逐字稿，"
                "精煉成適合閱讀的書面文字。"
            ),
            "instructions": (
                "請按照以下原則處理這段課堂逐字稿：\n"
                "1. 刪除語氣詞（如：嗯、啊、那個、就是、然後等）\n"
                "2. 刪除重複或冗余的表述\n"
                "3. 刪除與導讀主題無關的閒聊內容\n"
                "4. 將口語化表達改為書面語\n"
                "5. 保留所有重要的知識點、觀點、書籍引用和例子\n"
                "6. 適當重組句子，使邏輯更清晰\n"
                "7. 保持原作者的觀點和語氣\n"
                "8. 適當分段，讓內容更易讀\n\n"
                "請直接輸出精煉後的內容，不要添加「精煉後」等前綴。"
            )
        },
        "concise": {
            "system": (
                "你是專業的文字編輯。你的任務是將逐字稿精簡成重點摘要。"
            ),
            "instructions": (
                "請將逐字稿精簡為重點摘要：\n"
                "1. 只保留核心觀點和重要資訊\n"
                "2. 刪除所有冗余內容和例子\n"
                "3. 使用簡潔的書面語\n"
                "4. 條列式呈現重點\n\n"
                "請直接輸出摘要內容。"
            )
        },
        "formal": {
            "system": (
                "你是專業的文字編輯。你的任務是將口語逐字稿轉為正式書面文字。"
            ),
            "instructions": (
                "請將逐字稿改寫為正式的書面文字：\n"
                "1. 刪除所有語氣詞\n"
                "2. 將口語改為正式書面語\n"
                "3. 保留所有重要資訊\n"
                "4. 適當重組句子結構\n\n"
                "請直接輸出改寫後的內容。"
            )
        }
    }

    selected_style = style_prompts.get(style, style_prompts["book_guide"])

    # 如果文本不長，直接處理
    if len(text) <= chunk_size:
        user_msg = selected_style["instructions"] + "\n\n原文：\n" + text
        resp = model.generate_content(
            [{"role": "user", "parts": [selected_style["system"] + "\n\n" + user_msg]}],
            generation_config={"temperature": 0.3}
        )
        return (resp.text or "").strip()

    # 長文本：分段處理
    print(f"📊 文本長度 {len(text)} 字，將分段處理（每段約 {chunk_size} 字）...")
    chunks = []
    start = 0

    while start < len(text):
        end = start + chunk_size
        # 避免切斷句子，往前找最近的標點
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

        if idx == 1:
            context = "（這是第 1 段）"
        elif idx == len(chunks):
            context = "（這是最後一段，接續前文）"
        else:
            context = f"（這是第 {idx} 段，接續前文）"

        user_msg = selected_style["instructions"] + "\n" + context + "\n\n原文：\n" + chunk

        resp = model.generate_content(
            [{"role": "user", "parts": [selected_style["system"] + "\n\n" + user_msg]}],
            generation_config={"temperature": 0.3}
        )
        results.append((resp.text or "").strip())

    print("✅ 所有段落處理完成，正在合併...")
    return "\n\n".join(results)

def main():
    parser = argparse.ArgumentParser(
        description="使用 Gemini 潤飾和精煉逐字稿"
    )
    parser.add_argument("-i", "--input", required=True, help="輸入文本檔案路徑")
    parser.add_argument("-o", "--output", help="輸出檔案路徑（預設：原檔名.refined.txt）")
    parser.add_argument("--style", choices=["book_guide", "concise", "formal"],
                        default="book_guide",
                        help="潤飾風格：book_guide(書籍導讀) | concise(精簡摘要) | formal(正式書面語)")
    parser.add_argument("--chunk-size", type=int, default=CHUNK_SIZE,
                        help=f"分段處理的字數（預設 {CHUNK_SIZE}）")
    args = parser.parse_args()

    input_path = Path(args.input).expanduser().resolve()
    if not input_path.exists():
        print(f"❌ 找不到檔案：{input_path}")
        sys.exit(1)

    # 設定輸出路徑
    if args.output:
        output_path = Path(args.output).expanduser().resolve()
    else:
        output_path = input_path.with_suffix('').with_suffix('.refined.txt')

    # 檢查輸出檔案是否已存在
    if output_path.exists():
        print(f"📂 偵測到已存在輸出檔案：{output_path.name}")
        response = input("是否覆蓋？(y/n): ")
        if response.lower() != 'y':
            print("取消執行。")
            sys.exit(0)

    print(f"📖 讀取檔案：{input_path.name}")
    text = input_path.read_text(encoding="utf-8")
    print(f"📊 原文長度：{len(text)} 字")

    style_names = {
        "book_guide": "書籍導讀風格",
        "concise": "精簡摘要風格",
        "formal": "正式書面語風格"
    }
    print(f"✨ 使用 Gemini 潤飾（{style_names.get(args.style, args.style)}）...")

    try:
        refined_text = refine_with_gemini(text, style=args.style, chunk_size=args.chunk_size)

        output_path.write_text(refined_text, encoding="utf-8")
        print(f"📊 精煉後長度：{len(refined_text)} 字")
        print(f"📉 精簡比例：{(1 - len(refined_text)/len(text))*100:.1f}%")
        print(f"🎉 已輸出精煉文本：{output_path.name}")
    except Exception as e:
        print(f"⚠️ 處理失敗：{e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
