<template>
  <div class="editor-container">
    <!-- 音檔管理區 -->
    <div class="files-section electric-card">
      <div class="files-content">
            <div class="files-header">
              <h3>📁 音檔列表 ({{ uploadedFiles.length }})</h3>
              <label class="btn btn-primary">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                  <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path>
                  <polyline points="17 8 12 3 7 8"></polyline>
                  <line x1="12" y1="3" x2="12" y2="15"></line>
                </svg>
                添加音檔
                <input
                  type="file"
                  @change="handleFileAdd"
                  accept="audio/*,video/*,.m4a,.mp3,.wav,.mp4,.flac,.ogg"
                  multiple
                  style="display: none"
                />
              </label>
            </div>

            <div v-if="uploadedFiles.length === 0" class="empty-state">
              <p>尚未上傳任何音檔</p>
              <p class="hint">點擊「添加音檔」開始</p>
            </div>

            <div v-else class="files-list">
              <div
                v-for="file in uploadedFiles"
                :key="file.id"
                :class="['file-item', { active: currentFileId === file.id }]"
                @click="selectFile(file.id)"
              >
                <div class="file-info">
                  <span class="file-icon">🎵</span>
                  <div class="file-details">
                    <div class="file-name">{{ file.name }}</div>
                    <div class="file-meta">
                      <span class="file-size">{{ formatFileSize(file.size) }}</span>
                      <span v-if="file.duration" class="file-duration">{{ formatDuration(file.duration) }}</span>
                    </div>
                  </div>
                </div>
                <div class="file-actions">
                  <button
                    @click.stop="removeFile(file.id)"
                    class="action-btn delete-btn"
                    title="移除"
                  >
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                      <line x1="18" y1="6" x2="6" y2="18"></line>
                      <line x1="6" y1="6" x2="18" y2="18"></line>
                    </svg>
                  </button>
                </div>
              </div>
            </div>
      </div>
    </div>

    <!-- 波形編輯器 -->
    <div v-if="currentFileId" class="editor-workspace">
      <WaveformViewer
        :audio-file="currentFile.file"
        :key="currentFileId"
        @regions-updated="handleRegionsUpdate"
        @duration-loaded="handleDurationLoaded"
        ref="waveformRef"
      />

      <RegionControls
        :regions="regions"
        :audio-duration="currentFile.duration || 0"
        @add-region="addRegion"
        @delete-region="deleteRegion"
        @play-region="playRegion"
      />

      <div class="editor-actions electric-card">
        <div class="actions-content">
              <button
                @click="clipSelectedRegions"
                :disabled="regions.length === 0 || processing"
                class="btn btn-primary"
              >
                剪輯選取區段 ({{ regions.length }})
              </button>
              <button
                @click="addCurrentFileAsClip"
                :disabled="processing"
                class="btn btn-accent"
              >
                添加完整檔案到列表
              </button>
        </div>
      </div>
    </div>

    <!-- 片段與合併管理 -->
    <div v-if="clips.length > 0 || uploadedFiles.length > 1" class="action-panels">
      <ClipManager
        :clips="clips"
        @clip-deleted="handleClipDelete"
      />

      <MergePanel
        :clips="clips"
        :source-files="uploadedFiles"
        :mode="mergeMode"
        @mode-changed="mergeMode = $event"
        @merge="handleMerge"
      />
    </div>

    <!-- 時間軸編輯器切換按鈕 -->
    <div v-if="clips.length > 0" class="timeline-toggle-section electric-card">
      <div class="timeline-toggle-content">
            <button @click="showTimeline = !showTimeline" class="btn btn-timeline">
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <polygon v-if="!showTimeline" points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"></polygon>
                <template v-else>
                  <line x1="18" y1="6" x2="6" y2="18"></line>
                  <line x1="6" y1="6" x2="18" y2="18"></line>
                </template>
              </svg>
              {{ showTimeline ? '關閉' : '✨ 開啟' }}時間軸編輯器
            </button>
            <p class="timeline-hint">拖曳排序片段、調整音量、淡入淡出效果 </p>
      </div>
    </div>

    <!-- 時間軸編輯器 -->
    <TimelineEditor
      v-if="showTimeline"
      :clips="clips"
      @timeline-export="handleTimelineExport"
    />

    <div v-if="processing" class="processing-overlay">
      <div class="spinner-large"></div>
      <p>{{ processingMessage }}</p>
    </div>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import WaveformViewer from '../components/editor/WaveformViewer.vue'
