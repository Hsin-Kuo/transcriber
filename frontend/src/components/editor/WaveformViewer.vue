<template>
  <div class="waveform-container electric-card">
    <div class="electric-inner">
      <div class="electric-border-outer">
        <div class="electric-main waveform-wrapper">
          <div ref="waveformEl" class="waveform"></div>

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
import { ref, onMounted, watch, onBeforeUnmount } from 'vue'
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

onMounted(() => {
  initWavesurfer()
})

onBeforeUnmount(() => {
  wavesurfer.value?.destroy()
})

watch(() => props.audioFile, (newFile) => {
  if (newFile) {
    loadAudio(newFile)
  }
})

function initWavesurfer() {
  // 創建 regions plugin
  regionsPlugin.value = RegionsPlugin.create()

  // 創建 WaveSurfer 實例 - 優化大檔案效能
  wavesurfer.value = WaveSurfer.create({
    container: waveformEl.value,
    waveColor: '#DD8448',
    progressColor: '#FF6B35',
    cursorColor: '#FFFFFF',
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
  const duration = wavesurfer.value.getDuration()
  const currentTime = wavesurfer.value.getCurrentTime()

  // 創建 5 秒區段（或到結尾）
  const start = currentTime
  const end = Math.min(currentTime + 5, duration)

  // 生成隨機顏色
  const colors = [
    'rgba(221, 132, 72, 0.3)',
    'rgba(255, 107, 53, 0.3)',
    'rgba(0, 184, 148, 0.3)',
    'rgba(156, 39, 176, 0.3)',
    'rgba(33, 150, 243, 0.3)'
  ]
  const color = colors[Math.floor(Math.random() * colors.length)]

  regionsPlugin.value.addRegion({
    start,
    end,
    color,
    drag: true,
    resize: true
  })
}

function handleRegionCreated(region) {
  updateRegions()
}

function handleRegionUpdated(region) {
  updateRegions()
}

function handleRegionRemoved(region) {
  updateRegions()
}

function updateRegions() {
  const allRegions = regionsPlugin.value.getRegions()
  regions.value = allRegions.map(r => ({
    id: r.id,
    start: r.start,
    end: r.end,
    duration: r.end - r.start
  }))
  emit('regions-updated', regions.value)
}

function deleteRegion(regionId) {
  const allRegions = regionsPlugin.value.getRegions()
  const region = allRegions.find(r => r.id === regionId)
  if (region) {
    region.remove()
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

// 暴露方法給父組件
defineExpose({
  addRegion,
  deleteRegion,
  playRegion
})
</script>

<style scoped>
.waveform-wrapper {
  padding: 24px;
  background: linear-gradient(135deg, rgba(28, 28, 28, 0.95) 0%, rgba(20, 20, 20, 0.95) 100%);
  position: relative;
}

.waveform {
  width: 100%;
  margin-bottom: 20px;
  min-height: 128px;
  overflow-x: auto;  /* 允許水平滾動 */
  overflow-y: hidden;
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
  background: rgba(221, 132, 72, 0.5);
  border-radius: 6px;
  transition: background 0.3s ease;
}

.waveform::-webkit-scrollbar-thumb:hover {
  background: rgba(221, 132, 72, 0.8);
}

.waveform-hint {
  margin-top: 12px;
  padding: 10px 16px;
  background: rgba(221, 132, 72, 0.1);
  border: 1px solid rgba(221, 132, 72, 0.3);
  border-radius: 6px;
  color: #999;
  font-size: 0.85rem;
  text-align: center;
  line-height: 1.5;
}

.waveform-hint strong {
  color: #DD8448;
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
  color: #aaa;
  font-size: 0.95rem;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.3s ease;
}

.control-btn:hover {
  background: rgba(255, 255, 255, 0.1);
  color: #fff;
  border-color: rgba(255, 255, 255, 0.3);
}

.control-btn.active {
  background: rgba(255, 107, 53, 0.2);
  color: #FF6B35;
  border-color: rgba(255, 107, 53, 0.5);
}

.control-btn-primary {
  background: linear-gradient(135deg, rgba(255, 107, 53, 0.2) 0%, rgba(221, 132, 72, 0.2) 100%);
  color: #DD8448;
  border-color: rgba(221, 132, 72, 0.5);
}

.control-btn-primary:hover {
  background: linear-gradient(135deg, rgba(255, 107, 53, 0.3) 0%, rgba(221, 132, 72, 0.3) 100%);
  color: #FF6B35;
}

.zoom-control {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-left: auto;
}

.zoom-control label {
  color: #aaa;
  font-size: 0.9rem;
}

.zoom-slider {
  width: 150px;
  height: 4px;
  border-radius: 2px;
  background: rgba(255, 255, 255, 0.1);
  outline: none;
  cursor: pointer;
}

.zoom-slider::-webkit-slider-thumb {
  appearance: none;
  width: 14px;
  height: 14px;
  border-radius: 50%;
  background: #DD8448;
  cursor: pointer;
}

.zoom-slider::-moz-range-thumb {
  width: 14px;
  height: 14px;
  border-radius: 50%;
  background: #DD8448;
  cursor: pointer;
  border: none;
}

.zoom-value {
  color: #DD8448;
  font-weight: 600;
  font-size: 0.9rem;
  min-width: 40px;
}

.loading-overlay {
  position: absolute;
  inset: 0;
  background: rgba(20, 20, 20, 0.9);
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
  border-top-color: #DD8448;
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
  color: #aaa;
  font-size: 0.95rem;
  margin: 4px 0;
}

.loading-overlay .loading-hint {
  color: #888;
  font-size: 0.85rem;
  max-width: 400px;
  text-align: center;
  line-height: 1.5;
}

.error-overlay {
  position: absolute;
  inset: 0;
  background: rgba(20, 20, 20, 0.95);
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
  color: #ff6b6b;
  font-size: 0.9rem;
  background: rgba(255, 107, 107, 0.1);
  border: 1px solid rgba(255, 107, 107, 0.3);
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
  color: #fff;
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
