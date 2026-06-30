import { watch, nextTick, onMounted, onUnmounted } from 'vue'
import { onBeforeRouteLeave } from 'vue-router'

/**
 * 頁面生命週期管理 Composable
 *
 * 職責：
 * - 載入逐字稿（含 audio URL 初始化、segment markers、字幕設定）
 * - 字幕滾動修復（MutationObserver）
 * - 滾動監聽（關閉 header 下拉選單）
 * - onMounted / onUnmounted 生命週期
 * - 路由離開守衛
 * - 編輯狀態 body class
 * - segment markers 自動重建
 * - displayMode 切換時重設滾動監聽
 */
export function usePageLifecycle({
  route,
  router,
  $t,
  textareaRef,
  headerRef,
  displayMode,
  segments,
  currentTranscript,
  subtitleSettings,
  densityThreshold,
  isEditing,
  hasUnsavedChanges,
  handleCancelEditing,
  clearHighlights,
  cleanupAudioPlayer,
  cancelPendingRequests,
  loadTranscriptData,
  getAudioUrl,
  initAudioUrl,
  generateSegmentMarkers,
  fetchTagColors,
  isMountedRef,
  scrollRestoreTimersRef,
  isInitializingRef,
}) {
  // ========== 載入逐字稿 ==========

  async function loadTranscript(taskId) {
    isInitializingRef.set(true)

    const result = await loadTranscriptData(
      taskId,
      getAudioUrl,
      null
    )

    if (result) {
      if (result.audioUrl) {
        initAudioUrl(taskId)
      }

      if (displayMode.value === 'paragraph' && segments.value && currentTranscript.value.content) {
        generateSegmentMarkers(segments.value, currentTranscript.value.content)
      }

      if (displayMode.value === 'subtitle' && subtitleSettings.value) {
        if (subtitleSettings.value.density_threshold !== undefined) {
          densityThreshold.value = subtitleSettings.value.density_threshold
        }
      }
    }

    nextTick(() => {
      isInitializingRef.set(false)
    })
  }

  // ========== 滾動管理 ==========

  function fixSubtitleScrolling() {
    const wrapper = document.querySelector('.subtitle-table-wrapper')
    if (!wrapper) return

    const handleWheel = (e) => {
      const delta = e.deltaY
      wrapper.scrollTop += delta
      e.preventDefault()
    }

    const addScrollListeners = () => {
      const editableCells = wrapper.querySelectorAll('.col-content[contenteditable="true"]')
      editableCells.forEach(cell => {
        cell.addEventListener('wheel', handleWheel, { passive: false })
      })
    }

    addScrollListeners()

    const observer = new MutationObserver(() => {
      addScrollListeners()
    })

    observer.observe(wrapper, {
      childList: true,
      subtree: true,
      attributes: true,
      attributeFilter: ['contenteditable']
    })
  }

  function handleContentAreaScroll() {
    if (headerRef.value) {
      headerRef.value.closeMoreOptions()
    }
  }

  function setupScrollListeners() {
    if (textareaRef.value) {
      textareaRef.value.addEventListener('scroll', handleContentAreaScroll)
    }

    const subtitleWrapper = document.querySelector('.subtitle-table-wrapper')
    if (subtitleWrapper) {
      subtitleWrapper.addEventListener('scroll', handleContentAreaScroll)
    }
  }

  function removeScrollListeners() {
    if (textareaRef.value) {
      textareaRef.value.removeEventListener('scroll', handleContentAreaScroll)
    }

    const subtitleWrapper = document.querySelector('.subtitle-table-wrapper')
    if (subtitleWrapper) {
      subtitleWrapper.removeEventListener('scroll', handleContentAreaScroll)
    }
  }

  // ========== 瀏覽器關閉/重新整理警告 ==========

  // 與路由守衛（onBeforeRouteLeave）共用同一個 hasUnsavedChanges（由 View 以實際
  // DOM 內容計算），避免段落模式編輯中關分頁不跳警告。
  const handleBeforeUnload = (e) => {
    if (hasUnsavedChanges.value) {
      e.preventDefault()
      e.returnValue = ''
      return ''
    }
  }

  // ========== 生命週期 ==========

  onMounted(() => {
    document.body.classList.add('transcript-detail-page')
    window.addEventListener('beforeunload', handleBeforeUnload)

    loadTranscript(route.params.taskId)
    fetchTagColors()

    const timerId = setTimeout(() => {
      if (!isMountedRef.get()) return
      fixSubtitleScrolling()
      setupScrollListeners()
    }, 100)
    scrollRestoreTimersRef.get().push(timerId)
  })

  onUnmounted(() => {
    isMountedRef.set(false)

    clearHighlights()

    scrollRestoreTimersRef.get().forEach(timer => clearTimeout(timer))
    scrollRestoreTimersRef.set([])

    removeScrollListeners()

    window.removeEventListener('beforeunload', handleBeforeUnload)

    document.body.classList.remove('editing-transcript')
    document.body.classList.remove('transcript-detail-page')

    cleanupAudioPlayer()
    cancelPendingRequests()
  })

  // ========== 路由守衛 ==========

  onBeforeRouteLeave((_to, _from, next) => {
    if (hasUnsavedChanges.value) {
      const answer = window.confirm($t('transcriptDetail.confirmLeave'))
      if (answer) {
        next()
      } else {
        next(false)
      }
    } else {
      next()
    }
  })

  // ========== Watchers ==========

  watch(() => route.params.taskId, (newTaskId, oldTaskId) => {
    if (newTaskId && newTaskId !== oldTaskId) {
      if (hasUnsavedChanges.value) {
        const answer = window.confirm($t('transcriptDetail.confirmLeave'))
        if (!answer) {
          router.replace({ name: 'transcript-detail', params: { taskId: oldTaskId } })
          return
        }
      }
      if (isEditing.value) {
        handleCancelEditing()
      }
      loadTranscript(newTaskId)
    }
  })

  watch(isEditing, (editing) => {
    if (editing) {
      document.body.classList.add('editing-transcript')
    } else {
      document.body.classList.remove('editing-transcript')
    }
  })

  watch(
    () => [segments.value, currentTranscript.value.content, displayMode.value, isEditing.value],
    () => {
      if (displayMode.value === 'paragraph' && !isEditing.value && segments.value && currentTranscript.value.content) {
        generateSegmentMarkers(segments.value, currentTranscript.value.content)
      }
    },
    { deep: true }
  )

  watch(displayMode, () => {
    nextTick(() => {
      removeScrollListeners()
      setupScrollListeners()
    })
  })

  return {
    loadTranscript,
  }
}
