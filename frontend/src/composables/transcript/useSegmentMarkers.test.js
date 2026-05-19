import { describe, it, expect } from 'vitest'
import { alignSegmentsToContent } from './useSegmentMarkers.js'

// Helper：把 marker 陣列壓成易讀的字串，方便 expect 比對
function shape(markers) {
  return markers.map((m) => `[${m.segmentIndex}]${m.text}@[${m.textStartIndex},${m.textEndIndex})`)
}

describe('alignSegmentsToContent', () => {
  describe('基本對齊', () => {
    it('對齊一般段落（無重複、無失配、有標點）', () => {
      const segments = [
        { text: '大家好', start: 0, end: 0.5 },
        { text: '今天天氣不錯', start: 0.6, end: 1.5 },
        { text: '謝謝大家', start: 1.6, end: 2.5 },
      ]
      const content = '大家好，今天天氣不錯。謝謝大家！'

      expect(shape(alignSegmentsToContent(segments, content))).toEqual([
        '[0]大家好@[0,3)',
        '[1]今天天氣不錯@[4,10)',
        '[2]謝謝大家@[11,15)',
      ])
    })

    it('保留 segmentIndex 對應原始 segments 陣列順序', () => {
      const segments = [
        { text: '甲段落', start: 0, end: 1 },
        { text: '乙段落', start: 1, end: 2 },
      ]
      const result = alignSegmentsToContent(segments, '甲段落乙段落')
      expect(result[0].segmentIndex).toBe(0)
      expect(result[1].segmentIndex).toBe(1)
    })

    it('marker 包含 start/end 時間軸資訊', () => {
      const result = alignSegmentsToContent(
        [{ text: '你好', start: 1.5, end: 2.0 }],
        '你好世界'
      )
      expect(result[0]).toMatchObject({ start: 1.5, end: 2.0, text: '你好' })
    })
  })

  describe('短 segment（A2 — 拿掉 6 字下限）', () => {
    it('1 字 segment 也納入', () => {
      const segments = [
        { text: '對', start: 0, end: 0.3 },
        { text: '是', start: 0.4, end: 0.7 },
      ]
      expect(shape(alignSegmentsToContent(segments, '對，是。'))).toEqual([
        '[0]對@[0,1)',
        '[1]是@[2,3)',
      ])
    })

    it('2~3 字 segment 也納入', () => {
      const segments = [
        { text: '好的', start: 0, end: 0.5 },
        { text: '謝謝', start: 0.6, end: 1.0 },
      ]
      expect(shape(alignSegmentsToContent(segments, '好的，謝謝！'))).toEqual([
        '[0]好的@[0,2)',
        '[1]謝謝@[3,5)',
      ])
    })

    it('純標點 segment 跳過（無意義 anchor）', () => {
      const segments = [
        { text: '你好', start: 0, end: 0.5 },
        { text: '。', start: 0.6, end: 0.7 }, // 純標點
        { text: '再見', start: 0.8, end: 1.2 },
      ]
      expect(shape(alignSegmentsToContent(segments, '你好。再見！'))).toEqual([
        '[0]你好@[0,2)',
        '[2]再見@[3,5)',
      ])
    })

    it('全空白 segment 跳過', () => {
      const segments = [
        { text: 'foo', start: 0, end: 1 },
        { text: '   ', start: 1, end: 2 }, // 全空白
        { text: 'bar', start: 2, end: 3 },
      ]
      expect(shape(alignSegmentsToContent(segments, 'foo bar'))).toEqual([
        '[0]foo@[0,3)',
        '[2]bar@[4,7)',
      ])
    })
  })

  describe('失配 segment（A1 — 不污染 lastSearchIndex）', () => {
    it('失配 segment 不影響後續 segment 對齊', () => {
      const segments = [
        { text: '甲', start: 0, end: 1 },
        { text: '不存在的字', start: 1, end: 2 }, // 失配
        { text: '乙', start: 2, end: 3 },
      ]
      expect(shape(alignSegmentsToContent(segments, '甲乙'))).toEqual([
        '[0]甲@[0,1)',
        '[2]乙@[1,2)',
      ])
    })

    it('重複文字 + 中間失配：用 ExpectedPosition 選對位置（關鍵 case）', () => {
      // segments[1]「嗯」在 content 中不存在，舊版會讓後續 3 個「對」全部
      // 從第一個重複位置開始抓，時間軸完全錯位。新版用 segment.start 推出
      // ExpectedPos 把各「對」鎖到對的位置。
      const segments = [
        { text: '大家好', start: 0, end: 0.5 },
        { text: '嗯', start: 0.6, end: 0.8 }, // 失配
        { text: '對', start: 0.9, end: 1.1 },
        { text: '對', start: 1.2, end: 1.4 },
        { text: '謝謝', start: 1.5, end: 2.0 },
      ]
      const content = '大家好，對對對，謝謝。'
      // 對 在 [4][5][6]; charPerSecond = 11/2.0 = 5.5
      // seg[2] expected=4.95 → 取 5; seg[3] expected=6.6 → 取 6; seg[4] → 8
      expect(shape(alignSegmentsToContent(segments, content))).toEqual([
        '[0]大家好@[0,3)',
        '[2]對@[5,6)',
        '[3]對@[6,7)',
        '[4]謝謝@[8,10)',
      ])
    })
  })

  describe('重複文字', () => {
    it('同樣片語在不同位置重複時依時間軸正確分派', () => {
      const segments = [
        { text: '我覺得這件事', start: 0, end: 1.0 },
        { text: '很重要', start: 1.1, end: 1.5 },
        { text: '我覺得這件事', start: 1.6, end: 2.5 },
        { text: '不重要', start: 2.6, end: 3.0 },
      ]
      expect(
        shape(alignSegmentsToContent(segments, '我覺得這件事很重要。我覺得這件事不重要。'))
      ).toEqual([
        '[0]我覺得這件事@[0,6)',
        '[1]很重要@[6,9)',
        '[2]我覺得這件事@[10,16)',
        '[3]不重要@[16,19)',
      ])
    })

    it('連續重複的單字（對對對）依時間軸正確分派', () => {
      const segments = [
        { text: '對', start: 0, end: 0.3 },
        { text: '對', start: 0.4, end: 0.7 },
        { text: '對', start: 0.8, end: 1.1 },
      ]
      expect(shape(alignSegmentsToContent([...segments], '對對對'))).toEqual([
        '[0]對@[0,1)',
        '[1]對@[1,2)',
        '[2]對@[2,3)',
      ])
    })
  })

  describe('Edge cases', () => {
    it('空 segments 回 []', () => {
      expect(alignSegmentsToContent([], 'abc')).toEqual([])
    })

    it('null/undefined segments 回 []', () => {
      expect(alignSegmentsToContent(null, 'abc')).toEqual([])
      expect(alignSegmentsToContent(undefined, 'abc')).toEqual([])
    })

    it('空 content 回 []', () => {
      expect(alignSegmentsToContent([{ text: 'a', start: 0, end: 1 }], '')).toEqual([])
    })

    it('null/undefined content 回 []', () => {
      expect(alignSegmentsToContent([{ text: 'a', start: 0, end: 1 }], null)).toEqual([])
      expect(alignSegmentsToContent([{ text: 'a', start: 0, end: 1 }], undefined)).toEqual([])
    })

    it('segment.text 是 undefined 跳過', () => {
      const segments = [
        { text: 'foo', start: 0, end: 1 },
        { start: 1, end: 2 }, // 無 text
        { text: 'bar', start: 2, end: 3 },
      ]
      expect(shape(alignSegmentsToContent(segments, 'foo bar'))).toEqual([
        '[0]foo@[0,3)',
        '[2]bar@[4,7)',
      ])
    })

    it('segment.start 缺失時 fallback 到首個候選', () => {
      // 無時間軸資訊 → 不算 expectedPos → 多候選取第一個（與舊版 greedy 一致）
      const segments = [
        { text: '對', end: 0.3 }, // 無 start
        { text: '對', end: 0.6 }, // 無 start
      ]
      expect(shape(alignSegmentsToContent(segments, '對對對'))).toEqual([
        '[0]對@[0,1)',
        '[1]對@[1,2)',
      ])
    })

    it('totalDuration 為 0 時 fallback 到首個候選', () => {
      // 全部 end 都是 0 → charPerSecond=0 → expected=null → 取首個
      const segments = [
        { text: '對', start: 0, end: 0 },
        { text: '對', start: 0, end: 0 },
      ]
      expect(shape(alignSegmentsToContent(segments, '對對對'))).toEqual([
        '[0]對@[0,1)',
        '[1]對@[1,2)',
      ])
    })

    it('大小寫不敏感匹配', () => {
      const segments = [
        { text: 'Hello', start: 0, end: 0.5 },
        { text: 'WORLD', start: 0.6, end: 1.0 },
      ]
      expect(shape(alignSegmentsToContent(segments, 'hello, world!'))).toEqual([
        '[0]Hello@[0,5)',
        '[1]WORLD@[7,12)',
      ])
    })

    it('全部失配時回 []', () => {
      const segments = [
        { text: '完全不存在的字', start: 0, end: 1 },
        { text: '另一個不存在的字', start: 1, end: 2 },
      ]
      expect(alignSegmentsToContent(segments, '其他內容')).toEqual([])
    })

    it('大量短重複文字：每個 segment 仍能依時間軸選到對的位置', () => {
      // 100 個「對」連續 + 1 個「結束」
      const content = '對'.repeat(100) + '結束'
      const segments = [
        { text: '對', start: 0, end: 0.1 },
        { text: '結束', start: 9, end: 10 }, // 接近結尾
      ]
      const result = alignSegmentsToContent(segments, content)
      // 「對」應該對到接近 0 的位置（expected ≈ 0）
      expect(result[0].textStartIndex).toBe(0)
      // 「結束」應該對到 [100, 102)
      expect(result[1]).toMatchObject({ textStartIndex: 100, textEndIndex: 102 })
    })

    it('短重複文字大量散佈 content：不會 cascade 失配（每個 segment 都有 marker）', () => {
      // Regression: 短重複文字在整篇出現上百次時,各 segment 至少能對到某個位置、
      // lastSearchIndex 不會跳過頭、後面 segments 不會 cascade 失配。
      //
      // 注意:當 firstHit 跟 validBackward 相距 > 30（candidates 散落在 content
      // 不同段落）時,演算法會偏好 monotone 順序選 firstHit 而非「最靠 expected」
      // 的 validBackward—— 避免 cps 高估造成的 cascade。所以這裡「有」segment
      // 不保證對到 time-correct 位置（150/300），但**保證每段都有 marker**。
      const head = '頭'.repeat(100)
      const tail = '尾'.repeat(100)
      const middle = Array(200).fill('有X').join('')
      const content = head + middle + tail // 100 + 400 + 100 = 600 chars

      const segments = [
        { text: '頭', start: 0, end: 0.5 },
        { text: '有', start: 150, end: 150.1 },
        { text: '有', start: 300, end: 300.1 },
        { text: '尾', start: 599, end: 600 },
      ]

      const result = alignSegmentsToContent(segments, content)
      expect(result.length).toBe(4) // 沒 cascade
      expect(result[0].textStartIndex).toBe(0)
      // 兩個「有」都對到中段範圍內某個「有」位置 (100~498，每 2 字一個)
      expect(result[1].textStartIndex).toBeGreaterThanOrEqual(100)
      expect(result[1].textStartIndex).toBeLessThanOrEqual(498)
      expect(result[2].textStartIndex).toBeGreaterThan(result[1].textStartIndex)
      expect(result[2].textStartIndex).toBeLessThanOrEqual(498)
      // 「尾」對到尾段範圍 [500, 599]
      expect(result[3].textStartIndex).toBeGreaterThanOrEqual(500)
      expect(result[3].textStartIndex).toBeLessThanOrEqual(599)
    })

    it('silence 後第一個段：同字在 line 2 / line 3 各出現，演算法選 line 2 不破壞 line 4 對齊', () => {
      // 使用者實測 case (PR #44 之後的問題):
      //   "[皓棠] Blow跟Popper。\n[宗文] SSK愛丁堡...還有呢？拉圖。\n[宗文] 其實愛丁堡,...一個SSK,..."
      // segments:
      //   1. "Blow跟Popper" (920-923)
      //   2. ""             (923-927)  silence
      //   3. "SSK"          (932-933)  ← 應對到 line 2 的 SSK
      //   4. "愛丁堡"        (933-935)  ← 緊接 line 2 的 SSK 之後
      //
      // 4.6s silence 讓 global cps 對這段嚴重高估,expected 飄到後段。
      // lastIndexOf 給 line 3 的 SSK（最靠 expected），lastSearchIndex 跳過頭,
      // 之後「愛丁堡」對不到 → cascade。
      // 修法: spread heuristic 偏好 firstHit (line 2 SSK)，保留後續對齊。
      const content =
        '[皓棠] Blow跟Popper。\n' +
        '[宗文] SSK愛丁堡，還有呢？拉圖。\n' +
        '[宗文] 其實愛丁堡，還有另外一個，一個SSK，另一'

      const segments = [
        { text: 'Blow跟Popper', start: 920.65, end: 922.89 },
        { text: '', start: 922.89, end: 927.5 }, // silence
        { text: 'SSK', start: 932.46, end: 933.44 },
        { text: '愛丁堡', start: 933.44, end: 934.92 },
      ]

      const result = alignSegmentsToContent(segments, content)
      const byIdx = Object.fromEntries(result.map((m) => [m.segmentIndex, m]))
      expect(byIdx[0]?.text).toBe('Blow跟Popper') // seg 1 有 marker
      // seg 3 「SSK」對到 line 2 的 SSK，不該對到 line 3 那個（後者位置 >50）
      expect(byIdx[2]).toBeDefined()
      expect(byIdx[2].textStartIndex).toBeLessThan(30)
      // 關鍵: seg 4 「愛丁堡」**有 marker**（沒 cascade 失配）
      expect(byIdx[3]).toBeDefined()
      // 且對到的位置在 line 2 範圍（接近 SSK 的位置之後）
      expect(byIdx[3].textStartIndex).toBeGreaterThan(byIdx[2].textStartIndex)
      expect(byIdx[3].textStartIndex).toBeLessThan(40)
    })

    it('短字段 LLM 被改掉 + 同字後面才出現：當失配，不污染 anchor 不影響後續', () => {
      // 模擬 user 實測 case: LLM 強化過程把短字「那」從 content 改掉了,
      // 但 segments 還記錄著「那」。content 後面 200 chars 才又出現一個「那」。
      // 沒 drift threshold 時:演算法被迫挑後面那個「那」→ lastSearchIndex 推
      // 過頭 → 之後 segment 都失配。加 drift threshold 後:該段被當失配,
      // lastSearchIndex 不變,後面 segments 仍能對齊。
      const content =
        '段落一結束。' + 'X'.repeat(200) + '那段內容也很重要。' // 「那」只在 200 chars 之後
      // positions: 段落一結束。 = 0-5。X×200 = 6-205。那段內容也很重要。 = 206-214

      const segments = [
        { text: '段落一結束', start: 0, end: 1 }, // 對到 0-4
        { text: '那', start: 1.05, end: 1.1 }, // ← LLM 把這字改掉了,該失配
        { text: '那段內容也很重要', start: 1.2, end: 3 }, // 應對到 206
      ]
      // duration = 3,cps = 215/3 ≈ 71.67
      // seg 1 「那」timeDelta=0.05, expected=5 + 0.05×71.67 ≈ 8.58
      // 沒 threshold: forward = 206 (那段內容也...的那), chosen=206, drift=197
      //   → lastSearchIndex 變 207 → seg 2 「那段內容...」 indexOf from 207 = -1 → 失配!
      // 有 threshold (短字): allowedDrift = max(20, 0.05×71.67×1.5) = 20
      //   drift 197 > 20 → reject,當失配。lastSearchIndex 不變
      // seg 2 仍能從 lastSearchIndex(5) 找到「那段內容...」at 206 ✓

      const result = alignSegmentsToContent(segments, content)
      const segmentIndices = result.map((m) => m.segmentIndex)
      expect(segmentIndices).not.toContain(1) // 「那」被當失配跳過
      expect(segmentIndices).toContain(0) // seg 0 有 marker
      expect(segmentIndices).toContain(2) // seg 2 不受 cascade 影響,仍有 marker
      const seg2Result = result.find((m) => m.segmentIndex === 2)
      expect(seg2Result.textStartIndex).toBe(206)
    })

    it('時間軸緊接的短 segment 對到緊接位置，不被「同字後出現」吸引（local-anchored expected）', () => {
      // 模擬使用者實測 case 2:「？有，因為」中那個「有」緊接前段尾巴,
      // 但 content 後面還有另一個「有」。若用 seg.start × global_cps 算 expected
      // 容易 over-shoot 到後面的「有」(標點強化會讓全域 cps 比 local 高);
      // 用 lastSearchIndex + timeDelta × cps 把 expected 鎖在 local,正確選緊接位置。
      const content = '段落結束嗎' + '有' + 'XXXX' + '有過'
      // 段(0)落(1)結(2)束(3)嗎(4) 有(5) X(6-9) 有(10)過(11)，length=12
      const segments = [
        { text: '段落結束嗎', start: 0, end: 1 }, // 對到 0,結尾 lastSearchIndex=5
        { text: '有', start: 1.1, end: 1.2 }, // 緊接,該對到 5
      ]
      // duration = 1.2,cps = 12/1.2 = 10。
      // 全域 expected = 1.1 × 10 = 11 → backward 會挑到位置 10、forward -1 → 錯選 10。
      // local expected = lastSearchIndex(5) + (1.1-1)×10 = 6 → backward=5,forward=10,選 5。✓
      const result = alignSegmentsToContent(segments, content)
      expect(result.length).toBe(2)
      expect(result[1].textStartIndex).toBe(5)
    })

    it('silence segment（空文字）不應造成後續 expected 過度偏移（真實 case：兩個 SSK）', () => {
      // segment 285 是 silence（text=""），跳過後若不更新 lastSearchTime，
      // 下一個 "SSK" 的 timeDelta 被虛增，expected 飛到第二個 SSK 位置而非第一個。
      const content = '[皓棠] Blow跟Popper。\n[宗文] SSK愛丁堡，還有呢？拉圖。\n[宗文] 其實愛丁堡，還有另外一個，一個SSK，'
      const segments = [
        { text: 'Blow跟Popper', start: 920.65, end: 922.89 },
        { text: '', start: 922.89, end: 927.5 },  // silence
        { text: 'SSK', start: 932.46, end: 933.44 },
        { text: '愛丁堡', start: 933.44, end: 934.92 },
      ]
      const result = alignSegmentsToContent(segments, content)
      const sskMarker = result.find(m => m.text === 'SSK')
      expect(sskMarker).toBeDefined()
      // 第一個 SSK 在「[宗文] SSK愛丁堡」這行，不是結尾的「一個SSK」
      expect(sskMarker.textStartIndex).toBeLessThan(40)
    })

    it('使用者實測 case：「有」segment + 之後 segments 仍能對齊', () => {
      // 簡化版的 user-reported case:「有」在 transcript 出現幾百次,
      // segment.start = 410.52 (60% 進度) 該對到中後段位置
      const beforeY = 'X'.repeat(500) // 前段 500 字無「有」
      const yArea = '有'.repeat(50) // 中段大量「有」
      const afterY = 'Z'.repeat(450) // 後段
      const content = beforeY + yArea + afterY // 1000 chars total

      const segments = [
        { text: 'X', start: 0, end: 100 }, // 開頭某個 X
        { text: '有', start: 410.52, end: 410.76 }, // user 報的這個 segment
        { text: 'Z', start: 900, end: 1000 }, // 結尾某個 Z
      ]
      // totalDuration = 1000,charPerSecond = 1
      // 「有」expected ≈ 410 → 該對到位置 500~549 區間（最靠近 410 的是 500）
      const result = alignSegmentsToContent(segments, content)
      expect(result.length).toBe(3)
      expect(result[1].text).toBe('有')
      expect(result[1].textStartIndex).toBeGreaterThanOrEqual(500)
      expect(result[1].textStartIndex).toBeLessThanOrEqual(549)
      // 後續「Z」segment 仍能對齊（沒 cascade 失配）
      expect(result[2].text).toBe('Z')
      expect(result[2].textStartIndex).toBeGreaterThanOrEqual(550)
    })
  })
})
