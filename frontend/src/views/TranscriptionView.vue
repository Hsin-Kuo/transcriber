<template>
  <div class="container">
    <!-- SVG 濾鏡定義 -->
    <ElectricBorder />

    <!-- <header class="header">
      <h1>🎙️ Whisper Transcription Service</h1>
      <p>Upload audio files for automatic transcription with punctuation</p>
    </header> -->

    <!-- 上傳區域 -->
    <UploadZone @file-selected="handleFileUpload" :uploading="uploading" :disabled="!!pendingFile" />

    <!-- 確認表單（在上傳區下方） -->
    <div v-if="pendingFile" class="confirm-section electric-card">
        <div class="electric-inner">
          <div class="electric-border-outer">
            <div class="electric-main modal-body">
              <!-- 第一排：任務類型 + 檔案資訊 + 說話者辨識 + 標籤 -->
              <div class="confirm-row">
                <!-- 任務類型 -->
                <div class="modal-section task-type-section">
                  <label class="section-label">任務類型</label>

                  <div class="radio-group">
                    <label class="radio-item">
                      <input type="radio" name="taskType" value="paragraph" v-model="taskType" />
                      <span class="radio-label">段落</span>
                    </label>
                    <label class="radio-item">
                      <input type="radio" name="taskType" value="subtitle" v-model="taskType" />
                      <span class="radio-label">字幕</span>
                    </label>
                  </div>

                  <div class="task-type-hint">
                    <span v-if="taskType === 'paragraph'" class="hint">合併文字並添加標點符號，適合文章或筆記</span>
                    <span v-else class="hint">保留時間軸資訊，自動停用標點符號，適合字幕製作</span>
                  </div>
                </div>

                <!-- 檔案資訊 -->
                <div class="modal-section file-section">
                  <label class="section-label">檔案資訊</label>
                  <div class="file-info">
                    <span class="label">檔案名稱</span>
                    <span class="value">{{ pendingFile?.name }}</span>
                  </div>
                  <div class="file-info" v-if="pendingFile">
                    <span class="label">檔案大小</span>
                    <span class="value">{{ (pendingFile.size / 1024 / 1024).toFixed(2) }} MB</span>
                  </div>
                  <div class="file-note">
                    音檔保留規則：最多可保留3個音檔，超過會從最舊的依序刪除，亦可手動勾選保留。
                  </div>
                </div>

                <!-- 說話者辨識 -->
                <div class="modal-section diarize-section">
                  <label class="section-label">說話者辨識</label>

                  <label class="toggle-item">
                    <div class="toggle-wrapper">
                      <input type="checkbox" id="modal-diarize" v-model="enableDiarization" class="toggle-input" />
                      <span class="toggle-track">
                        <span class="toggle-thumb"></span>
                      </span>
                    </div>
                    <span class="toggle-label-text">啟用</span>
                  </label>

                  <div class="sub-setting" v-if="enableDiarization">
                    <label for="modal-maxSpeakers" class="sub-label">
                      最大講者人數
                      <span class="hint">可提高精確度，避免過度分析；留空則自動偵測。</span>
                    </label>
                    <input
                      type="number"
                      id="modal-maxSpeakers"
                      v-model.number="maxSpeakers"
                      min="2"
                      max="10"
                      placeholder="自動偵測"
                      class="number-input"
                    />
                  </div>
                </div>

                <!-- 標籤 -->
                <div class="modal-section tag-section">
                <label class="section-label">標籤</label>
                <div class="tag-input-container">
                  <div class="tag-input-wrapper">
                    <input
                      type="text"
                      v-model="tagInput"
                      @keydown.enter.prevent="addTag"
                      @keydown.comma.prevent="addTag"
                      placeholder="輸入標籤後按 Enter 或逗號"
                      class="text-input"
                    />
                    <button
                      type="button"
                      class="btn-add-tag"
                      @click="addTag"
                      :disabled="!tagInput.trim()"
                    >
                      新增
                    </button>
                  </div>

                  <!-- 快速選擇現有標籤 -->
                  <div v-if="availableQuickTags.length > 0" class="quick-tags-section">
                    <div class="quick-tags">
                      <button
                        v-for="tag in availableQuickTags"
                        :key="tag"
                        type="button"
                        class="quick-tag-btn"
                        @click="addQuickTag(tag)"
                        :title="`加入標籤：${tag}`"
                      >
                        + {{ tag }}
                      </button>
                    </div>
                  </div>

                  <div v-if="selectedTags.length > 0" class="selected-tags">
                    <span
                      v-for="(tag, index) in selectedTags"
                      :key="index"
                      class="selected-tag"
                    >
                      {{ tag }}
                      <button
                        type="button"
                        class="remove-tag"
                        @click="removeTag(index)"
                        title="移除標籤"
                      >
                        ×
                      </button>
                    </span>
                  </div>
                </div>
                </div>
              </div>

              <!-- 動作按鈕 -->
              <div class="modal-actions">
                <button class="btn btn-primary btn-start" @click="confirmAndUpload">開始轉錄</button>
                <button class="btn btn-secondary btn-cancel" @click="cancelUpload">取消</button>
              </div>
            </div>
          </div>
          <div class="electric-glow-1"></div>
          <div class="electric-glow-2"></div>
        </div>
        <div class="electric-overlay"></div>
        <div class="electric-bg-glow"></div>
    </div>

  </div>

