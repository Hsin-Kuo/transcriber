<template>
  <div class="task-type-cards" role="radiogroup" :aria-label="$t('transcription.taskTypeSelectAria')">
    <!-- 文件模式 -->
    <label class="type-card" :class="{ selected: selected === 'paragraph' }">
      <input type="radio" :name="name" value="paragraph" v-model="selected" class="type-card-input" />
      <span class="type-card-preview preview-doc" aria-hidden="true">
        <span v-for="(para, i) in docPreview" :key="i" class="pd-para">{{ para }}</span>
      </span>
      <div class="type-card-info">
        <span class="type-card-title">{{ $t('transcription.paragraph') }}</span>
        <ul class="type-card-features">
          <li v-for="(f, i) in docFeatures" :key="i" class="feat-item" :class="{ off: !f.ok }">
            <svg v-if="f.ok" class="feat-mark" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><polyline points="20 6 9 17 4 12"></polyline></svg>
            <svg v-else class="feat-mark" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg>
            <span>{{ f.label }}</span>
          </li>
        </ul>
      </div>
      <span class="type-card-check" aria-hidden="true">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round">
          <polyline points="20 6 9 17 4 12"></polyline>
        </svg>
      </span>
    </label>

    <!-- 字幕模式 -->
    <label class="type-card" :class="{ selected: selected === 'subtitle' }">
      <input type="radio" :name="name" value="subtitle" v-model="selected" class="type-card-input" />
      <span class="type-card-preview preview-sub" aria-hidden="true">
        <span v-for="(row, i) in subPreview" :key="i" class="ps-row">
          <span class="ps-time">{{ row.time }}</span>
          <span class="ps-cap">{{ row.text }}</span>
        </span>
      </span>
      <div class="type-card-info">
        <span class="type-card-title">{{ $t('transcription.subtitle') }}</span>
        <ul class="type-card-features">
          <li v-for="(f, i) in subFeatures" :key="i" class="feat-item" :class="{ off: !f.ok }">
            <svg v-if="f.ok" class="feat-mark" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><polyline points="20 6 9 17 4 12"></polyline></svg>
            <svg v-else class="feat-mark" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg>
            <span>{{ f.label }}</span>
          </li>
        </ul>
      </div>
      <span class="type-card-check" aria-hidden="true">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round">
          <polyline points="20 6 9 17 4 12"></polyline>
        </svg>
      </span>
    </label>
  </div>
</template>

<script setup>
// 任務類型選擇卡片（文件 / 字幕）：迷你預覽 + 特性列點。
// 由 TaskSettingsModal（單檔）與 BatchUploadModal（批次）共用，維持單一真實來源。
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

const props = defineProps({
  // v-model 綁定的任務類型：'paragraph' | 'subtitle'
  modelValue: { type: String, default: 'paragraph' },
  // radio group 的 name（同頁多組時避免互相干擾）
  name: { type: String, default: 'taskType' },
})
const emit = defineEmits(['update:modelValue'])

const selected = computed({
  get: () => props.modelValue,
  set: (val) => emit('update:modelValue', val),
})

const { locale } = useI18n()
const isZh = computed(() => (locale.value || '').startsWith('zh'))

// 文件模式：合併成有標點的連續段落（在「無論…」處分段）
const docPreview = computed(() =>
  isZh.value
    ? [
        '歡迎使用 SoundLite。很高興能與你相遇，讓我們一起開啟高效辦公與學習的新體驗！',
        '無論你是第一次接觸 AI 語音轉文字工具，或是已經有使用逐字稿服務的經驗，我們都希望讓每一次轉錄都變得更快速、更準確，也更貼近你的工作流程。',
      ]
    : [
        'Welcome to SoundLite. We are glad to meet you — let’s begin a new experience of productive work and learning!',
        'Whether this is your first time with an AI speech-to-text tool or you already use transcription services, we want every transcription to be faster, more accurate, and a better fit for your workflow.',
      ],
)
// 字幕模式：保留時間軸、逐句分行、不加標點
const subPreview = computed(() =>
  isZh.value
    ? [
        { time: '00:00', text: '歡迎使用 SoundLite' },
        { time: '00:03', text: '很高興能與你相遇' },
        { time: '00:06', text: '讓我們一起開啟高效辦公與學習的新體驗' },
      ]
    : [
        { time: '00:00', text: 'Welcome to SoundLite' },
        { time: '00:03', text: 'We are glad to meet you' },
        { time: '00:06', text: 'Let’s begin a new experience of productive work and learning' },
      ],
)

// 兩種模式的特性列點（✓ 支援 / ✗ 不支援）
const docFeatures = computed(() =>
  isZh.value
    ? [
        { ok: true, label: '段落文字' },
        { ok: true, label: '標點符號' },
        { ok: true, label: '時間資訊' },
        { ok: true, label: '適合文章或筆記' },
      ]
    : [
        { ok: true, label: 'Paragraph text' },
        { ok: true, label: 'Punctuation' },
        { ok: true, label: 'Timeline info' },
        { ok: true, label: 'Great for articles & notes' },
      ],
)
const subFeatures = computed(() =>
  isZh.value
    ? [
        { ok: true, label: '短句分行' },
        { ok: false, label: '標點符號' },
        { ok: true, label: '時間資訊' },
        { ok: true, label: '適合字幕製作' },
      ]
    : [
        { ok: true, label: 'Line-by-line' },
        { ok: false, label: 'Punctuation' },
        { ok: true, label: 'Timeline info' },
        { ok: true, label: 'Great for subtitles' },
      ],
)
</script>