import RegionControls from '../components/editor/RegionControls.vue'
import ClipManager from '../components/editor/ClipManager.vue'
import MergePanel from '../components/editor/MergePanel.vue'
import TimelineEditor from '../components/timeline/TimelineEditor.vue'
import axios from 'axios'

const API_BASE = '/api'

const uploadedFiles = ref([])
const currentFileId = ref(null)
const regions = ref([])
const clips = ref([])
const mergeMode = ref('same-file-clips')
const processing = ref(false)
const processingMessage = ref('')
const waveformRef = ref(null)
const showTimeline = ref(false)
let fileIdCounter = 0

const currentFile = computed(() => {
  return uploadedFiles.value.find(f => f.id === currentFileId.value)
})

function handleFileAdd(event) {
  const files = Array.from(event.target.files)

  // 檢查大檔案並警告
  const largeFiles = files.filter(f => f.size > 100 * 1024 * 1024) // 100MB
  if (largeFiles.length > 0) {
    const fileNames = largeFiles.map(f => `${f.name} (${formatFileSize(f.size)})`).join('\n')
    const proceed = confirm(
      `⚠️ 偵測到大型音檔：\n\n${fileNames}\n\n` +
      `處理大檔案可能需要較長時間（1-3分鐘）。\n` +
      `建議：使用較小的檔案或先用其他工具剪輯。\n\n` +
      `是否繼續載入？`
    )
    if (!proceed) {
      event.target.value = ''
      return
    }
  }

  files.forEach(file => {
    const fileId = `file-${++fileIdCounter}-${Date.now()}`
    uploadedFiles.value.push({
      id: fileId,
      name: file.name,
      file: file,
      size: file.size,
      duration: null
    })
  })

  if (files.length > 0 && !currentFileId.value) {
    selectFile(uploadedFiles.value[uploadedFiles.value.length - 1].id)
  }

  event.target.value = ''
}

function selectFile(fileId) {
  currentFileId.value = fileId
  regions.value = []
}

function removeFile(fileId) {
  if (confirm('確定要移除此音檔？')) {
    uploadedFiles.value = uploadedFiles.value.filter(f => f.id !== fileId)
    if (currentFileId.value === fileId) {
      currentFileId.value = uploadedFiles.value[0]?.id || null
    }
  }
}

function handleDurationLoaded(duration) {
  if (currentFile.value) {
    currentFile.value.duration = duration
  }
}

function handleRegionsUpdate(newRegions) {
  regions.value = newRegions
}

async function clipSelectedRegions() {
  if (regions.value.length === 0 || !currentFile.value) return

  processing.value = true
  processingMessage.value = '正在剪輯音訊...'

  try {
    const formData = new FormData()
    formData.append('audio_file', currentFile.value.file)
    formData.append('regions', JSON.stringify(regions.value.map(r => ({
      start: r.start,
      end: r.end,
      id: r.id
    }))))

    const response = await axios.post(`${API_BASE}/audio/clip`, formData, {
      headers: { 'Content-Type': 'multipart/form-data' }
    })

    response.data.clips.forEach((clip, index) => {
      clips.value.push({
        id: clip.clip_id,
        name: `${currentFile.value.name} - 片段 ${clips.value.length + index + 1}`,
        filename: clip.filename,
        duration: clip.duration,
        source: currentFile.value.name,
        url: `${API_BASE}/audio/download/${clip.clip_id}`,
        type: 'clip'
      })
    })

    alert(`成功剪輯 ${response.data.clips.length} 個片段`)
    regions.value = []
  } catch (error) {
    console.error('剪輯失敗:', error)
    alert('剪輯失敗：' + (error.response?.data?.detail || error.message))
  } finally {
    processing.value = false
  }
}