</template>

<script setup>
import { ref, computed, onMounted, onUnmounted, watch, inject } from 'vue'
import api, { API_BASE, TokenManager } from '../utils/api'
import ElectricBorder from '../components/shared/ElectricBorder.vue'
import UploadZone from '../components/UploadZone.vue'

// 新 API 服務層
import { transcriptionService, taskService, legacyService } from '../api/services'

const showNotification = inject('showNotification')
const tasks = ref([])
const uploading = ref(false)
const taskType = ref('paragraph')  // 任務類型：paragraph（段落）或 subtitle（字幕）
const enableDiarization = ref(true)
const maxSpeakers = ref(null)
const pendingFile = ref(null)
const selectedTags = ref([])
const tagInput = ref('')
const showTranscriptDialog = ref(false)
const currentTranscript = ref({})
const loadingTranscript = ref(false)
const transcriptError = ref(null)
const isEditing = ref(false)
const savingTranscript = ref(false)
const originalContent = ref('')
const findText = ref('')
const replaceText = ref('')
const isComposing = ref(false)
const segments = ref([])
const timecodeMarkers = ref([])
const audioElement = ref(null)
const textarea = ref(null)
const transcriptContent = ref(null)
const textareaScrollHeight = ref(0)
const audioError = ref(null)
const activeTimecodeIndex = ref(-1)  // 當前活躍的 timecode 索引
const isPlaying = ref(false)  // 音檔播放狀態
// 自定義音檔播放器狀態
const progressBar = ref(null)
const currentTime = ref(0)
const duration = ref(0)
const progressPercent = ref(0)
const volume = ref(1)
const isMuted = ref(false)
const playbackRate = ref(1)
// 任務名稱編輯
const isEditingTitle = ref(false)
const editingTaskName = ref('')
const titleInput = ref(null)
const savingName = ref(false)

// 監聽對話框開關，控制背景滾動
watch(showTranscriptDialog, (newValue) => {
  if (newValue) {
    // 對話框打開時，禁用背景滾動
    document.body.style.overflow = 'hidden'
  } else {
    // 對話框關閉時，恢復背景滾動
    document.body.style.overflow = ''
  }
})

// 獲取所有唯一標籤
const allTags = computed(() => {
  const tags = new Set()
  tasks.value.forEach(task => {
    if (task.tags && task.tags.length > 0) {
      task.tags.forEach(tag => tags.add(tag))
    }
  })
  return Array.from(tags).sort()
})

