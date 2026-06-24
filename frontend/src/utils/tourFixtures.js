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
      { start: 0.0, end: 4.2, speaker: 'SPEAKER_01', text: '大家好，歡迎參加今天的產品會議。' },
      { start: 4.2, end: 9.6, speaker: 'SPEAKER_02', text: '謝謝，我先快速同步一下上週的進度。' },
      { start: 9.6, end: 15.0, speaker: 'SPEAKER_01', text: '好的，請開始，我們會把重點記在逐字稿裡。' },
      { start: 15.0, end: 21.3, speaker: 'SPEAKER_02', text: '我們完成了新版上傳流程，使用者回饋比預期更好。' },
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
  return segments.map((s) => `[${s.speaker}] ${s.text}`).join('\n')
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
    duration_text: '00:21',
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
      '這是一場產品會議的示範摘要：團隊同步了上週進度，確認新版上傳流程已上線，且使用者回饋優於預期，後續將聚焦在體驗優化與下一階段規劃。',
    points: [
      '新版上傳流程已完成並上線',
      '使用者回饋比預期更好',
      '下一步聚焦體驗優化與規劃',
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
