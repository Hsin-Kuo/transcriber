import { ref, computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { API_BASE, TokenManager } from '../../utils/api'
import { NEW_ENDPOINTS } from '../../api/endpoints'

/**
 * 音訊播放器管理 Composable
 *
 * 職責：
 * - 管理音訊播放狀態（播放、暫停、時間、音量、速度）
 * - 處理圓形進度條拖拽
 * - 提供播放控制方法（播放/暫停、快進/快退、跳轉）
 * - 處理音訊載入錯誤
 */
export function useAudioPlayer() {
  // i18n
  const { t } = useI18n()

  // 音訊元素引用
  const audioElement = ref(null)

  // 播放狀態
  const isPlaying = ref(false)
  const currentTime = ref(0)
  const duration = ref(0)
  const progressPercent = ref(0)

  // 音量和速度
  const volume = ref(1)
  const isMuted = ref(false)
  const playbackRate = ref(1)

  // 圓弧進度條拖拽狀態
  const isDraggingArc = ref(false)
  const draggingPercent = ref(0)
  let rafId = null

  // 音訊 URL 和錯誤
  const audioUrl = ref('')
  const audioError = ref(null)

  // ========== 計算屬性 ==========

  /**
   * 圓弧路徑（1/3 圓，120度）
   */
  const arcPath = computed(() => {
    const centerX = 100
    const centerY = 100
    const radius = 90
    const startAngle = 210 * (Math.PI / 180)
    const endAngle = 330 * (Math.PI / 180)

    const startX = centerX + radius * Math.cos(startAngle)
    const startY = centerY + radius * Math.sin(startAngle)
    const endX = centerX + radius * Math.cos(endAngle)
    const endY = centerY + radius * Math.sin(endAngle)

    return `M ${startX} ${startY} A ${radius} ${radius} 0 0 1 ${endX} ${endY}`
  })

  /**
   * 圓弧長度
   */
  const arcLength = computed(() => {
    const radius = 90
    return (2 * Math.PI * radius) / 3
  })

  /**
   * 拇指（進度點）位置
   */
  const thumbPosition = computed(() => {
    const centerX = 100
    const centerY = 100
    const radius = 90
    const startAngle = 210 * (Math.PI / 180)
    const totalAngle = 120 * (Math.PI / 180)
    const percent = isDraggingArc.value ? draggingPercent.value : progressPercent.value
    const currentAngle = startAngle + (totalAngle * percent / 100)

    return {
      x: centerX + radius * Math.cos(currentAngle),
      y: centerY + radius * Math.sin(currentAngle)
    }
  })

  /**
   * 顯示的進度百分比（拖拽時使用拖拽進度）
   */
  const displayProgress = computed(() => {
    return isDraggingArc.value ? draggingPercent.value : progressPercent.value
  })

  /**
   * 顯示的時間（拖拽時即時計算）
   */
  const displayTime = computed(() => {
    if (isDraggingArc.value) {
      return (draggingPercent.value / 100) * duration.value
    }
    return currentTime.value
  })

  // ========== 音訊 URL 管理 ==========

  /**
   * 獲取音訊 URL（帶 token）
   */
  function getAudioUrl(taskId) {
    const token = TokenManager.getAccessToken()
    if (!token) {
      console.warn(t('audioPlayer.cannotGetAccessToken'))
      return ''
    }
    return `${API_BASE}${NEW_ENDPOINTS.transcriptions.audio(taskId)}?token=${encodeURIComponent(token)}&t=${Date.now()}`
  }

  /**
   * 初始化音訊 URL
   */
  function initAudioUrl(taskId) {
    if (!taskId) return
    audioUrl.value = getAudioUrl(taskId)
    audioError.value = null
  }

  /**
   * 重新載入音檔
   */
  async function reloadAudio(taskId) {
    if (!taskId) return

    // 保存當前播放位置
    const currentPosition = audioElement.value?.currentTime || 0
    const wasPlaying = isPlaying.value

    try {
      // 先嘗試刷新 token（透過發送一個測試請求觸發 token 刷新機制）
      const refreshToken = TokenManager.getRefreshToken()
      if (refreshToken) {
        try {
          // 使用 refresh token 獲取新的 access token
          const response = await fetch(`${API_BASE}/auth/refresh`, {
            method: 'POST',
            headers: {
              'Content-Type': 'application/json'
            },
            body: JSON.stringify({ refresh_token: refreshToken })
          })

          if (response.ok) {
            const data = await response.json()
            TokenManager.setTokens(data.access_token, data.refresh_token)
            console.log(t('audioPlayer.tokenRefreshed'))
          }
        } catch (refreshError) {
          console.warn(t('audioPlayer.tokenRefreshFailed'), refreshError)
        }
      }

      // 生成新的音檔 URL
      const newUrl = getAudioUrl(taskId)
      if (!newUrl) {
        audioError.value = t('audioPlayer.cannotGetAuthToken')
        return
      }

      // 更新音檔 URL
      audioUrl.value = newUrl
      audioError.value = null

      // 恢復播放位置和狀態
      if (audioElement.value) {
        audioElement.value.load()
        audioElement.value.addEventListener('loadedmetadata', () => {
          if (audioElement.value && currentPosition > 0) {
            audioElement.value.currentTime = currentPosition
          }
          if (wasPlaying) {
            audioElement.value?.play().catch(err => console.log(t('audioPlayer.resumePlaybackFailed'), err))
          }
        }, { once: true })
      }
    } catch (error) {
      console.error(t('audioPlayer.reloadFailed'), error)
      audioError.value = t('audioPlayer.reloadFailed')
    }
  }

  // ========== 事件處理 ==========

  /**
   * 音訊載入完成
   */
  function handleAudioLoaded() {
    audioError.value = null
  }

  /**
   * 音訊載入錯誤
   */
  async function handleAudioError(event) {
    const audio = event.target
    if (!audio.error) return

    // 忽略空 src 的錯誤（初始化時的正常現象）
    if (!audio.src || audio.src === window.location.href || audio.src === '') {
      return
    }

    console.error('音檔載入錯誤:', {
      code: audio.error.code,
      message: audio.error.message,
      src: audio.src
    })

    // 診斷錯誤原因
    if (audio.error.code === audio.error.MEDIA_ERR_SRC_NOT_SUPPORTED) {
      try {
        const response = await fetch(audio.src)
        const contentType = response.headers.get('content-type')

        console.log('後端響應診斷:', {
          status: response.status,
          statusText: response.statusText,
          contentType: contentType
        })

        if (!response.ok) {
          if (response.status === 401 || response.status === 403) {
            audioError.value = t('audioPlayer.authExpired')
          } else if (response.status === 404) {
            audioError.value = t('audioPlayer.audioNotFound')
          } else {
            audioError.value = t('audioPlayer.backendError', { status: response.status, statusText: response.statusText })
          }
        } else if (contentType && !contentType.includes('audio')) {
          audioError.value = t('audioPlayer.invalidContentType', { contentType })
        } else {
          audioError.value = t('audioPlayer.audioFormatNotSupported')
        }
      } catch (fetchError) {
        console.error('診斷錯誤時發生問題:', fetchError)
        const token = TokenManager.getAccessToken()
        if (!token) {
          audioError.value = t('audioPlayer.authTokenExpired')
        } else {
          audioError.value = t('audioPlayer.cannotAccessAudio')
        }
      }
    } else {
      switch (audio.error.code) {
        case audio.error.MEDIA_ERR_NETWORK:
          audioError.value = t('audioPlayer.networkError')
          break
        case audio.error.MEDIA_ERR_DECODE:
          audioError.value = t('audioPlayer.audioDecodeError')
          break
        default:
          audioError.value = t('audioPlayer.audioLoadFailed')
      }
    }
  }

  /**
   * 更新播放進度
   */
  function updateProgress() {
    if (!audioElement.value) return
    currentTime.value = audioElement.value.currentTime
    if (duration.value > 0) {
      progressPercent.value = (currentTime.value / duration.value) * 100
    }
  }

  /**
   * 更新音訊時長
   */
  function updateDuration() {
    if (!audioElement.value) return

    const newDuration = audioElement.value.duration

    // 只在 duration 是有效數字時更新
    // 避免 NaN、Infinity 或 0 覆蓋已有的正確值
    if (newDuration && isFinite(newDuration) && newDuration > 0) {
      duration.value = newDuration
    }
  }

  /**
   * 更新音量
   */
  function updateVolume() {
    if (!audioElement.value) return
    volume.value = audioElement.value.volume
    isMuted.value = audioElement.value.muted
  }

  /**
   * 更新播放速度
   */
  function updatePlaybackRate() {
    if (!audioElement.value) return
    playbackRate.value = audioElement.value.playbackRate
  }

  // ========== 播放控制 ==========

  /**
   * 切換播放/暫停
   */
  function togglePlayPause() {
    if (!audioElement.value) return
    if (audioElement.value.paused) {
      audioElement.value.play().catch(err => {
        console.error(t('audioPlayer.playbackFailed'), err)
        audioError.value = t('audioPlayer.playbackFailed')
      })
    } else {
      audioElement.value.pause()
    }
  }

  /**
   * 快退指定秒數（預設 10 秒）
   * @param {number} seconds - 要快退的秒數，預設為 10
   */
  function skipBackward(seconds = 10) {
    if (audioElement.value) {
      audioElement.value.currentTime = Math.max(0, audioElement.value.currentTime - seconds)
    }
  }

  /**
   * 快進指定秒數（預設 10 秒）
   * @param {number} seconds - 要快進的秒數，預設為 10
   */
  function skipForward(seconds = 10) {
    if (audioElement.value) {
      audioElement.value.currentTime = Math.min(
        audioElement.value.duration || 0,
        audioElement.value.currentTime + seconds
      )
    }
  }

  /**
   * 跳轉到指定時間並播放
   */
  function seekToTime(time) {
    if (audioElement.value) {
      audioElement.value.currentTime = time
      audioElement.value.play().catch(err => console.log(t('audioPlayer.playbackFailed'), err))
    }
  }

  /**
   * 設定音量
   */
  function setVolume(event) {
    if (!audioElement.value) return
    const newVolume = parseInt(event.target.value) / 100
    audioElement.value.volume = newVolume
    if (newVolume > 0 && isMuted.value) {
      audioElement.value.muted = false
    }
  }

  /**
   * 切換靜音
   */
  function toggleMute() {
    if (!audioElement.value) return
    audioElement.value.muted = !audioElement.value.muted
  }

  /**
   * 設定播放速度
   */
  function setPlaybackRate(rate) {
    if (!audioElement.value) return
    audioElement.value.playbackRate = rate
  }

  // ========== 圓弧進度條拖拽 ==========

  /**
   * 計算圓弧上的進度百分比
   */
  function calculateArcProgress(event, svg) {
    if (!svg) return null

    const rect = svg.getBoundingClientRect()
    const clickX = event.clientX - rect.left
    const clickY = event.clientY - rect.top

    // 將 SVG 座標轉換為相對於圓心的座標
    const svgWidth = rect.width
    const svgHeight = rect.height
    const scaleX = 200 / svgWidth
    const scaleY = 140 / svgHeight

    const svgX = clickX * scaleX
    const svgY = clickY * scaleY

    const centerX = 100
    const centerY = 100

    // 計算角度
    const dx = svgX - centerX
    const dy = svgY - centerY
    let angle = Math.atan2(dy, dx) * (180 / Math.PI)

    // 標準化到 0-360 範圍
    if (angle < 0) angle += 360

    // 檢查是否在 210-330 度範圍內
    let normalizedAngle = angle
    if (angle >= 0 && angle < 210) {
      if (angle < 90) {
        normalizedAngle = 330
      } else {
        normalizedAngle = 210
      }
    } else if (angle > 330) {
      normalizedAngle = 330
    }

    // 計算進度百分比
    let percent = ((normalizedAngle - 210) / 120) * 100
    percent = Math.max(0, Math.min(100, percent))

    return percent
  }

  /**
   * 開始拖拽圓弧
   */
  function startDragArc(event) {
    if (!audioElement.value || duration.value === 0) return
    isDraggingArc.value = true

    const percent = calculateArcProgress(event, event.currentTarget)
    if (percent !== null) {
      draggingPercent.value = percent
    }
  }

  /**
   * 拖拽圓弧中
   */
  function dragArc(event) {
    if (!isDraggingArc.value || !audioElement.value || duration.value === 0) return

    const percent = calculateArcProgress(event, event.currentTarget)
    if (percent === null) return

    // 取消之前的 RAF
    if (rafId !== null) {
      cancelAnimationFrame(rafId)
    }

    // 使用 RAF 來優化更新
    rafId = requestAnimationFrame(() => {
      draggingPercent.value = percent
    })
  }

  /**
   * 停止拖拽圓弧
   */
  function stopDragArc() {
    if (!isDraggingArc.value) return

    isDraggingArc.value = false

    // 取消任何待處理的 RAF
    if (rafId !== null) {
      cancelAnimationFrame(rafId)
      rafId = null
    }

    // 釋放時才真正 seek 到目標位置
    if (audioElement.value && duration.value > 0) {
      const newTime = (draggingPercent.value / 100) * duration.value
      audioElement.value.currentTime = newTime
    }
  }

  // ========== 工具函數 ==========

  /**
   * 格式化時間顯示
   */
  function formatTime(seconds) {
    if (!seconds || isNaN(seconds)) return '0:00'
    const hours = Math.floor(seconds / 3600)
    const mins = Math.floor((seconds % 3600) / 60)
    const secs = Math.floor(seconds % 60)
    if (hours > 0) {
      return `${hours}:${mins.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`
    }
    return `${mins}:${secs.toString().padStart(2, '0')}`
  }

  return {
    // 元素引用
    audioElement,

    // 播放狀態
    isPlaying,
    currentTime,
    duration,
    progressPercent,
    displayProgress,
    displayTime,

    // 音量和速度
    volume,
    isMuted,
    playbackRate,

    // 圓弧進度條
    arcPath,
    arcLength,
    thumbPosition,
    isDraggingArc,

    // 音訊 URL 和錯誤
    audioUrl,
    audioError,

    // URL 管理
    getAudioUrl,
    initAudioUrl,
    reloadAudio,

    // 事件處理
    handleAudioLoaded,
    handleAudioError,
    updateProgress,
    updateDuration,
    updateVolume,
    updatePlaybackRate,

    // 播放控制
    togglePlayPause,
    skipBackward,
    skipForward,
    seekToTime,
    setVolume,
    toggleMute,
    setPlaybackRate,

    // 圓弧拖拽
    startDragArc,
    dragArc,
    stopDragArc,

    // 工具函數
    formatTime
  }
}
