<template>
  <div class="waveform-container electric-card">
    <div class="electric-inner">
      <div class="electric-border-outer">
        <div class="electric-main waveform-wrapper">
          <div class="waveform-container-inner">
            <div ref="waveformEl" class="waveform" :style="waveformStyle"></div>

            <!-- 刪除區段的標記線 -->
            <div v-if="deletedRegionsForDisplay.length > 0" class="deleted-markers">
              <div
                v-for="region in deletedRegionsForDisplay"
                :key="region.id"
                class="deleted-marker"
                :style="{
                  left: region.startPx + 'px',
                  width: region.widthPx + 'px'
                }"
              >
                <div class="marker-line marker-line-start"></div>
                <div class="marker-fill"></div>
                <div class="marker-line marker-line-end"></div>
              </div>
            </div>
          </div>

          <!-- 控制按鈕 -->
          <div class="waveform-controls">
            <button @click="playPause" class="control-btn" :class="{ active: isPlaying }">
              <svg v-if="!isPlaying" width="20" height="20" viewBox="0 0 24 24" fill="currentColor">
                <polygon points="5 3 19 12 5 21 5 3"></polygon>
              </svg>
              <svg v-else width="20" height="20" viewBox="0 0 24 24" fill="currentColor">
                <rect x="6" y="4" width="4" height="16"></rect>
                <rect x="14" y="4" width="4" height="16"></rect>
              </svg>
              {{ isPlaying ? '暫停' : '播放' }}
            </button>

            <button @click="stop" class="control-btn">
              <svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor">
                <rect x="6" y="6" width="12" height="12"></rect>
              </svg>
              停止
            </button>

            <button @click="addRegion" class="control-btn control-btn-primary">
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <rect x="3" y="3" width="18" height="18" rx="2" ry="2"></rect>
                <line x1="12" y1="8" x2="12" y2="16"></line>
                <line x1="8" y1="12" x2="16" y2="12"></line>
              </svg>
              新增區段
            </button>

            <div class="zoom-control">
              <label>縮放:</label>
              <input
                type="range"
                v-model="zoom"
                min="1"
                max="500"
                @input="handleZoom"
                class="zoom-slider"
              />
              <span class="zoom-value">{{ zoom }}x</span>
            </div>
          </div>

          <div class="waveform-hint">
            💡 提示：長音檔可使用<strong>滾動條</strong>或調整<strong>縮放</strong>來查看完整波形
          </div>

          <div v-if="loading" class="loading-overlay">
            <div class="spinner"></div>
            <p v-if="converting">🔄 正在轉換音檔格式...</p>
            <p v-else>正在處理音檔...</p>
            <p v-if="converting" class="loading-hint">⚡ 偵測到不支援的格式，正在自動轉換為 MP3</p>
            <p v-else class="loading-hint">📊 大檔案需要較長時間解碼和生成波形</p>
            <p v-if="!converting" class="loading-hint">💡 建議使用較小的檔案或先剪輯後再編輯</p>
          </div>

          <div v-if="errorMessage" class="error-overlay">
            <div class="error-icon">⚠️</div>
            <pre class="error-message">{{ errorMessage }}</pre>
            <button @click="errorMessage = ''" class="btn-dismiss">關閉</button>
          </div>
        </div>
      </div>
      <div class="electric-glow-1"></div>
      <div class="electric-glow-2"></div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, watch, onBeforeUnmount, computed } from 'vue'
import WaveSurfer from 'wavesurfer.js'
import RegionsPlugin from 'wavesurfer.js/dist/plugins/regions'

const props = defineProps({
  audioFile: {
    type: File,
    required: true
  }
})

const emit = defineEmits(['regions-updated', 'duration-loaded'])

const waveformEl = ref(null)
const wavesurfer = ref(null)
const regionsPlugin = ref(null)
const isPlaying = ref(false)
const zoom = ref(1)
const regions = ref([])
const loading = ref(false)
const errorMessage = ref('')
const converting = ref(false)
const currentAudioFile = ref(null)
const deletedRegionIds = ref(new Set()) // 追蹤已刪除的區段 ID
const deletedRegionsData = ref([]) // 儲存已刪除區段的位置資訊
const waveformWidth = ref(0)
const waveformHeight = ref(128)
const currentClipId = ref(Math.random().toString(36).substring(7))