// 可用的快速標籤（排除已選擇的）
const availableQuickTags = computed(() => {
  return allTags.value.filter(tag => !selectedTags.value.includes(tag))
})

// 選擇檔案後顯示確認表單
function handleFileUpload(file) {
  pendingFile.value = file
}

// 標籤管理
function addTag() {
  const tag = tagInput.value.trim()
  if (tag && !selectedTags.value.includes(tag)) {
    selectedTags.value.push(tag)
    tagInput.value = ''
  } else if (selectedTags.value.includes(tag)) {
    tagInput.value = ''
  }
}

function addQuickTag(tag) {
  if (!selectedTags.value.includes(tag)) {
    selectedTags.value.push(tag)
  }
}

function removeTag(index) {
  selectedTags.value.splice(index, 1)
}

// 載入任務列表
async function refreshTasks() {
  try {
    const response = await taskService.list({ limit: 20 })
    tasks.value = response.tasks || response || []
  } catch (error) {
    console.error('載入任務失敗:', error)
  }
}

// 確認後開始上傳
async function confirmAndUpload() {
  if (!pendingFile.value) return

  uploading.value = true

  const formData = new FormData()
  formData.append('file', pendingFile.value)
  formData.append('task_type', taskType.value)
  formData.append('punct_provider', 'gemini')
  formData.append('chunk_audio', 'true')
  formData.append('language', 'auto')  // 使用 Whisper 自動偵測語言
  formData.append('diarize', enableDiarization.value ? 'true' : 'false')
  if (enableDiarization.value && maxSpeakers.value) {
    formData.append('max_speakers', maxSpeakers.value.toString())
  }
  if (selectedTags.value.length > 0) {
    formData.append('tags', JSON.stringify(selectedTags.value))
  }

  try {
    // 使用新 API 服務層
    const responseData = await transcriptionService.create(formData)

    const newTask = {
      ...responseData,
      file: pendingFile.value.name,
      uploadedAt: new Date().toLocaleString('zh-TW')
    }

    tasks.value.unshift(newTask)

    // 顯示轉錄中通知
    if (showNotification) {
      showNotification({
        title: '轉錄中',
        message: `正在轉錄「${pendingFile.value.name}」`,
        type: 'processing',
        duration: 5000  // 5秒後自動關閉
      })
    }
  } catch (error) {
    console.error('上傳失敗:', error)
    if (showNotification) {
      showNotification({
        title: '上傳失敗',
        message: error.response?.data?.detail || error.message,
        type: 'error',
        duration: 5000
      })
    } else {
      alert('上傳失敗：' + (error.response?.data?.detail || error.message))
    }
  } finally {
    uploading.value = false
    pendingFile.value = null
    taskType.value = 'paragraph'  // 重置為預設值
    selectedTags.value = []
    tagInput.value = ''
  }
}

// 取消上傳
function cancelUpload() {
  pendingFile.value = null
  taskType.value = 'paragraph'  // 重置為預設值
  selectedTags.value = []
  tagInput.value = ''
}



