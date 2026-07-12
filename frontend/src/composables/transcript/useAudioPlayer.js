import { ref, computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { API_BASE, setAccessTokenExpiry } from '../../utils/api'
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

    // access_token 是 httpOnly cookie，<audio> 的同源請求會自動帶上，不再
    // 需要（也讀不到）把 token 塞進 URL query string；t= 純粹用來破快取。
    return `${API_BASE}${NEW_ENDPOINTS.transcriptions.audio(taskId)}?t=${Date.now()}`
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
        await silentRefreshToken()
      }
    }, TOKEN_REFRESH_INTERVAL)
  }

  function stopTokenRefreshTimer() {
    if (tokenRefreshTimer) {
      clearInterval(tokenRefreshTimer)
      tokenRefreshTimer = null
    }
  }

  async function silentRefreshToken() {
    if (!currentTaskId) return
    try {
      const response = await fetch(`${API_BASE}/auth/refresh`, {
        method: 'POST',
        credentials: 'include',
      })
      if (response.ok) {
        // 新 access_token 已由後端種進 httpOnly cookie，這裡只需要同步
        // expires_at 給 ensureFreshAccessToken（大檔上傳）共用判斷。
        // 刻意不重設 audioUrl：更換 <audio> 的 src 會讓瀏覽器重新載入並把 currentTime 歸零，
        // 暫停中的播放位置會因此遺失。src 內嵌的 token 過期改由 handleAudioError 在實際
        // 發生 401（range 請求）時走 reloadAudio（保留位置 + 還原播放狀態）自癒。
        const data = await response.json()
        setAccessTokenExpiry(data.expires_at)
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
          // 新 access_token 已由後端種進 httpOnly cookie，不需要在這裡讀寫
          const data = await response.json()
          setAccessTokenExpiry(data.expires_at)
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

    const ERR = audio.error
    const code = ERR.code

    // src 內嵌的 token 過期會以兩種 MediaError 浮現：
    //   - 初始載入失敗 → MEDIA_ERR_SRC_NOT_SUPPORTED (4)
    //   - 播放途中 range 請求 401 → MEDIA_ERR_NETWORK (2)
    // 兩者都先探測真正的 HTTP 狀態碼，確認是授權問題就走 reloadAudio
    //（reloadAudio 會保存 currentTime、刷新 token、還原播放狀態），不會把進度歸零。
    if (code === ERR.MEDIA_ERR_SRC_NOT_SUPPORTED || code === ERR.MEDIA_ERR_NETWORK) {
      try {
        // 帶 Range: bytes=0-0 只探第一個 byte，避免把整個音檔重抓一遍。
        // 後端本地 FileResponse 與 AWS S3 皆支援 Range（回 206）；授權檢查在 serve 之前，
        // token 過期仍先回 401，不受 Range 影響。Range 屬 CORS-safelisted，不觸發 preflight。
        //
        // redirect: 'manual'：AWS 模式音檔端點成功時回 302 → S3 presigned URL。我方 JWT 與
        // S3 presigned 是兩套各自過期的憑證：JWT 過期 → 我方 API 回 401（可讀）；JWT 仍有效
        // 但 S3 presigned（1 小時）過期 → 媒體層 range 打 S3 得 403，而此時打我方 API 只會拿到
        // 一張「新簽的」302。用 manual 在 302 就停手（opaqueredirect），即可判定「JWT 有效、
        // 下游 presigned 失效」並直接帶位置重載取得新連結，補上跟隨 redirect 會誤判成 OK 的缺口。
        // 本地模式無 redirect，永遠走下方 status/content-type 既有分支，行為不變。
        const response = await fetch(audio.src, {
          headers: { Range: 'bytes=0-0' },
          redirect: 'manual',
        })

        // AWS：我方端點放行（302）但媒體層的 S3 presigned 過期才失敗 → 重載取新連結
        if (response.type === 'opaqueredirect') {
          if (retryCount < MAX_RETRY_COUNT && currentTaskId) {
            retryCount++
            await reloadAudio(currentTaskId)
            return
          }
          audioError.value = t('audioPlayer.authExpired')
          return
        }

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
          } else if (code === ERR.MEDIA_ERR_NETWORK) {
            audioError.value = t('audioPlayer.networkError')
          } else {
            audioError.value = t('audioPlayer.backendError', { status: response.status, statusText: response.statusText })
          }
        } else if (code === ERR.MEDIA_ERR_NETWORK) {
          // src 可正常存取（非授權問題）→ 視為單純連線中斷
          audioError.value = t('audioPlayer.networkError')
        } else if (contentType && !contentType.includes('audio')) {
          audioError.value = t('audioPlayer.invalidContentType', { contentType })
        } else {
          audioError.value = t('audioPlayer.audioFormatNotSupported')
        }
      } catch (fetchError) {
        // access_token 是 httpOnly cookie，這裡讀不到「有沒有 token」了——
        // 不再用「有沒有 token」當判斷依據，改成：明確是網路錯誤就顯示網路
        // 錯誤，否則當成可能是認證問題，先嘗試 reloadAudio（內含 refresh）
        // 自癒，重試次數用完才顯示通用錯誤。
        if (code === ERR.MEDIA_ERR_NETWORK) {
          audioError.value = t('audioPlayer.networkError')
        } else if (retryCount < MAX_RETRY_COUNT && currentTaskId) {
          retryCount++
          await reloadAudio(currentTaskId)
        } else {
          audioError.value = t('audioPlayer.cannotAccessAudio')
        }
      }
    } else {
      switch (code) {
        case ERR.MEDIA_ERR_DECODE:
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