// 快取已轉換的音檔，避免重複轉換
const convertedFilesCache = new Map()

// 計算已刪除區段的顯示資訊（包含像素位置）
const deletedRegionsForDisplay = computed(() => {
  if (!wavesurfer.value || deletedRegionsData.value.length === 0) {
    return []
  }

  const duration = wavesurfer.value.getDuration()
  if (!duration) return []

  const minPxPerSec = 50
  const pixelsPerSecond = minPxPerSec * zoom.value

  return deletedRegionsData.value.map(region => ({
    ...region,
    startPx: region.start * pixelsPerSecond,
    widthPx: (region.end - region.start) * pixelsPerSecond
  }))
})

// 計算保留區段（用於創建分段波形）
const keepRegions = computed(() => {
  if (!wavesurfer.value || deletedRegionsData.value.length === 0) {
    return []
  }

  const duration = wavesurfer.value.getDuration()
  if (!duration) return []

  const sortedDeleted = [...deletedRegionsData.value].sort((a, b) => a.start - b.start)
  const keeps = []
  let lastEnd = 0

  for (const region of sortedDeleted) {
    if (region.start > lastEnd) {
      keeps.push({
        start: lastEnd,
        end: region.start,
        id: `keep-${keeps.length}`
      })
    }
    lastEnd = Math.max(lastEnd, region.end)
  }

  if (lastEnd < duration) {
    keeps.push({
      start: lastEnd,
      end: duration,
      id: `keep-${keeps.length}`
    })
  }

  const minPxPerSec = 50
  const pixelsPerSecond = minPxPerSec * zoom.value

  // 計算壓縮後的位置（將保留區段緊密排列）
  let compressedPosition = 0
  return keeps.map(region => {
    const widthPx = (region.end - region.start) * pixelsPerSecond
    const result = {
      ...region,
      startPx: region.start * pixelsPerSecond,
      widthPx: widthPx,
      compressedStartPx: compressedPosition
    }
    compressedPosition += widthPx
    return result
  })
})

// 計算波形的容器樣式
const waveformContainerStyle = computed(() => {
  if (keepRegions.value.length === 0) {
    return {}
  }

  // 容器寬度是所有保留區段的總和
  const totalWidth = keepRegions.value.reduce((sum, r) => sum + r.widthPx, 0)
  return {
    width: totalWidth + 'px',
    overflow: 'visible'
  }
})

// 計算波形的遮罩樣式
const waveformStyle = computed(() => {
  if (keepRegions.value.length === 0 || !wavesurfer.value) {
    return {}
  }

  const duration = wavesurfer.value.getDuration()
  if (!duration) return {}

  const minPxPerSec = 50
  const pixelsPerSecond = minPxPerSec * zoom.value
  const totalWidth = duration * pixelsPerSecond

  // 創建 CSS mask-image 使用 linear-gradient
  // 保留區段顯示為黑色（可見），刪除區段顯示為透明（不可見）
  const gradientStops = []

  if (deletedRegionsForDisplay.value.length === 0) {
    return {}
  }

  const sortedDeleted = [...deletedRegionsForDisplay.value].sort((a, b) => a.startPx - b.startPx)

  let currentPos = 0
  sortedDeleted.forEach((deleted, index) => {
    // 保留區段（從上一個結束到這個刪除開始）
    if (deleted.startPx > currentPos) {
      const keepPercent1 = (currentPos / totalWidth * 100).toFixed(4)
      const keepPercent2 = (deleted.startPx / totalWidth * 100).toFixed(4)
      gradientStops.push(`black ${keepPercent1}%`)
      gradientStops.push(`black ${keepPercent2}%`)
    }

    // 刪除區段
    const deletePercent1 = (deleted.startPx / totalWidth * 100).toFixed(4)
    const deletePercent2 = ((deleted.startPx + deleted.widthPx) / totalWidth * 100).toFixed(4)
    gradientStops.push(`transparent ${deletePercent1}%`)
    gradientStops.push(`transparent ${deletePercent2}%`)

    currentPos = deleted.startPx + deleted.widthPx
  })

  // 最後的保留區段
  if (currentPos < totalWidth) {
    const keepPercent1 = (currentPos / totalWidth * 100).toFixed(4)
    gradientStops.push(`black ${keepPercent1}%`)
    gradientStops.push(`black 100%`)
  }

  const maskImage = `linear-gradient(to right, ${gradientStops.join(', ')})`

  return {
    maskImage: maskImage,
    WebkitMaskImage: maskImage
  }
})