// 改進的 timecode 匹配：結合位置和內容匹配
function findActiveTimecode(charOffset) {
  if (timecodeMarkers.value.length === 0) return -1

  const content = currentTranscript.value.content
  const contextLength = 30 // 用於匹配的上下文長度

  // 取得當前位置的文字片段
  const currentText = content.substring(
    Math.max(0, charOffset - contextLength),
    Math.min(content.length, charOffset + contextLength)
  ).trim()

  // Binary search 找到位置最接近的 marker
  let left = 0
  let right = timecodeMarkers.value.length - 1
  let closest = 0

  while (left <= right) {
    const mid = Math.floor((left + right) / 2)
    const marker = timecodeMarkers.value[mid]

    if (marker.charPosition <= charOffset) {
      closest = mid
      left = mid + 1
    } else {
      right = mid - 1
    }
  }

  // 在附近的 markers 中尋找內容最匹配的（考慮編輯造成的偏移）
  const searchRange = 3 // 前後搜尋 3 個 markers
  const startIdx = Math.max(0, closest - searchRange)
  const endIdx = Math.min(timecodeMarkers.value.length - 1, closest + searchRange)

  let bestMatch = closest
  let bestScore = 0

  for (let i = startIdx; i <= endIdx; i++) {
    const marker = timecodeMarkers.value[i]

    // 找到對應的 segment
    const segment = segments.value.find(s => Math.abs(s.start - marker.time) < 0.1)
    if (!segment) continue

    // 計算文字相似度（簡單的子字串匹配）
    const segmentText = segment.text.trim()
    let score = 0

    // 檢查當前文字片段是否包含 segment 的部分內容
    const segmentWords = segmentText.split(/\s+/).filter(w => w.length > 2)
    for (const word of segmentWords) {
      if (currentText.includes(word)) {
        score += word.length
      }
    }

    // 距離懲罰：距離越遠，分數越低
    const distancePenalty = Math.abs(i - closest) * 10
    score -= distancePenalty

    if (score > bestScore) {
      bestScore = score
      bestMatch = i
    }
  }

  // 如果找到了明顯更好的匹配（分數 > 0），使用它；否則用位置最近的
  return bestScore > 0 ? bestMatch : closest
}

// 計算字符的視覺寬度（區分中文、英文等）
function getCharWidth(char) {
  const code = char.charCodeAt(0)

  // 中文字符（CJK 統一表意文字）
  if ((code >= 0x4E00 && code <= 0x9FFF) ||   // 基本漢字
      (code >= 0x3400 && code <= 0x4DBF) ||   // 擴展 A
      (code >= 0x20000 && code <= 0x2A6DF) || // 擴展 B
      (code >= 0xF900 && code <= 0xFAFF) ||   // 兼容漢字
      (code >= 0x2E80 && code <= 0x2EFF) ||   // 部首補充
      (code >= 0x3000 && code <= 0x303F)) {   // CJK 符號和標點
    return 15 // 15px (等於 font-size)
  }

  // 全角符號
  if (code >= 0xFF00 && code <= 0xFFEF) {
    return 15
  }

  // 英文、數字、半角符號
  if ((code >= 0x0020 && code <= 0x007E) ||   // 基本拉丁字母
      (code >= 0x00A0 && code <= 0x00FF)) {   // 拉丁補充
    return 8.5 // 約 0.57 倍的 font-size
  }

  // 其他字符（預設）
  return 10
}

// 計算一行文字的視覺寬度（像素）
function calculateLineWidth(line) {
  let width = 0
  for (let i = 0; i < line.length; i++) {
    width += getCharWidth(line[i])
  }
  return width
}

// 基於換行符和實際行數精確計算字符偏移量
function estimateCharOffsetFromScroll(targetScrollTop) {
  if (!textarea.value) return 0

  const content = currentTranscript.value.content
  const lineHeight = parseFloat(getComputedStyle(textarea.value).lineHeight) || 27 // line-height: 1.8, font-size: 15px

  // 取得實際可用寬度（扣除 padding）
  const computedStyle = getComputedStyle(textarea.value)
  const paddingLeft = parseFloat(computedStyle.paddingLeft) || 0
  const paddingRight = parseFloat(computedStyle.paddingRight) || 0
  const textareaWidth = textarea.value.clientWidth - paddingLeft - paddingRight

  // 計算目標滾動位置對應的行數
  const targetLineNumber = Math.floor(targetScrollTop / lineHeight)

  // 分割文字為行（根據換行符）
  const lines = content.split('\n')

  // 累計字符數，找到對應的行
  let charOffset = 0
  let currentLine = 0

  for (let i = 0; i < lines.length && currentLine < targetLineNumber; i++) {
    const line = lines[i]

    // 計算這一行的實際視覺寬度
    const lineWidth = calculateLineWidth(line)

    // 計算這一行會佔用多少視覺行（考慮自動換行）
    const visualLines = Math.max(1, Math.ceil(lineWidth / textareaWidth))

    if (currentLine + visualLines <= targetLineNumber) {
      // 整行都在目標行之前
      charOffset += line.length + 1 // +1 for \n
      currentLine += visualLines
    } else {
      // 目標位置在這一行的中間
      const remainingLines = targetLineNumber - currentLine
      const targetWidthInLine = remainingLines * textareaWidth

      // 累積字符直到達到目標寬度
      let accumulatedWidth = 0
      let charsInLine = 0

      for (let j = 0; j < line.length; j++) {
        const charWidth = getCharWidth(line[j])
        if (accumulatedWidth + charWidth > targetWidthInLine) {
          break
        }
        accumulatedWidth += charWidth
        charsInLine++
      }

      charOffset += charsInLine
      break
    }
  }

  return Math.min(charOffset, content.length)
}