<style scoped>
.task-type-cards {
  display: flex;
  gap: 12px;
}

.type-card {
  position: relative;
  flex: 1 1 0;
  min-width: 0; /* 允許壓縮，避免字幕預覽 nowrap 長句撐寬卡片 */
  display: flex;
  flex-direction: column;
  align-items: center;
  text-align: center;
  gap: 8px;
  padding: 18px 14px;
  border: 2px solid rgba(var(--color-primary-rgb), 0.2);
  border-radius: 14px;
  background: var(--color-bg-light);
  cursor: pointer;
  transition: border-color 0.2s, box-shadow 0.2s, transform 0.2s;
}

.type-card:hover {
  border-color: rgba(var(--color-primary-rgb), 0.45);
  transform: translateY(-1px);
}

.type-card.selected {
  border-color: var(--color-primary);
  box-shadow: 0 0 0 3px rgba(var(--color-primary-rgb), 0.12);
}

/* 真正的 radio 隱藏，保留鍵盤 / 無障礙 */
.type-card-input {
  position: absolute;
  opacity: 0;
  width: 0;
  height: 0;
}

.type-card-input:focus-visible + .type-card-preview {
  outline: 2px solid var(--color-primary);
  outline-offset: 4px;
}

/* 迷你預覽：用假逐字稿模擬文件 / 字幕的實際輸出樣子 */
.type-card-preview {
  width: 100%;
  height: 66px;
  padding: 8px 9px;
  border-radius: 8px;
  border: 1px solid rgba(var(--color-text-dark-rgb), 0.12);
  background: var(--color-white);
  box-shadow: 0 1px 2px rgba(var(--color-text-dark-rgb), 0.06);
  overflow: hidden;
  text-align: left;
  transition: border-color 0.2s, box-shadow 0.2s;
}

.type-card.selected .type-card-preview {
  border-color: rgba(var(--color-primary-rgb), 0.5);
  box-shadow: 0 0 0 2px rgba(var(--color-primary-rgb), 0.1);
}

/* 文件模式：合併成段落的連續文字（多段時逐段分行） */
.preview-doc {
  display: flex;
  flex-direction: column;
  gap: 0px;
}

.pd-para {
  font-size: 9px;
  line-height: 1.5;
  color: rgba(var(--color-text-dark-rgb), 0.72);
}

/* 字幕模式：時間碼 + 逐句分行（對齊 SubtitleTable 的 TIME / CONTENT 觀感） */
.preview-sub {
  display: flex;
  flex-direction: column;
  gap: 5px;
}

.ps-row {
  display: flex;
  align-items: baseline;
  gap: 5px;
  font-size: 9px;
  line-height: 1.3;
  white-space: nowrap;
  overflow: hidden;
}

.ps-time {
  flex: 0 0 auto;
  font-weight: 600;
  font-variant-numeric: tabular-nums;
  color: var(--color-primary);
  background: rgba(var(--color-primary-rgb), 0.1);
  border-radius: 3px;
  padding: 1px 3px;
}

.ps-cap {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  color: rgba(var(--color-text-dark-rgb), 0.72);
}

/* 標題（左）＋ 特性列點（右）左右排列 */
.type-card-info {
  width: 100%;
  display: flex;
  align-items: flex-start;
  justify-content: center;
  gap: 32px;
}

.type-card-title {
  flex: 0 0 auto;
  font-size: 15px;
  font-weight: 600;
  color: rgba(var(--color-text-dark-rgb), 0.9);
}

/* 特性列點：✓ 支援 / ✗ 不支援 */
.type-card-features {
  list-style: none;
  margin: 0;
  padding: 0;
  flex: 0 0 auto;
  display: flex;
  flex-direction: column;
  gap: 5px;
  text-align: left;
}

.feat-item {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  line-height: 1.3;
  color: rgba(var(--color-text-dark-rgb), 0.72);
}

.feat-mark {
  flex: 0 0 auto;
  width: 13px;
  height: 13px;
  color: var(--color-primary);
}

.feat-item.off {
  color: rgba(var(--color-text-dark-rgb), 0.42);
}

.feat-item.off .feat-mark {
  color: rgba(var(--color-text-dark-rgb), 0.35);
}

.type-card-check {
  position: absolute;
  top: 8px;
  right: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
  width: 22px;
  height: 22px;
  border-radius: 50%;
  background: var(--color-primary);
  color: var(--color-white);
  opacity: 0;
  transform: scale(0.6);
  transition: opacity 0.2s, transform 0.2s;
}

.type-card.selected .type-card-check {
  opacity: 1;
  transform: scale(1);
}

/* 手機：卡片改上下堆疊 */
@media (max-width: 600px) {
  .task-type-cards {
    flex-direction: column;
  }
}
</style>