onMounted(() => {
  initWavesurfer()
})

onBeforeUnmount(() => {
  wavesurfer.value?.destroy()

  // 清理快取的 ObjectURLs 以釋放記憶體
  convertedFilesCache.forEach(url => {
    URL.revokeObjectURL(url)
  })
  convertedFilesCache.clear()
})

watch(() => props.audioFile, (newFile) => {
  if (newFile) {
    loadAudio(newFile)
  }
})

// 當縮放改變時，強制重新計算已刪除區段的位置
watch(zoom, () => {
  // 觸發重新渲染以更新位置
  deletedRegionsData.value = [...deletedRegionsData.value]
})

function initWavesurfer() {
  // 創建 regions plugin
  regionsPlugin.value = RegionsPlugin.create()

  // 從 CSS 變數取得編輯器顏色
  const styles = getComputedStyle(document.documentElement)
  const waveColor = styles.getPropertyValue('--editor-waveform').trim() || '#DD8448'
  const progressColor = styles.getPropertyValue('--editor-progress').trim() || '#FF6B35'
  const cursorColor = styles.getPropertyValue('--editor-cursor').trim() || '#FFFFFF'

  // 創建 WaveSurfer 實例 - 優化大檔案效能
  wavesurfer.value = WaveSurfer.create({
    container: waveformEl.value,
    waveColor,
    progressColor,
    cursorColor,
    barWidth: 2,
    barGap: 1,
    barRadius: 2,
    height: 128,
    normalize: true,
    minPxPerSec: 50,  // 每秒至少 50 像素，確保長音檔可以滾動查看
    hideScrollbar: false,  // 顯示滾動條以便瀏覽長音檔
    autoScroll: true,  // 播放時自動滾動
    autoCenter: false,  // 關閉自動置中，讓滾動更順暢
    plugins: [regionsPlugin.value]
  })

  // 載入進度監聽
  wavesurfer.value.on('loading', (percent) => {
    loading.value = true
    console.log(`🎵 音檔解碼中: ${percent}%`)
  })

  // 解碼進度（大檔案會顯示此事件）
  wavesurfer.value.on('decode', (duration) => {
    console.log(`🔄 開始處理音檔，時長: ${duration.toFixed(2)}秒`)
  })

  // 事件監聽
  wavesurfer.value.on('ready', () => {
    loading.value = false
    const duration = wavesurfer.value.getDuration()
    emit('duration-loaded', duration)
    console.log(`✅ 音檔載入完成，時長: ${duration.toFixed(2)}秒`)
  })

  // 錯誤處理
  wavesurfer.value.on('error', async (error) => {
    loading.value = false
    console.error('❌ 音檔載入失敗:', error)

    // 檢查是否為格式不支援錯誤，如果是，嘗試自動轉換
    if ((error.message?.includes('NO_SUPPORTED_STREAMS') || error.code === 4) && currentAudioFile.value && !converting.value) {
      console.log('🔄 偵測到不支援的格式，嘗試自動轉換...')
      await tryConvertAndLoad()
    } else if (!converting.value) {
      // 其他錯誤直接顯示
      errorMessage.value = `載入失敗：${error.message || '未知錯誤'}`
    }
  })

  wavesurfer.value.on('play', () => {
    isPlaying.value = true
  })

  wavesurfer.value.on('pause', () => {
    isPlaying.value = false
  })

  wavesurfer.value.on('finish', () => {
    isPlaying.value = false
  })

  // 監聽播放位置，跳過已刪除的區段
  wavesurfer.value.on('timeupdate', (currentTime) => {
    checkAndSkipDeletedRegions(currentTime)
  })

  // 區段事件
  regionsPlugin.value.on('region-created', handleRegionCreated)
  regionsPlugin.value.on('region-updated', handleRegionUpdated)
  regionsPlugin.value.on('region-removed', handleRegionRemoved)
  regionsPlugin.value.on('region-clicked', (region, e) => {
    e.stopPropagation()
    region.play()
  })

  // 載入音檔
  if (props.audioFile) {
    loadAudio(props.audioFile)
  }
}