// 滾動時更新活躍的 timecode
function syncScroll() {
  if (!textarea.value) return

  // 1. 計算基準線位置（視窗頂部向下 25% 的位置）
  const referenceLineOffset = textarea.value.clientHeight * 0.25
  const referenceScrollTop = textarea.value.scrollTop + referenceLineOffset

  // 2. 將基準線滾動位置轉換為字符偏移量（使用二分搜索 + 換行符計算）
  const estimatedCharOffset = estimateCharOffsetFromScroll(referenceScrollTop)
  const scrollPercent = referenceScrollTop / textarea.value.scrollHeight

  // 3. 使用 binary search 找到對應的 timecode
  const newActiveIndex = findActiveTimecode(estimatedCharOffset)

  // 4. 調試信息：顯示當前位置的文字片段和對應的 segment
  if (newActiveIndex !== activeTimecodeIndex.value) {
    activeTimecodeIndex.value = newActiveIndex

    // 顯示基準線位置附近的文字片段（幫助調試）
    const textAtReference = currentTranscript.value.content.substring(
      Math.max(0, estimatedCharOffset - 30),
      Math.min(currentTranscript.value.content.length, estimatedCharOffset + 30)
    )

    const marker = timecodeMarkers.value[newActiveIndex]

    // 找到對應的 segment
    let correspondingSegment = null
    if (marker && segments.value.length > 0) {
      // 找到時間最接近 marker 的 segment
      correspondingSegment = segments.value.reduce((closest, seg) => {
        const currentDiff = Math.abs(seg.start - marker.time)
        const closestDiff = Math.abs(closest.start - marker.time)
        return currentDiff < closestDiff ? seg : closest
      })
    }

    const lineHeight = parseFloat(getComputedStyle(textarea.value).lineHeight) || 27
    const targetLine = Math.floor((textarea.value.scrollTop + textarea.value.clientHeight * 0.25) / lineHeight)

    console.log(`🎯 滾動 ${(scrollPercent * 100).toFixed(1)}% (scrollTop: ${textarea.value.scrollTop.toFixed(0)}px)`)
    console.log(`   目標行: ${targetLine} (行高: ${lineHeight.toFixed(1)}px) → 字符 ${estimatedCharOffset}/${currentTranscript.value.content.length}`)
    console.log(`   顯示 Timecode: ${marker?.label || 'N/A'} (charPos: ${marker?.charPosition})`)
    console.log(`   基準線文字: "...${textAtReference.replace(/\n/g, '↵')}..."`)
    if (correspondingSegment) {
      console.log(`   Segment文字: "${correspondingSegment.text.trim().substring(0, 60).replace(/\n/g, '↵')}..."`)
    }
  }
}

// 更新 textarea 的 scrollHeight
function updateScrollHeight() {
  if (textarea.value) {
    // 使用 nextTick 確保 DOM 更新後再計算高度
    setTimeout(() => {
      textareaScrollHeight.value = textarea.value.scrollHeight
    }, 0)
  }
}

