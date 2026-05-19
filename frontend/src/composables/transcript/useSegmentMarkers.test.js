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

    it('MAX_CANDIDATES 上限：1 字 segment 在大量重複的 content 中不會掃描爆炸', () => {
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
  })
})