function loadAudio(file) {
  loading.value = true
  errorMessage.value = '' // 清除之前的錯誤訊息
  converting.value = false
  currentAudioFile.value = file // 儲存檔案以便轉換失敗時重試
  deletedRegionIds.value.clear() // 清空已刪除區段列表
  deletedRegionsData.value = [] // 清空已刪除區段的顯示資料
  console.log('🔄 Cleared deleted region IDs for new file')

  // 檢查是否已經轉換過此檔案
  const cacheKey = `${file.name}-${file.size}-${file.lastModified}`
  if (convertedFilesCache.has(cacheKey)) {
    console.log('✨ 使用快取的轉換檔案，跳過重複轉換')
    const cachedUrl = convertedFilesCache.get(cacheKey)
    wavesurfer.value.load(cachedUrl)
    return
  }

  // 載入原始檔案
  const url = URL.createObjectURL(file)
  wavesurfer.value.load(url)
}

async function tryConvertAndLoad() {
  try {
    converting.value = true
    loading.value = true
    errorMessage.value = ''

    console.log('📤 上傳音檔至後端進行格式轉換...')

    const formData = new FormData()
    formData.append('audio_file', currentAudioFile.value)

    const response = await fetch('/api/audio/convert-to-web-format', {
      method: 'POST',
      body: formData
    })

    if (!response.ok) {
      throw new Error(`轉換失敗: ${response.statusText}`)
    }

    const result = await response.json()
    console.log('✅ 格式轉換成功，正在載入轉換後的音檔...')

    // 下載轉換後的音檔
    const convertedAudioUrl = `/api/audio/download/${result.clip_id}`
    const audioResponse = await fetch(convertedAudioUrl)
    const audioBlob = await audioResponse.blob()
    const audioUrl = URL.createObjectURL(audioBlob)

    // 儲存到快取
    const cacheKey = `${currentAudioFile.value.name}-${currentAudioFile.value.size}-${currentAudioFile.value.lastModified}`
    convertedFilesCache.set(cacheKey, audioUrl)
    console.log(`💾 已快取轉換後的音檔: ${currentAudioFile.value.name}`)

    // 載入轉換後的音檔
    wavesurfer.value.load(audioUrl)

    // 顯示成功訊息
    console.log(`✅ 已自動轉換為 MP3 格式並載入 (${result.duration.toFixed(2)}秒)`)

  } catch (error) {
    converting.value = false
    loading.value = false
    console.error('❌ 自動轉換失敗:', error)
    errorMessage.value = `❌ 無法載入此音檔\n\n瀏覽器不支援此格式，且自動轉換失敗。\n\n錯誤：${error.message}\n\n建議：\n• 手動將檔案轉換為 MP3 或 WAV 格式\n• 檢查檔案是否完整且未損壞`
  }
}

function playPause() {
  wavesurfer.value.playPause()
}

function stop() {
  wavesurfer.value.stop()
  isPlaying.value = false
}

function handleZoom() {
  wavesurfer.value.zoom(Number(zoom.value))
}