async function addCurrentFileAsClip() {
  if (!currentFile.value) return

  processing.value = true
  processingMessage.value = '正在添加完整檔案...'

  try {
    const formData = new FormData()
    formData.append('audio_file', currentFile.value.file)
    formData.append('regions', JSON.stringify([{
      start: 0,
      end: currentFile.value.duration || 999999,
      id: 'full-file'
    }]))

    const response = await axios.post(`${API_BASE}/audio/clip`, formData)

    const clip = response.data.clips[0]
    clips.value.push({
      id: clip.clip_id,
      name: `📄 ${currentFile.value.name}`,
      filename: clip.filename,
      duration: clip.duration,
      source: currentFile.value.name,
      url: `${API_BASE}/audio/download/${clip.clip_id}`,
      type: 'full-file'
    })

    alert('完整檔案已添加到列表')
  } catch (error) {
    console.error('添加失敗:', error)
    alert('添加失敗：' + (error.response?.data?.detail || error.message))
  } finally {
    processing.value = false
  }
}

async function handleMerge(selectedItems) {
  if (selectedItems.length < 2) {
    alert('請至少選擇 2 個項目')
    return
  }

  processing.value = true
  processingMessage.value = '正在合併音訊...'

  try {
    const formData = new FormData()
    formData.append('clip_ids', JSON.stringify(selectedItems.map(item => item.id)))
    formData.append('mode', mergeMode.value)

    const response = await axios.post(`${API_BASE}/audio/merge`, formData)

    const downloadUrl = `${API_BASE}/audio/download/${response.data.merged_id}`
    window.open(downloadUrl, '_blank')

    alert('合併成功！正在下載...')
  } catch (error) {
    console.error('合併失敗:', error)
    alert('合併失敗：' + (error.response?.data?.detail || error.message))
  } finally {
    processing.value = false
  }
}

async function handleTimelineExport(timelineData) {
  processing.value = true
  processingMessage.value = '正在匯出時間軸音訊...'

  try {
    const formData = new FormData()
    formData.append('timeline_data', JSON.stringify(timelineData))

    // For now, use the existing merge endpoint
    // In Stage 3, we'll implement the dedicated /audio/arrange endpoint
    const clipIds = []
    timelineData.tracks.forEach(track => {
      track.clips.forEach(clip => {
        clipIds.push(clip.clipId)
      })
    })

    formData.append('clip_ids', JSON.stringify(clipIds))
    formData.append('mode', 'same-file-clips')

    const response = await axios.post(`${API_BASE}/audio/merge`, formData)

    const downloadUrl = `${API_BASE}/audio/download/${response.data.merged_id}`
    window.open(downloadUrl, '_blank')

    alert('時間軸匯出成功！正在下載...')
  } catch (error) {
    console.error('匯出失敗:', error)
    alert('匯出失敗：' + (error.response?.data?.detail || error.message))
  } finally {
    processing.value = false
  }
}

function formatDuration(seconds) {
  if (!seconds) return '0:00'
  const mins = Math.floor(seconds / 60)
  const secs = Math.floor(seconds % 60)
  return `${mins}:${secs.toString().padStart(2, '0')}`
}

function formatFileSize(bytes) {
  if (bytes < 1024) return bytes + ' B'
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB'
  return (bytes / (1024 * 1024)).toFixed(1) + ' MB'
}

function addRegion() {
  waveformRef.value?.addRegion()
}

function deleteRegion(id) {
  waveformRef.value?.deleteRegion(id)
}

function playRegion(region) {
  waveformRef.value?.playRegion(region)
}

function handleClipDelete(clipId) {
  clips.value = clips.value.filter(c => c.id !== clipId)
}
</script>

<style scoped>
/* CSS 變數 */
.editor-container {
  --color-primary: #DD8448;
  --color-text-muted: var(--color-text-muted);
  --color-text-secondary: var(--color-text-secondary);
  --color-danger: var(--color-danger);
  --gradient-dark: var(--gradient-dark);
}

.editor-container {
  min-height: calc(100vh - 200px);
}

.files-section {
  margin-bottom: 24px;
}

.files-content {
  padding: 24px;
  background: var(--gradient-dark);
}

.files-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 20px;
}

.files-header h3 {
  margin: 0;
  font-size: 1.3rem;
  color: #fff;
}

.files-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
  max-height: 300px;
  overflow-y: auto;
}

