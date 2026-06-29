import { ref, computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { API_BASE, TokenManager } from '../../utils/api'
import { NEW_ENDPOINTS } from '../../api/endpoints'
import { DEMO_ID, getDemoAudioUrl } from '../../utils/tourFixtures'

export function useAudioPlayer() {
  const { t } = useI18n()

  const audioElement = ref(null)

  // Playback state
  const isPlaying = ref(false)
  const currentTime = ref(0)
  const duration = ref(0)
  const progressPercent = ref(0)

  // Volume & speed
  const volume = ref(1)
  const isMuted = ref(false)
  const playbackRate = ref(1)

  // Audio URL & error
  const audioUrl = ref('')
  const audioError = ref(null)

  // Token refresh internals
  let currentTaskId = null
  let tokenRefreshTimer = null
  let retryCount = 0
  const MAX_RETRY_COUNT = 2
  const TOKEN_REFRESH_INTERVAL = 10 * 60 * 1000

  // --- Derived state for UI ---

  const displayTime = computed(() => currentTime.value)

  // --- Audio URL management ---

  function getAudioUrl(taskId) {
    // 新手導覽 demo：回傳內建靜音 data URI，讓播放器有合法來源、不打 API、不報錯
    if (taskId === DEMO_ID) return getDemoAudioUrl()

    const token = TokenManager.getAccessToken()
    if (!token) {
      console.warn(t('audioPlayer.cannotGetAccessToken'))
      return ''
    }
    return `${API_BASE}${NEW_ENDPOINTS.transcriptions.audio(taskId)}?token=${encodeURIComponent(token)}&t=${Date.now()}`
  }

  function initAudioUrl(taskId) {
    if (!taskId) return
    currentTaskId = taskId
    retryCount = 0
    audioUrl.value = getAudioUrl(taskId)
    audioError.value = null
    startTokenRefreshTimer()
  }

  function startTokenRefreshTimer() {
    stopTokenRefreshTimer()
    tokenRefreshTimer = setInterval(async () => {
      if (currentTaskId) {
        await silentRefreshAudioUrl()
      }
    }, TOKEN_REFRESH_INTERVAL)
  }

  function stopTokenRefreshTimer() {
    if (tokenRefreshTimer) {
      clearInterval(tokenRefreshTimer)
      tokenRefreshTimer = null
    }
  }

  async function silentRefreshAudioUrl() {
    if (!currentTaskId) return
    try {
      const response = await fetch(`${API_BASE}/auth/refresh`, {
        method: 'POST',
        credentials: 'include',
      })
      if (response.ok) {
        const data = await response.json()
        TokenManager.setAccessToken(data.access_token)
        if (!isPlaying.value) {
          audioUrl.value = getAudioUrl(currentTaskId)
        }
      }
    } catch (error) {
      console.warn('靜默刷新 token 失敗:', error)
    }
  }

  async function reloadAudio(taskId) {
    if (!taskId) return
    currentTaskId = taskId

    const currentPosition = audioElement.value?.currentTime || 0
    const wasPlaying = isPlaying.value

    try {
      try {
        const response = await fetch(`${API_BASE}/auth/refresh`, {
          method: 'POST',
          credentials: 'include',
        })
        if (response.ok) {
          const data = await response.json()
          TokenManager.setAccessToken(data.access_token)
        }
      } catch (refreshError) {
        console.warn(t('audioPlayer.tokenRefreshFailed'), refreshError)
      }

      const newUrl = getAudioUrl(taskId)
      if (!newUrl) {
        audioError.value = t('audioPlayer.cannotGetAuthToken')
        return
      }

      audioUrl.value = newUrl
      audioError.value = null

      if (audioElement.value) {
        audioElement.value.load()
        audioElement.value.addEventListener('loadedmetadata', () => {
          retryCount = 0
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

  // --- Event handlers (called by AudioPlayer.vue) ---

  function handleAudioLoaded() {
    audioError.value = null
    retryCount = 0
  }

  async function handleAudioError(event) {
    const audio = event.target
    if (!audio.error) return
    if (!audio.src || audio.src === window.location.href || audio.src === '') return

    if (audio.error.code === audio.error.MEDIA_ERR_SRC_NOT_SUPPORTED) {
      try {
        const response = await fetch(audio.src)
        const contentType = response.headers.get('content-type')

        if (!response.ok) {
          if (response.status === 401 || response.status === 403) {
            if (retryCount < MAX_RETRY_COUNT && currentTaskId) {
              retryCount++
              await reloadAudio(currentTaskId)
              return
            }
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
        const token = TokenManager.getAccessToken()
        if (!token) {
          if (retryCount < MAX_RETRY_COUNT && currentTaskId) {
            retryCount++
            await reloadAudio(currentTaskId)
            return
          }
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

  function updateProgress() {
    if (!audioElement.value) return
    currentTime.value = audioElement.value.currentTime
    if (duration.value > 0) {
      progressPercent.value = (currentTime.value / duration.value) * 100
    }
  }

  function updateDuration() {
    if (!audioElement.value) return
    const newDuration = audioElement.value.duration
    if (newDuration && isFinite(newDuration) && newDuration > 0) {
      duration.value = newDuration
    }
  }

  function updateVolume() {
    if (!audioElement.value) return
    volume.value = audioElement.value.volume
    isMuted.value = audioElement.value.muted
  }

  function updatePlaybackRate() {
    if (!audioElement.value) return
    playbackRate.value = audioElement.value.playbackRate
  }

  // --- Playback controls ---

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

  function skipBackward(seconds = 10) {
    if (audioElement.value) {
      audioElement.value.currentTime = Math.max(0, audioElement.value.currentTime - seconds)
    }
  }

  function skipForward(seconds = 10) {
    if (audioElement.value) {
      audioElement.value.currentTime = Math.min(
        audioElement.value.duration || 0,
        audioElement.value.currentTime + seconds
      )
    }
  }

  function seekToTime(time) {
    if (audioElement.value) {
      audioElement.value.currentTime = time
      audioElement.value.play().catch(err => console.log(t('audioPlayer.playbackFailed'), err))
    }
  }

  function setVolume(event) {
    if (!audioElement.value) return
    const newVolume = parseInt(event.target.value) / 100
    audioElement.value.volume = newVolume
    if (newVolume > 0 && isMuted.value) {
      audioElement.value.muted = false
    }
  }

  function toggleMute() {
    if (!audioElement.value) return
    audioElement.value.muted = !audioElement.value.muted
  }

  function setPlaybackRate(rate) {
    if (!audioElement.value) return
    audioElement.value.playbackRate = rate
  }

  function cleanup() {
    stopTokenRefreshTimer()
    currentTaskId = null
    retryCount = 0
  }

  return {
    // Audio element ref (AudioPlayer.vue binds this)
    audioElement,

    // Reactive state (read by parent & mobile UI)
    isPlaying,
    currentTime,
    duration,
    progressPercent,
    displayTime,
    volume,
    isMuted,
    playbackRate,
    audioUrl,
    audioError,

    // URL lifecycle
    getAudioUrl,
    initAudioUrl,
    reloadAudio,
    cleanup,

    // Event handlers (AudioPlayer.vue calls these on <audio> events)
    handleAudioLoaded,
    handleAudioError,
    updateProgress,
    updateDuration,
    updateVolume,
    updatePlaybackRate,

    // Playback controls (used by parent, keyboard shortcuts, mobile UI)
    togglePlayPause,
    skipBackward,
    skipForward,
    seekToTime,
    setVolume,
    toggleMute,
    setPlaybackRate,
  }
}