function addRegion() {
  console.log('➕ addRegion called')
  const duration = wavesurfer.value.getDuration()
  const currentTime = wavesurfer.value.getCurrentTime()

  // 創建 5 秒區段（或到結尾）
  const start = currentTime
  const end = Math.min(currentTime + 5, duration)

  console.log('➕ Creating region:', { start, end })

  // 從 CSS 變數取得區段顏色
  const styles = getComputedStyle(document.documentElement)
  const colors = [
    styles.getPropertyValue('--editor-region-1').trim() || 'rgba(221, 132, 72, 0.3)',
    styles.getPropertyValue('--editor-region-2').trim() || 'rgba(255, 107, 53, 0.3)',
    styles.getPropertyValue('--editor-region-3').trim() || 'rgba(0, 184, 148, 0.3)',
    styles.getPropertyValue('--editor-region-4').trim() || 'rgba(156, 39, 176, 0.3)',
    styles.getPropertyValue('--editor-region-5').trim() || 'rgba(33, 150, 243, 0.3)'
  ]
  const color = colors[Math.floor(Math.random() * colors.length)]

  regionsPlugin.value.addRegion({
    start,
    end,
    color,
    drag: true,
    resize: true
  })

  console.log('➕ addRegion returned')
}

function handleRegionCreated(region) {
  console.log('🎨 handleRegionCreated triggered for:', region?.id)
  updateRegions()
}

function handleRegionUpdated(region) {
  console.log('✏️ handleRegionUpdated triggered for:', region?.id)
  updateRegions()
}

function handleRegionRemoved(region) {
  console.log('🔔 handleRegionRemoved triggered for:', region?.id)
  updateRegions()
  console.log('🔔 regions updated:', regions.value)
}

function updateRegions() {
  console.log('🔄 updateRegions called')
  const allRegions = regionsPlugin.value.getRegions()
  console.log('🔄 All regions from plugin:', allRegions.length, allRegions.map(r => r.id))
  console.log('🔄 Deleted region IDs:', Array.from(deletedRegionIds.value))

  // 過濾掉已刪除的區段
  regions.value = allRegions
    .filter(r => !deletedRegionIds.value.has(r.id))
    .map(r => ({
      id: r.id,
      start: r.start,
      end: r.end,
      duration: r.end - r.start
    }))

  console.log('🔄 regions.value updated to:', regions.value.length, regions.value.map(r => r.id))
  emit('regions-updated', regions.value)
  console.log('🔄 regions-updated event emitted')
}

function deleteRegion(regionId) {
  console.log('🌊 WaveformViewer: deleteRegion called with id:', regionId)

  if (!regionsPlugin.value) {
    console.error('❌ regionsPlugin is null!')
    return
  }

  const allRegions = regionsPlugin.value.getRegions()
  console.log('🌊 All regions before delete:', allRegions.map(r => ({ id: r.id, start: r.start, end: r.end })))

  const region = allRegions.find(r => r.id === regionId)
  console.log('🌊 Found region:', region)

  if (region) {
    // 儲存刪除區段的位置資訊用於顯示遮罩
    deletedRegionsData.value.push({
      id: region.id,
      start: region.start,
      end: region.end
    })

    // 添加到已刪除列表
    deletedRegionIds.value.add(regionId)
    console.log('🌊 Added to deleted list:', regionId)

    // 將區段改為灰色並禁用互動（從 CSS 變數取得顏色）
    try {
      const styles = getComputedStyle(document.documentElement)
      const deletedColor = styles.getPropertyValue('--editor-region-deleted').trim() || 'rgba(100, 100, 100, 0.3)'
      region.setOptions({
        color: deletedColor,
        drag: false,
        resize: false
      })
      console.log('✅ Region styled as deleted')
    } catch (e) {
      console.error('❌ Failed to update region style:', e)
    }

    // 立即更新狀態
    updateRegions()
  } else {
    console.error('❌ Region not found!')
  }
}

function getDeletedRegionStyle(region) {
  if (!wavesurfer.value) return {}

  const duration = wavesurfer.value.getDuration()
  if (!duration) return {}

  // WaveSurfer uses minPxPerSec * zoom for actual pixel density
  const minPxPerSec = 50 // 從 initWavesurfer 中定義的值
  const pixelsPerSecond = minPxPerSec * zoom.value

  const left = region.start * pixelsPerSecond
  const width = (region.end - region.start) * pixelsPerSecond

  return {
    left: `${left}px`,
    width: `${width}px`
  }
}

