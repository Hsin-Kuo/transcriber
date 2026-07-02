/**
 * headerTips — 任務詳情頁 header 輪播「使用技巧」的靜態設定。
 *
 * 每則 tip 只描述「現有」功能，不引導不存在的操作。文案走 i18n
 * （transcriptDetail.tips.<key>），Alt/Option 之類的平台差異由文案內
 * 用 {mod} 佔位、composable 以 modifierKeyLabel 帶入。
 *
 * 欄位語意：
 * - id          穩定識別（不連續重複、debug 用）
 * - i18nKey     對應 transcriptDetail.tips.<i18nKey>
 * - modes       適用的 displayMode（'paragraph' | 'subtitle'）；命中才顯示
 * - requiresSpeaker    true 時僅在有講者辨識（hasSpeakerInfo）的任務顯示
 * - requiresCompleted  true 時僅在任務完成（isContentReady）後顯示
 * - requiresAudio      true 時僅在音檔仍存在（hasAudio，未過期刪除）時顯示
 * - requiresPin        true 時僅在方案支援釘選音檔（maxKeepAudio > 0）時顯示
 * - requiresNoPin      true 時僅在方案不支援釘選（free，maxKeepAudio = 0）時顯示
 * - weight      加權隨機的權重；越大越常出現（常用功能給高權重）
 *
 * 文案可用 {days} 佔位（音檔保留天數，由 useHeaderTips 帶入）。
 *
 * gate 判定集中在 useHeaderTips，改這裡只需維護內容與權重。
 */
export const HEADER_TIPS = [
  {
    id: 'audio-shortcuts',
    i18nKey: 'audioShortcuts',
    modes: ['paragraph', 'subtitle'],
    requiresSpeaker: false,
    requiresCompleted: true,
    weight: 5,
  },
  {
    id: 'click-time-jump',
    i18nKey: 'clickTimeJump',
    modes: ['subtitle'],
    requiresSpeaker: false,
    requiresCompleted: true,
    weight: 5,
  },
  {
    id: 'rename-speaker',
    i18nKey: 'renameSpeaker',
    modes: ['subtitle'],
    requiresSpeaker: true,
    requiresCompleted: true,
    weight: 3,
  },
  {
    id: 'timecode-markers',
    i18nKey: 'timecodeMarkers',
    modes: ['paragraph'],
    requiresSpeaker: false,
    requiresCompleted: true,
    weight: 3,
  },
  {
    id: 'alt-click-seek',
    i18nKey: 'altClickSeek',
    modes: ['paragraph'],
    requiresSpeaker: false,
    requiresCompleted: true,
    weight: 5,
  },
  {
    id: 'search-replace',
    i18nKey: 'searchReplace',
    modes: ['paragraph', 'subtitle'],
    requiresSpeaker: false,
    requiresCompleted: true,
    weight: 3,
  },
  {
    id: 'download-formats',
    i18nKey: 'downloadFormats',
    modes: ['subtitle'],
    requiresSpeaker: false,
    requiresCompleted: true,
    weight: 3,
  },
  {
    id: 'ai-summary',
    i18nKey: 'aiSummary',
    modes: ['paragraph', 'subtitle'],
    requiresSpeaker: false,
    requiresCompleted: true,
    weight: 2,
  },
  {
    id: 'share-link',
    i18nKey: 'shareLink',
    modes: ['paragraph', 'subtitle'],
    requiresSpeaker: false,
    requiresCompleted: true,
    weight: 2,
  },
  {
    id: 'dark-mode',
    i18nKey: 'darkMode',
    modes: ['paragraph', 'subtitle'],
    requiresSpeaker: false,
    requiresCompleted: false,
    weight: 1,
  },
  {
    id: 'audio-retention-pin',
    i18nKey: 'audioRetentionPin',
    modes: ['paragraph', 'subtitle'],
    requiresSpeaker: false,
    requiresCompleted: false,
    requiresAudio: true,
    requiresPin: true,
    weight: 2,
  },
  {
    id: 'audio-retention-free',
    i18nKey: 'audioRetentionFree',
    modes: ['paragraph', 'subtitle'],
    requiresSpeaker: false,
    requiresCompleted: false,
    requiresAudio: true,
    requiresNoPin: true,
    weight: 2,
  },
]
