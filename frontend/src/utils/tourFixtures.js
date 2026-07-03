// 新手導覽用的 demo 假資料（方案 C）
// 用於在「不建立真實後端任務」的前提下，展示任務列表卡片與任務詳情頁。
// 詳情頁的資料注入點在 useTranscriptData.loadTranscript（偵測 DEMO_ID 短路回此處資料）。

// 哨兵 taskId：路由 /transcript/__tour_demo__ 與列表卡片皆用此 id 辨識為 demo。
export const DEMO_ID = '__tour_demo__'

// 0.3 秒靜音 WAV（data URI）——讓 demo 的音檔播放器有合法來源、不會觸發載入錯誤。
const SILENT_WAV =
  'data:audio/wav;base64,UklGRoQJAABXQVZFZm10IBAAAAABAAEAQB8AAEAfAAABAAgAZGF0YWAJAACAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIA='

const CONTENT = {
  'zh-TW': {
    taskName: '示範會議錄音',
    tagName: '範例',
    speakerNames: { SPEAKER_01: '主持人', SPEAKER_02: '來賓' },
    segments: [
      {
        start: 0.0,
        end: 7.0,
        speaker: 'SPEAKER_01',
        text: '歡迎使用 SoundLite 逐字稿工具。很高興能與你相遇！',
      },
      { start: 7.0, end: 11.0, speaker: 'SPEAKER_02', text: 'SoundLite有什麼特色呢？' },
      {
        start: 11.0,
        end: 35.0,
        speaker: 'SPEAKER_01',
        text: 'SoundLite 以獨創的文字流文件模式，使你的使用體驗更貼近一般文書處理情境。我們也支援區分說話者和字幕模式，當然，錄音環境越安靜、說話口齒越清晰，辨識的正確率就會越高喔！',
      },
      { start: 35.0, end: 40.0, speaker: 'SPEAKER_02', text: '還有沒有其他很讚的功能？說來聽聽？' },
      {
        start: 40.0,
        end: 58.0,
        speaker: 'SPEAKER_01',
        text: '這裡分享一個新手小撇步，在文件模式中按下快捷鍵 Alt / Option，即可快速跳到某段文句對應的音檔位置，讓你來回聽打時有如神助！',
      },
      { start: 58.0, end: 63.0, speaker: 'SPEAKER_02', text: '好耶！我迫不及待想試試上傳音檔了！' },
      {
        start: 63.0,
        end: 111.0,
        speaker: 'SPEAKER_01',
        text: '在上傳音檔的流程中，考量使用者在錄音過程中可能發生的中斷或突發狀況，我們提供合併音檔與批次上傳的功能，減少事前彙整音檔的麻煩。逐字稿完成後，你可以直接在線上編輯內容、修正辨識結果、調整說話者名稱。SoundLite 也搭配 AI 功能快速整理重點、摘要內容、產生會議紀錄或萃取關鍵資訊，減少重複性的整理工作。所有修改都會即時儲存，方便你隨時回來繼續編輯，也能將成果匯出為不同格式，或以線上連結輕鬆分享給同事、研究夥伴或客戶。',
      },
    ],
  },
  en: {
    taskName: 'Sample meeting recording',
    tagName: 'Sample',
    speakerNames: { SPEAKER_01: 'Host', SPEAKER_02: 'Guest' },
    segments: [
      { start: 0.0, end: 4.2, speaker: 'SPEAKER_01', text: 'Hi everyone, welcome to today’s product meeting.' },
      { start: 4.2, end: 9.6, speaker: 'SPEAKER_02', text: 'Thanks. Let me quickly sync on last week’s progress.' },
      { start: 9.6, end: 15.0, speaker: 'SPEAKER_01', text: 'Sounds good, we’ll capture the key points in the transcript.' },
      { start: 15.0, end: 21.3, speaker: 'SPEAKER_02', text: 'We shipped the new upload flow, and feedback is better than expected.' },
    ],
  },
}

function pick(locale) {
  return (locale || '').startsWith('zh') ? CONTENT['zh-TW'] : CONTENT.en
}