function checkAndSkipDeletedRegions(currentTime) {
  if (!isPlaying.value || deletedRegionsData.value.length === 0) {
    return
  }

  // 檢查當前時間是否在任何已刪除的區段中
  for (const deletedRegion of deletedRegionsData.value) {
    if (currentTime >= deletedRegion.start && currentTime < deletedRegion.end) {
      // 跳到該刪除區段的結束時間
      console.log(`⏭️ 跳過已刪除區段: ${deletedRegion.start.toFixed(2)}s - ${deletedRegion.end.toFixed(2)}s`)
      wavesurfer.value.setTime(deletedRegion.end)
      break
    }
  }
}

function playRegion(regionData) {
  wavesurfer.value.setTime(regionData.start)
  wavesurfer.value.play()

  // 在區段結束時停止
  const stopAt = regionData.end
  const checkTime = setInterval(() => {
    if (wavesurfer.value.getCurrentTime() >= stopAt) {
      wavesurfer.value.pause()
      clearInterval(checkTime)
    }
  }, 100)
}

// 獲取已刪除區段的資料（供父組件使用）
function getDeletedRegions() {
  return [...deletedRegionsData.value]
}

// 清除所有已刪除的區段記錄
function clearDeletedRegions() {
  deletedRegionsData.value = []
  deletedRegionIds.value.clear()
}

// 暴露方法給父組件
defineExpose({
  addRegion,
  deleteRegion,
  playRegion,
  getDeletedRegions,
  clearDeletedRegions
})
</script>

<style scoped>
.waveform-wrapper {
  padding: 24px;
  background: var(--editor-bg-gradient);
  position: relative;
}

.waveform-container-inner {
  width: 100%;
  overflow-x: auto;
  overflow-y: hidden;
  margin-bottom: 20px;
  position: relative;
  min-height: 128px;
}

.waveform {
  width: 100%;
  min-height: 128px;
  overflow-x: auto;  /* 允許水平滾動 */
  overflow-y: hidden;
  position: relative;
}

/* 刪除區段標記 */
.deleted-markers {
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  height: 128px;
  pointer-events: none;
  z-index: 5;
}

.deleted-marker {
  position: absolute;
  top: 0;
  height: 100%;
  display: flex;
}

.marker-line {
  width: 2px;
  height: 100%;
  background: var(--editor-marker-color);
  position: relative;
  z-index: 2;
}

.marker-line-start {
  box-shadow: 2px 0 8px rgba(var(--color-orange-rgb), 0.5);
}

.marker-line-end {
  box-shadow: -2px 0 8px rgba(var(--color-orange-rgb), 0.5);
}

.marker-fill {
  flex: 1;
  background: var(--editor-marker-fill);
  border-top: 1px dashed rgba(var(--color-orange-rgb), 0.3);
  border-bottom: 1px dashed rgba(var(--color-orange-rgb), 0.3);
}

/* 美化滾動條 */
.waveform::-webkit-scrollbar {
  height: 12px;
}

.waveform::-webkit-scrollbar-track {
  background: rgba(255, 255, 255, 0.05);
  border-radius: 6px;
}

.waveform::-webkit-scrollbar-thumb {
  background: rgba(var(--color-primary-rgb), 0.5);
  border-radius: 6px;
  transition: background 0.3s ease;
}

.waveform::-webkit-scrollbar-thumb:hover {
  background: rgba(var(--color-primary-rgb), 0.8);
}

.waveform-hint {
  margin-top: 12px;
  padding: 10px 16px;
  background: rgba(var(--color-primary-rgb), 0.1);
  border: 1px solid rgba(var(--color-primary-rgb), 0.3);
  border-radius: 6px;
  color: var(--color-gray-200);
  font-size: 0.85rem;
  text-align: center;
  line-height: 1.5;
}

.waveform-hint strong {
  color: var(--color-primary);
  font-weight: 600;
}

.waveform-controls {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}