.file-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px;
  background: rgba(255, 255, 255, 0.03);
  border: 2px solid rgba(255, 255, 255, 0.1);
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.3s ease;
}

.file-item:hover {
  background: rgba(255, 255, 255, 0.05);
  border-color: rgba(221, 132, 72, 0.3);
}

.file-item.active {
  background: rgba(221, 132, 72, 0.15);
  border-color: rgba(221, 132, 72, 0.6);
}

.file-info {
  display: flex;
  align-items: center;
  gap: 12px;
  flex: 1;
}

.file-icon {
  font-size: 1.5rem;
}

.file-details {
  flex: 1;
}

.file-name {
  color: #fff;
  font-weight: 500;
  margin-bottom: 4px;
}

.file-meta {
  display: flex;
  gap: 12px;
  font-size: 0.85rem;
}

.file-size {
  color: var(--color-text-muted);
}

.file-duration {
  color: var(--color-primary);
  font-weight: 600;
}

.empty-state {
  text-align: center;
  padding: 40px 20px;
  color: var(--color-text-muted);
}

.empty-state p {
  margin: 8px 0;
}

.hint {
  font-size: 0.9rem;
  color: var(--color-text-secondary);
}

.editor-workspace {
  display: flex;
  flex-direction: column;
  gap: 24px;
  margin-bottom: 24px;
}

.actions-content {
  display: flex;
  justify-content: center;
  gap: 16px;
  padding: 24px;
  background: var(--gradient-dark);
}

.action-panels {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 24px;
  margin-top: 24px;
}

@media (max-width: 768px) {
  .action-panels {
    grid-template-columns: 1fr;
  }
}

.timeline-toggle-section {
  margin-top: 24px;
}

.timeline-toggle-content {
  padding: 24px;
  background: var(--gradient-dark);
  text-align: center;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
}

.btn-timeline {
  background: linear-gradient(135deg, #9b59b6 0%, #8e44ad 100%);
  color: white;
  font-size: 1.1rem;
}

.btn-timeline:hover {
  transform: translateY(-2px);
  box-shadow: 0 8px 16px rgba(155, 89, 182, 0.4);
}

.timeline-hint {
  color: var(--color-text-muted);
  font-size: 0.9rem;
  margin: 0;
}

.btn {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 12px 24px;
  border: none;
  border-radius: 8px;
  font-size: 1rem;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.3s ease;
}

.btn svg {
  stroke: currentColor;
}

.btn-primary {
  background: linear-gradient(135deg, #FF6B35 0%, var(--color-primary) 100%);
  color: white;
}

.btn-primary:hover:not(:disabled) {
  transform: translateY(-2px);
  box-shadow: 0 8px 16px rgba(255, 107, 53, 0.3);
}

.btn-accent {
  background: linear-gradient(135deg, #00b894 0%, #00cec9 100%);
  color: white;
}

.btn-accent:hover:not(:disabled) {
  transform: translateY(-2px);
  box-shadow: 0 8px 16px rgba(0, 184, 148, 0.3);
}

.btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.action-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  border: 1px solid rgba(255, 255, 255, 0.2);
  border-radius: 6px;
  background: rgba(255, 255, 255, 0.05);
  cursor: pointer;
  transition: all 0.2s ease;
}

.delete-btn {
  color: var(--color-danger);
}

.delete-btn:hover {
  border-color: rgba(244, 67, 54, 0.5);
  background: rgba(244, 67, 54, 0.1);
}

.processing-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.85);
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  z-index: 1000;
  color: white;
  backdrop-filter: blur(4px);
}

.spinner-large {
  width: 60px;
  height: 60px;
  border: 4px solid rgba(255, 255, 255, 0.1);
  border-top-color: var(--color-primary);
  border-radius: 50%;
  animation: spin 1s linear infinite;
  margin-bottom: 20px;
}

.processing-overlay p {
  font-size: 1.2rem;
  font-weight: 500;
}

.files-list::-webkit-scrollbar {
  width: 6px;
}

.files-list::-webkit-scrollbar-track {
  background: rgba(255, 255, 255, 0.05);
  border-radius: 3px;
}

.files-list::-webkit-scrollbar-thumb {
  background: rgba(221, 132, 72, 0.5);
  border-radius: 3px;
}
</style>