// 段落內容帶上 [SPEAKER_01] 標記（與啟用說話者辨識的真實輸出一致）
function joinContent(segments) {
  return segments.map((s) => `[${s.speaker}] ${s.text}`).join('\n\n')
}

// 固定時間戳，避免每次渲染不同（與 demo 性質一致）
const DEMO_CREATED_AT = '2026-06-24T03:00:00.000Z'

// 給任務列表 TaskCard 用的 demo 卡片物件
export function buildDemoListTask(locale, status = 'completed', progressPercentage = 100) {
  const c = pick(locale)
  const content = joinContent(c.segments)
  return {
    __demo: true,
    task_id: DEMO_ID,
    status,
    custom_name: c.taskName,
    filename: `${c.taskName}.mp3`,
    file: { filename: `${c.taskName}.mp3` },
    timestamps: { created_at: DEMO_CREATED_AT, updated_at: DEMO_CREATED_AT },
    task_type: 'paragraph',
    tags: [c.tagName], // tags 為字串陣列（與 TaskTagsSection 渲染一致）
    result: { text_length: content.length, audio_file: true },
    audio_file: 'demo-audio',
    keep_audio: true,
    progress: progressPercentage,
    progress_percentage: progressPercentage,
  }
}

// 給詳情頁 useTranscriptData 注入用：currentTranscript 物件
export function buildDemoTranscript(locale) {
  const c = pick(locale)
  const content = joinContent(c.segments)
  return {
    task_id: DEMO_ID,
    status: 'completed',
    filename: `${c.taskName}.mp3`,
    custom_name: c.taskName,
    created_at: DEMO_CREATED_AT,
    updated_at: DEMO_CREATED_AT,
    text_length: content.length,
    // demo 不顯示音檔時長：真實播放器讀的是 0.3s 靜音 WAV，標一個假時長只會與播放器對不上
    duration_text: '',
    hasAudio: true,
    audioExpired: false,
    audioRetentionDays: 7,
    task_type: 'paragraph',
    summary_status: null, // null → AISummary 不在 mount 時打 API
    tags: [c.tagName], // tags 為字串陣列
    share_token: null,
    share_token_expires: null,
    content,
  }
}

export function getDemoSegments(locale) {
  // 補上 segments 在 UI 常用的欄位別名
  return pick(locale).segments.map((s, i) => ({
    ...s,
    index: i,
    start_time: s.start,
    end_time: s.end,
  }))
}

export function getDemoSpeakerNames(locale) {
  return { ...pick(locale).speakerNames }
}

export function getDemoAudioUrl() {
  return SILENT_WAV
}

// 導覽用的假 AI 摘要（展示「AI 摘要長怎樣」）
const DEMO_SUMMARY = {
  'zh-TW': {
    summary:
      '這是 SoundLite 的功能介紹示範：SoundLite 提供獨創的文字流文件模式，並支援說話者區分與字幕模式，適用於訪談、會議、課程、Podcast 等各種音訊與影片；上傳時可合併音檔與批次上傳，轉錄完成後能線上編輯、調整說話者，並用 AI 快速整理重點與摘要，所有修改即時儲存，也能匯出或以連結分享。',
    points: [
      '獨創文字流文件模式，支援說話者區分與字幕模式',
      '可合併音檔、批次上傳，適用會議／訪談／Podcast 等情境',
      '線上編輯搭配 AI 摘要重點，修改即時儲存並可匯出、分享',
    ],
  },
  en: {
    summary:
      'A sample summary of a product meeting: the team synced on last week’s progress, confirmed the new upload flow shipped with better-than-expected feedback, and will focus next on UX polish and planning.',
    points: [
      'New upload flow is complete and live',
      'User feedback is better than expected',
      'Next: UX polish and planning',
    ],
  },
}

export function getDemoSummary(locale) {
  return (locale || '').startsWith('zh') ? DEMO_SUMMARY['zh-TW'] : DEMO_SUMMARY.en
}