.control-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 10px 16px;
  border: 1px solid rgba(255, 255, 255, 0.2);
  border-radius: 6px;
  background: rgba(255, 255, 255, 0.05);
  color: var(--color-gray-200);
  font-size: 0.95rem;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.3s ease;
}

.control-btn:hover {
  background: rgba(255, 255, 255, 0.1);
  color: var(--color-white);
  border-color: rgba(255, 255, 255, 0.3);
}

.control-btn.active {
  background: rgba(var(--color-orange-rgb), 0.2);
  color: var(--color-orange);
  border-color: rgba(var(--color-orange-rgb), 0.5);
}

.control-btn-primary {
  background: linear-gradient(135deg, rgba(var(--color-orange-rgb), 0.2) 0%, rgba(var(--color-primary-rgb), 0.2) 100%);
  color: var(--color-primary);
  border-color: rgba(var(--color-primary-rgb), 0.5);
}

.control-btn-primary:hover {
  background: linear-gradient(135deg, rgba(var(--color-orange-rgb), 0.3) 0%, rgba(var(--color-primary-rgb), 0.3) 100%);
  color: var(--color-orange);
}

.zoom-control {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-left: auto;
}

.zoom-control label {
  color: var(--color-gray-200);
  font-size: 0.9rem;
}

.zoom-slider {
  width: 150px;
  height: 4px;
  border-radius: 2px;
  background: rgba(var(--color-white), 0.1);
  outline: none;
  cursor: pointer;
}

.zoom-slider::-webkit-slider-thumb {
  appearance: none;
  width: 14px;
  height: 14px;
  border-radius: 50%;
  background: var(--color-primary);
  cursor: pointer;
}

.zoom-slider::-moz-range-thumb {
  width: 14px;
  height: 14px;
  border-radius: 50%;
  background: var(--color-primary);
  cursor: pointer;
  border: none;
}

.zoom-value {
  color: var(--color-primary);
  font-weight: 600;
  font-size: 0.9rem;
  min-width: 40px;
}

.loading-overlay {
  position: absolute;
  inset: 0;
  background: var(--editor-bg-dark);
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  border-radius: 8px;
  z-index: 10;
}

.spinner {
  width: 40px;
  height: 40px;
  border: 3px solid rgba(255, 255, 255, 0.1);
  border-top-color: var(--color-primary);
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
  margin-bottom: 12px;
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}

.loading-overlay p {
  color: var(--color-gray-200);
  font-size: 0.95rem;
  margin: 4px 0;
}

.loading-overlay .loading-hint {
  color: var(--color-gray-300);
  font-size: 0.85rem;
  max-width: 400px;
  text-align: center;
  line-height: 1.5;
}

.error-overlay {
  position: absolute;
  inset: 0;
  background: var(--editor-bg-dark);
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  border-radius: 8px;
  z-index: 15;
  padding: 24px;
}

.error-icon {
  font-size: 3rem;
  margin-bottom: 16px;
}

.error-message {
  color: var(--color-danger-light);
  font-size: 0.9rem;
  background: rgba(var(--color-danger-rgb), 0.1);
  border: 1px solid rgba(var(--color-danger-rgb), 0.3);
  border-radius: 6px;
  padding: 16px;
  margin-bottom: 20px;
  max-width: 500px;
  text-align: left;
  white-space: pre-wrap;
  font-family: inherit;
  line-height: 1.6;
}

.btn-dismiss {
  padding: 10px 24px;
  background: rgba(255, 255, 255, 0.1);
  color: var(--color-white);
  border: 1px solid rgba(255, 255, 255, 0.2);
  border-radius: 6px;
  font-size: 0.95rem;
  cursor: pointer;
  transition: all 0.3s ease;
}

.btn-dismiss:hover {
  background: rgba(255, 255, 255, 0.15);
  border-color: rgba(255, 255, 255, 0.3);
}

@media (max-width: 768px) {
  .zoom-control {
    width: 100%;
    margin-left: 0;
  }

  .zoom-slider {
    flex: 1;
  }
}
</style>