// 生命週期
onMounted(() => {
  refreshTasks()
  // 限制視窗高度
  document.body.classList.add('upload-page')
})

onUnmounted(() => {
  // 清理：移除視窗高度限制
  document.body.classList.remove('upload-page')
})
</script>

<style scoped>
.container {
  animation: fadeIn 0.5s ease-in;
}

@keyframes fadeIn {
  from {
    opacity: 0;
    transform: translateY(20px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

.header {
  text-align: center;
  color: #2d2d2d;
  margin-bottom: 30px;
}

.header h1 {
  font-size: 36px;
  margin-bottom: 10px;
  text-shadow: 0 2px 8px rgba(139, 69, 19, 0.3);
  font-weight: 700;
}

.header p {
  font-size: 16px;
  opacity: 0.8;
}

/* 確認表單區域（在上傳區下方） */
.confirm-section {
  width: 100%;
  max-width: 800px;
  margin: 20px auto 0;
  animation: slideDown 0.3s ease;
}

@keyframes slideDown {
  from {
    opacity: 0;
    transform: translateY(-20px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

/* 確認對話框（保留用於其他對話框） */
.modal-overlay {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(0, 0, 0, 0.3);
  backdrop-filter: blur(8px);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
  animation: fadeIn 0.3s ease;
}

.modal-content {
  width: 90%;
  max-width: 500px;
  animation: slideUp 0.3s ease;
}

@keyframes slideUp {
  from {
    opacity: 0;
    transform: translateY(30px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

.modal-body {
  padding: 20px;
  overflow-y: auto;
  /* max-height 由 flex 布局自動處理，移除以避免衝突 */
}

/* 確認區響應式排版 */
.confirm-row {
  display: grid;
  grid-template-columns: 1fr 1fr 1fr 1fr;
  gap: 20px;
  margin-bottom: 20px;
}

/* 平板版：兩欄 */
@media (max-width: 1024px) {
  .confirm-row {
    grid-template-columns: 1fr 1fr;
  }
}

/* 移動版：垂直排列 */
@media (max-width: 768px) {
  .confirm-row {
    grid-template-columns: 1fr;
    gap: 0;
  }

  .confirm-row .modal-section {
    margin-bottom: 20px;
  }
}

.modal-section {
  margin-bottom: 20px;
  padding-bottom: 16px;
  border-bottom: 1px solid rgba(221, 132, 72, 0.15);
}

.modal-section:last-of-type {
  border-bottom: none;
  padding-bottom: 0;
}

/* 確認區的 section 不需要底部邊框 */
.confirm-row .modal-section {
  border-bottom: none;
  padding-bottom: 0;
}

.section-label {
  display: block;
  font-size: 13px;
  color: rgba(45, 45, 45, 0.6);
  font-weight: 600;
  margin-bottom: 10px;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.file-info {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
  font-size: 14px;
}

.file-info:last-child {
  margin-bottom: 0;
}

.file-info .label {
  color: rgba(45, 45, 45, 0.6);
  font-weight: 500;
}

.file-info .value {
  color: rgba(45, 45, 45, 0.95);
  font-weight: 600;
}

.file-note {
  margin-top: 12px;
  padding-top: 12px;
  border-top: 1px solid rgba(163, 177, 198, 0.2);
  font-size: 11px;
  line-height: 1.5;
  color: var(--neu-text-light);
  font-style: italic;
}

/* Neumorphism Toggle 開關 */
.toggle-item {
  display: flex;
  align-items: center;
  gap: 12px;
  cursor: pointer;
  user-select: none;
}

.toggle-wrapper {
  position: relative;
  width: 40px;
  height: 22px;
}

.toggle-input {
  opacity: 0;
  width: 0;
  height: 0;
  position: absolute;
}

.toggle-track {
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: var(--neu-bg);
  border-radius: 11px;
  transition: all 0.3s ease;
  box-shadow: var(--neu-shadow-inset);
}

.toggle-thumb {
  position: absolute;
  top: 3px;
  left: 3px;
  width: 16px;
  height: 16px;
  background: var(--neu-bg);
  border-radius: 50%;
  transition: all 0.3s ease;
  box-shadow: var(--neu-shadow-btn-sm);
}

.toggle-input:checked + .toggle-track {
  background: linear-gradient(145deg, #c8e6c9, #a5d6a7);
}

.toggle-input:checked + .toggle-track .toggle-thumb {
  transform: translateX(18px);
  box-shadow: var(--neu-shadow-btn-hover-sm);
}

.toggle-item:hover .toggle-track {
  box-shadow: var(--neu-shadow-inset-hover);
}

.toggle-item:hover .toggle-input:checked + .toggle-track {
  background: linear-gradient(145deg, #b8d6b9, #95c697);
}

.toggle-label-text {
  font-size: 14px;
  color: var(--neu-text);
  font-weight: 500;
}

/* Radio 群組 */
.radio-group {
  display: flex;
  gap: 16px;
  margin-bottom: 10px;
}

.radio-item {
  display: flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
  user-select: none;
}

.radio-item input[type="radio"] {
  width: 18px;
  height: 18px;
  cursor: pointer;
  accent-color: var(--electric-primary);
}

.radio-label {
  font-size: 14px;
  color: var(--neu-text);
  font-weight: 500;
}

.task-type-hint {
  margin-top: 8px;
}

.task-type-hint .hint {
  font-size: 12px;
  color: rgba(45, 45, 45, 0.6);
  font-weight: 400;
  line-height: 1.4;
}

.sub-setting {
  margin-top: 14px;
  padding-left: 28px;
  animation: slideDown 0.2s ease;
}

@keyframes slideDown {
  from {
    opacity: 0;
    transform: translateY(-10px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

.sub-label {
  display: block;
  font-size: 13px;
  color: rgba(45, 45, 45, 0.8);
  font-weight: 500;
  margin-bottom: 8px;
}

.sub-label .hint {
  display: block;
  font-size: 12px;
  color: rgba(45, 45, 45, 0.6);
  font-weight: 400;
  margin-top: 4px;
}

.select-input {
  width: 100%;
  padding: 10px 12px;
  font-size: 14px;
  border: 2px solid rgba(221, 132, 72, 0.3);
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.9);
  color: #2d2d2d;
  transition: all 0.3s;
  cursor: pointer;
}

.select-input:focus {
  outline: none;
  border-color: var(--electric-primary);
  box-shadow: 0 0 0 3px rgba(221, 132, 72, 0.1);
}

.number-input {
  width: 100%;
  padding: 10px 12px;
  font-size: 14px;
  border: 2px solid rgba(221, 132, 72, 0.3);
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.9);
  color: #2d2d2d;
  transition: all 0.3s;
}

.number-input:focus {
  outline: none;
  border-color: var(--electric-primary);
  box-shadow: 0 0 0 3px rgba(221, 132, 72, 0.1);
}

.number-input::placeholder {
  color: rgba(45, 45, 45, 0.4);
}

/* 標籤輸入樣式 */
.tag-input-container {
  margin-top: 10px;
}

.tag-input-wrapper {
  display: flex;
  gap: 8px;
  margin-bottom: 12px;
}

.tag-input-wrapper .text-input {
  flex: 1;
  padding: 10px 12px;
  font-size: 14px;
  border: 2px solid rgba(221, 132, 72, 0.3);
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.9);
  color: #2d2d2d;
  transition: all 0.3s;
}

.tag-input-wrapper .text-input:focus {
  outline: none;
  border-color: var(--electric-primary);
  box-shadow: 0 0 0 3px rgba(221, 132, 72, 0.1);
}

.btn-add-tag {
  padding: 10px 20px;
  font-size: 14px;
  font-weight: 500;
  color: white;
  background: #77969A;
  border: none;
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.3s;
  white-space: nowrap;
}

.btn-add-tag:hover:not(:disabled) {
  background: #336774;
  transform: translateY(-1px);
  box-shadow: 0 4px 12px rgba(119, 150, 154, 0.3);
}

.btn-add-tag:disabled {
  background: rgba(119, 150, 154, 0.4);
  cursor: not-allowed;
}

/* 快速標籤選擇區 */
.quick-tags-section {
  margin-bottom: 12px;
  padding: 10px;
  background: rgba(119, 150, 154, 0.05);
  border-radius: 8px;
  border: 1px dashed rgba(119, 150, 154, 0.2);
}

.quick-tags-label {
  display: inline-block;
  font-size: 12px;
  font-weight: 600;
  color: rgba(119, 150, 154, 0.8);
  margin-bottom: 8px;
}

.quick-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 8px;
}

.quick-tag-btn {
  padding: 5px 12px;
  font-size: 12px;
  font-weight: 500;
  color: #77969A;
  background: white;
  border: 1.5px solid rgba(119, 150, 154, 0.3);
  border-radius: 10px;
  cursor: pointer;
  transition: all 0.2s;
}

.quick-tag-btn:hover {
  background: rgba(119, 150, 154, 0.1);
  border-color: #77969A;
  transform: translateY(-1px);
  box-shadow: 0 2px 6px rgba(119, 150, 154, 0.15);
}

.quick-tag-btn:active {
  transform: translateY(0);
}

.selected-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.selected-tag {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px 12px;
  background: rgba(102, 126, 234, 0.15);
  border: 1px solid rgba(102, 126, 234, 0.3);
  border-radius: 12px;
  font-size: 13px;
  font-weight: 500;
  color: #667eea;
  transition: all 0.2s;
}

.selected-tag:hover {
  background: rgba(102, 126, 234, 0.2);
  border-color: rgba(102, 126, 234, 0.4);
}

.remove-tag {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 18px;
  height: 18px;
  padding: 0;
  margin: 0;
  background: rgba(102, 126, 234, 0.2);
  border: none;
  border-radius: 50%;
  color: #667eea;
  font-size: 16px;
  line-height: 1;
  cursor: pointer;
  transition: all 0.2s;
}

.remove-tag:hover {
  background: rgba(239, 68, 68, 0.2);
  color: #ef4444;
}

/* 信息提示框 */
.info-section {
  margin-top: 20px;
  border: none;
  padding: 0;
}

.info-box {
  display: flex;
  gap: 12px;
  padding: 14px 16px;
  background: linear-gradient(135deg, rgba(221, 132, 72, 0.08) 0%, rgba(221, 132, 72, 0.04) 100%);
  border-left: 3px solid var(--electric-primary);
  border-radius: 8px;
  align-items: flex-start;
}

.info-icon {
  flex-shrink: 0;
  color: var(--electric-primary);
  margin-top: 2px;
}

.info-text {
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: 14px;
  color: #5d4e37;
  line-height: 1.5;
}

.info-text strong {
  color: var(--electric-primary);
  font-weight: 600;
}

.info-text span {
  color: #6d5d47;
}

.modal-actions {
  display: flex;
  gap: 12px;
  margin-top: 24px;
  justify-content: center;
  align-items: center;
}

.modal-actions .btn {
  padding: 12px 32px;
  font-size: 15px;
  font-weight: 600;
}

.modal-actions .btn-cancel {
  padding: 8px 20px;
  font-size: 13px;
}

/* 開始轉錄按鈕 - 使用者頭貼風格 */
.modal-actions .btn-start {
  background: var(--neu-bg);
  color: var(--neu-primary);
  box-shadow: var(--neu-shadow-btn);
}

.modal-actions .btn-start:hover {
  box-shadow: var(--neu-shadow-btn-hover);
  color: var(--neu-primary-dark);
}

.modal-actions .btn-start:active {
  box-shadow: var(--neu-shadow-btn-active);
}

</style>
