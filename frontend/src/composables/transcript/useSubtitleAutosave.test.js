import { describe, it, expect, vi, beforeEach } from 'vitest'
import { ref } from 'vue'

// useSubtitleAutosave 內用 useI18n；測試環境給個極簡 stub（回傳 key 即可）
vi.mock('vue-i18n', () => ({
  useI18n: () => ({ t: (k) => k }),
}))

import { useSubtitleAutosave } from './useSubtitleAutosave.js'

function makeDeps(overrides = {}) {
  const groupedSegments = ref([
    {
      id: 'g1',
      speaker: 'SPEAKER_00',
      segments: [{ start: 0, end: 1, text: 'hi', speaker: 'SPEAKER_00' }],
    },
  ])
  const segments = ref([{ start: 0, end: 1, text: 'hi', speaker: 'SPEAKER_00' }])
  return {
    displayMode: ref('subtitle'),
    segments,
    speakerNames: ref({}),
    densityThreshold: ref(30),
    groupedSegments,
    currentTranscript: ref({ task_id: 't1', content: 'hi' }),
    headerRef: ref(null),
    saveTranscript: vi.fn().mockResolvedValue(true),
    updateSpeakerNames: vi.fn().mockResolvedValue(true),
    updateSubtitleSettings: vi.fn().mockResolvedValue(true),
    isMounted: () => true,
    isInitializing: () => false,
    isEditing: ref(false),
    originalSegments: ref([]),
    originalContent: ref('hi'),
    ...overrides,
  }
}

describe('useSubtitleAutosave — I1 speaker 變更路由', () => {
  beforeEach(() => vi.clearAllMocks())

  it('flag 開：speaker 變更走統一閘門（scheduleAutosave immediate），不直接呼叫 saveTranscript', () => {
    const scheduleAutosave = vi.fn()
    const deps = makeDeps({ autosaveEnabled: true, scheduleAutosave })
    const { updateSegmentSpeaker } = useSubtitleAutosave(deps)

    updateSegmentSpeaker({ groupId: 'g1', newSpeaker: 'SPEAKER_01' })

    expect(scheduleAutosave).toHaveBeenCalledTimes(1)
    expect(scheduleAutosave).toHaveBeenCalledWith({ immediate: true })
    expect(deps.saveTranscript).not.toHaveBeenCalled()
    // 本地狀態仍同步更新
    expect(deps.groupedSegments.value[0].speaker).toBe('SPEAKER_01')
    expect(deps.segments.value[0].speaker).toBe('SPEAKER_01')
  })

  it('flag 關：維持舊路徑，直接呼叫 saveTranscript（不碰 scheduleAutosave）', () => {
    const scheduleAutosave = vi.fn()
    const deps = makeDeps({ autosaveEnabled: false, scheduleAutosave })
    const { updateSegmentSpeaker } = useSubtitleAutosave(deps)

    updateSegmentSpeaker({ groupId: 'g1', newSpeaker: 'SPEAKER_01' })

    expect(scheduleAutosave).not.toHaveBeenCalled()
    expect(deps.saveTranscript).toHaveBeenCalledTimes(1)
    // 舊路徑：subtitle 模式存 segments
    expect(deps.saveTranscript.mock.calls[0][2]).toBe('subtitle')
  })
})
