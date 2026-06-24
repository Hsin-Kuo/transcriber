<template>
  <div class="tasks-container">
    <!-- 下拉重新整理指示器 -->
    <div
      class="ptr-indicator"
      :class="{ refreshing: isRefreshing, animating: !isPulling }"
      :style="{ transform: `translateY(${isRefreshing ? 0 : Math.min(pullDistance, 48) - 48}px)` }"
    >
      <svg
v-if="!isRefreshing" class="ptr-arrow"
        :style="{ transform: `rotate(${Math.min(180, (pullDistance / 40) * 180)}deg)` }"
        viewBox="0 0 24 24" width="20" height="20" fill="none"
        stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <line x1="12" y1="5" x2="12" y2="19" /><polyline points="19 12 12 19 5 12" />
      </svg>
      <div v-else class="ptr-spinner"></div>
    </div>

    <!-- 任務列表 -->
    <TaskList
      :tasks="displayTasks"
      :current-page="currentPage"
      :total-pages="totalPages"
      @download="downloadTask"
      @refresh="refreshTasks"
      @delete="deleteTask"
      @cancel="cancelTask"
      @view="viewTranscript"
      @page-change="handlePageChange"
      @filter-change="handleFilterChange"
    />

    <!-- 字幕下載對話框 -->
    <DownloadDialog
      :show="showDownloadDialog"
      :time-format="timeFormat"
      :density-threshold="densityThreshold"
      :has-speaker-info="hasSpeakerInfo"
      v-model:selected-format="selectedDownloadFormat"
      v-model:include-speaker="includeSpeaker"
      @close="showDownloadDialog = false"
      @download="performDownload"
    />
  </div>
</template>

<script setup>
import { ref, onBeforeUnmount, onMounted, nextTick, inject, computed } from 'vue'
import api, { TokenManager } from '../utils/api'
import TaskList from '../components/task/TaskListContainer.vue'
import RulerPagination from '../components/common/RulerPagination.vue'
import DownloadDialog from '../components/transcript/DownloadDialog.vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { usePullToRefresh } from '../composables/usePullToRefresh'
import { useAuthStore } from '../stores/auth'
import { useTourStore, TOUR_PHASES, TOUR_ANCHORS, tourSel } from '../stores/tour'
import { useProductTour } from '../composables/useProductTour'
import { buildDemoListTask, DEMO_ID } from '../utils/tourFixtures'

// 新 API 服務層
import { transcriptionService, taskService } from '../api/services'
import { NEW_ENDPOINTS } from '../api/endpoints'

// Composables
import { useSubtitleMode } from '../composables/transcript/useSubtitleMode'
import { useTranscriptDownload } from '../composables/transcript/useTranscriptDownload'

const router = useRouter()
const { t, locale } = useI18n()
const authStore = useAuthStore()
const tourStore = useTourStore()
const tour = useProductTour()
const showNotification = inject('showNotification')
const tasks = ref([])

// 導覽列表 phase：注入一張 demo 卡片（不污染真實資料，狀態由 tourStore 驅動動畫）
const displayTasks = computed(() =>
  tourStore.showDemoCard
    ? [buildDemoListTask(locale.value, tourStore.demoStatus, tourStore.demoProgress), ...tasks.value]
    : tasks.value
)
const eventSources = new Map() // SSE 連接管理
let pollTimer = null // 進行中任務的輪詢備用計時器

// 分頁相關狀態
const currentPage = ref(1)
const pageSize = ref(10)
const totalTasks = ref(0)

// 篩選條件
const currentTaskType = ref(null)
const currentTags = ref([])
const currentHasAudio = ref(null)

// 計算總頁數
const totalPages = computed(() => Math.ceil(totalTasks.value / pageSize.value))

// 字幕下載相關狀態
const currentDownloadTask = ref(null)
const segments = ref([])
const speakerNames = ref({})
const {
  showDownloadDialog,
  selectedDownloadFormat,
  includeSpeaker,
  performSubtitleDownload
} = useTranscriptDownload()

const {
  timeFormat,
  densityThreshold,
  hasSpeakerInfo,
  groupedSegments,
  generateSubtitleText,
  generateSRTText,
  generateVTTText
} = useSubtitleMode(segments)

// 初始化由 TaskListContainer 的 filter-change 事件觸發
// 這確保篩選狀態恢復後才請求數據

const { pullDistance, isPulling, isRefreshing } = usePullToRefresh(() => refreshTasks())

// 刷新任務列表
async function refreshTasks() {
  try {
    // 計算分頁參數
    const skip = (currentPage.value - 1) * pageSize.value

    // 使用新 API 服務層，帶分頁參數和篩選條件
    const params = {
      skip: skip,
      limit: pageSize.value
    }

    // 如果有 task_type 篩選，加入參數
    if (currentTaskType.value) {
      params.task_type = currentTaskType.value
    }

    // 如果有 has_audio 篩選，加入參數
    if (currentHasAudio.value) {
      params.has_audio = currentHasAudio.value
    }

    // 如果有 tags 篩選，加入參數（逗號分隔）
    if (currentTags.value && currentTags.value.length > 0) {
      params.tags = currentTags.value.join(',')
    }

    const response = await taskService.list(params)

    const serverTasks = response.tasks || []
    totalTasks.value = response.total || 0

    // 保留本地狀態（cancelling 狀態和 SSE 更新的進度信息）
    const localStates = new Map()
    tasks.value.forEach(task => {
      localStates.set(task.task_id, {
        cancelling: task.cancelling,
        progress: task.progress,
        progress_percentage: task.progress_percentage
      })
    })

    // 用伺服器任務列表替換本地列表，但保留本地狀態
    tasks.value = serverTasks.map(serverTask => {
      const localState = localStates.get(serverTask.task_id)

      // 合併伺服器數據和本地狀態
      const mergedTask = { ...serverTask }

      if (localState) {
        // 恢復 cancelling 狀態
        if (localState.cancelling) {
          mergedTask.cancelling = localState.cancelling
        }

        // 保留 SSE 更新的進度信息
        // 只有當任務仍在進行中時才保留本地進度
        if (['pending', 'processing'].includes(serverTask.status)) {
          console.log(`🔄 Refreshing task ${serverTask.task_id}:`, {
            本地進度: { progress: localState.progress, percentage: localState.progress_percentage },
            伺服器進度: { progress: serverTask.progress, percentage: serverTask.progress_percentage }
          })

          // 優先使用本地 SSE 更新的進度（因為 SSE 更即時）
          // 如果本地有進度信息，就使用本地的
          if (localState.progress) {
            mergedTask.progress = localState.progress
          }
          if (localState.progress_percentage !== undefined && localState.progress_percentage !== null) {
            // 只有當本地進度更大時才使用本地的，或者伺服器沒有進度時
            const serverProgress = serverTask.progress_percentage
            const localProgress = localState.progress_percentage
            if (serverProgress === undefined || serverProgress === null || localProgress > serverProgress) {
              mergedTask.progress_percentage = localProgress
              console.log(`✅ Using local progress: ${localProgress}%`)
            } else {
              console.log(`⚠️ Using server progress: ${serverProgress}%`)
            }
          }
        }
      }

      // 如果是 completed，確保有下載連結
      if (mergedTask.status === 'completed' && !mergedTask.download_url) {
        mergedTask.has_download = true
      }

      return mergedTask
    })

    // 獲取當前頁面的任務 ID 列表
    const currentTaskIds = new Set(tasks.value.map(task => task.task_id))

    // 關閉不在當前頁面的 SSE 連接
    eventSources.forEach((eventSource, taskId) => {
      if (!currentTaskIds.has(taskId)) {
        console.log(`📄 任務 ${taskId} 不在當前頁面，關閉 SSE 連接`)
        disconnectTaskSSE(taskId)
      }
    })

    // 為正在進行的任務建立 SSE 連接，並啟動輪詢備用
    const hasActiveTasks = tasks.value.some(task => ['pending', 'processing'].includes(task.status))
    tasks.value.forEach(task => {
      if (['pending', 'processing'].includes(task.status)) {
        connectTaskSSE(task.task_id)
      }
    })
    if (hasActiveTasks) {
      startPollTimer()
    } else {
      stopPollTimer()
    }
  } catch (error) {
    console.error('Failed to refresh task list:', error)
  }
}

// 處理頁面切換
function handlePageChange(newPage) {
  currentPage.value = newPage
  refreshTasks()
}

// 處理篩選條件變更
function handleFilterChange(filter) {
  currentTaskType.value = filter.taskType
  currentTags.value = filter.tags
  currentHasAudio.value = filter.hasAudio
  // 篩選條件改變時，重置到第一頁
  currentPage.value = 1
  refreshTasks()
}

// 下載任務結果
async function downloadTask(task) {
  // 如果是字幕類型，顯示下載對話框
  if (task.task_type === 'subtitle') {
    await openSubtitleDownloadDialog(task)
  } else {
    // 段落類型，直接下載 TXT
    await downloadParagraphTask(task.task_id)
  }
}

// 下載段落類型任務
async function downloadParagraphTask(taskId) {
  try {
    // 使用新 API 服務層
    const response = await transcriptionService.download(taskId)

    const task = tasks.value.find(t => t.task_id === taskId)
    const filename = task?.custom_name
      ? `${task.custom_name}.txt`
      : `transcription_${taskId}.txt`

    const url = window.URL.createObjectURL(new Blob([response.data]))
    const link = document.createElement('a')
    link.href = url
    link.setAttribute('download', filename)
    document.body.appendChild(link)
    link.click()
    link.remove()
    window.URL.revokeObjectURL(url)
  } catch (error) {
    console.error('Download failed:', error)
    alert(t('tasksView.downloadFailed'))
  }
}

// 開啟字幕下載對話框
async function openSubtitleDownloadDialog(task) {
  try {
    // 載入 segments 和講者名稱
    const response = await api.get(NEW_ENDPOINTS.transcriptions.segments(task.task_id))
    segments.value = response.data.segments || []
    speakerNames.value = response.data.speaker_names || {}

    // 儲存當前任務資訊
    currentDownloadTask.value = task

    // 顯示對話框
    showDownloadDialog.value = true
  } catch (error) {
    console.error('Failed to load subtitle data:', error)
    alert(t('tasksView.loadSubtitleFailed'))
  }
}

// 執行字幕下載
function performDownload() {
  if (!currentDownloadTask.value) return

  const speakerNamesToUse = includeSpeaker.value ? speakerNames.value : null
  const filename = currentDownloadTask.value.custom_name || currentDownloadTask.value.filename || 'transcript'

  let content = ''
  const format = selectedDownloadFormat.value

  // 根據選擇的格式生成對應的內容
  if (format === 'srt') {
    content = generateSRTText(groupedSegments.value, speakerNamesToUse)
  } else if (format === 'vtt') {
    content = generateVTTText(groupedSegments.value, speakerNamesToUse)
  } else {
    // TXT 格式：使用當前時間格式設定
    content = generateSubtitleText(groupedSegments.value, timeFormat.value, speakerNamesToUse)
  }

  performSubtitleDownload(content, filename, format)
}

// 取消任務
async function cancelTask(taskId) {
  try {
    console.log('🚫 Cancelling task:', taskId)

    // 立即更新 UI 顯示取消中狀態
    const task = tasks.value.find(t => t.task_id === taskId)
    if (task) {
      task.cancelling = true
    }

    // 調用取消 API
    await taskService.cancel(taskId)

    console.log('✅ Task cancelled:', taskId)

    // 刷新任務列表以獲取最新狀態
    await refreshTasks()
  } catch (error) {
    console.error('Failed to cancel task:', error)

    // 取消失敗，恢復 UI 狀態
    const task = tasks.value.find(t => t.task_id === taskId)
    if (task) {
      task.cancelling = false
    }

    showNotification?.({ title: t('tasksView.cancelFailed'), type: 'error' })
  }
}

// 刪除任務
async function deleteTask(taskId) {
  if (!confirm(t('tasksView.confirmDeleteTask'))) {
    return
  }

  try {
    // 使用新 API 服務層
    await taskService.delete(taskId)

    const index = tasks.value.findIndex(t => t.task_id === taskId)
    if (index !== -1) {
      tasks.value.splice(index, 1)
    }
  } catch (error) {
    console.error('Delete failed:', error)
    alert(t('tasksView.deleteFailed'))
  }
}

// 查看逐字稿 - 導航到詳情頁面
function viewTranscript(taskId) {
  router.push(`/transcript/${taskId}`)
}

// SSE 實時更新任務狀態
function connectTaskSSE(taskId) {
  // 如果已經有連接，不要重複建立
  if (eventSources.has(taskId)) {
    console.log(`⏭️ Skipping SSE connection (already exists): ${taskId}`)
    return
  }

  const token = TokenManager.getAccessToken()
  if (!token) {
    console.error('Cannot establish SSE connection: Not logged in')
    return
  }

  // 創建 SSE 連接（使用新 API 服務層）
  const url = taskService.getEventsUrl(taskId, token)
  const eventSource = new EventSource(url)

  console.log(`🔌 Establishing SSE connection: ${taskId}`)

  eventSource.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data)
      console.log(`📊 SSE update ${taskId}:`, data)

      // 找到對應的任務並更新
      const task = tasks.value.find(t => t.task_id === taskId)
      if (task) {
        const oldStatus = task.status
        console.log(`📊 更新前任務狀態:`, { progress: task.progress, progress_percentage: task.progress_percentage })
        Object.assign(task, data)
        console.log(`📊 更新後任務狀態:`, { progress: task.progress, progress_percentage: task.progress_percentage })

        // 如果任務剛完成，顯示通知 + 重抓使用者額度（後端已扣時數，否則 UI 需手動 refresh 才更新）
        if (oldStatus !== 'completed' && data.status === 'completed') {
          authStore.fetchCurrentUser()
          if (showNotification) {
            showNotification({
              title: t('tasksView.transcriptionComplete'),
              message: t('tasksView.transcriptionCompleteMessage', { name: task.custom_name || task.filename || task.file?.filename }),
              type: 'success'
            })
          }
        }

        // 如果任務失敗，顯示通知
        if (oldStatus !== 'failed' && data.status === 'failed') {
          if (showNotification) {
            showNotification({
              title: t('tasksView.transcriptionFailed'),
              message: t('tasksView.transcriptionFailedMessage', { name: task.custom_name || task.filename || task.file?.filename }),
              type: 'error'
            })
          }
        }

        // 如果任務已完成、失敗或取消，關閉 SSE 連接
        if (['completed', 'failed', 'cancelled'].includes(data.status)) {
          console.log(`✅ Task ended (${data.status}), closing SSE: ${taskId}`)
          disconnectTaskSSE(taskId)
        }
      }
    } catch (error) {
      console.error('Failed to parse SSE data:', error)
    }
  }

  eventSource.onerror = (error) => {
    console.error(`SSE 連接錯誤: ${taskId}`, error)
    if (eventSource.readyState === EventSource.CLOSED) {
      console.log(`🔌 SSE 連接已關閉: ${taskId}`)
      disconnectTaskSSE(taskId)
    }
  }

  eventSources.set(taskId, eventSource)
}

// 斷開 SSE 連接
function disconnectTaskSSE(taskId) {
  const eventSource = eventSources.get(taskId)
  if (eventSource) {
    // 在關閉前移除事件監聽器，避免觸發錯誤
    eventSource.onmessage = null
    eventSource.onerror = null
    eventSource.close()
    eventSources.delete(taskId)
    console.log(`🔌 關閉 SSE: ${taskId}`)
  }
}

// 斷開所有 SSE 連接
function disconnectAllSSE() {
  eventSources.forEach((eventSource, taskId) => {
    // 移除事件監聽器，避免觸發錯誤
    eventSource.onmessage = null
    eventSource.onerror = null
    eventSource.close()
    console.log(`🔌 關閉 SSE: ${taskId}`)
  })
  eventSources.clear()
}

// 輪詢備用：當有進行中任務時，每 5 秒直接查 API 更新進度
// 確保即使 SSE 被 Cloudflare/nginx 緩衝，進度仍能更新
function startPollTimer() {
  if (pollTimer) return
  pollTimer = setInterval(async () => {
    const activeTasks = tasks.value.filter(t => ['pending', 'processing'].includes(t.status))
    if (activeTasks.length === 0) {
      stopPollTimer()
      return
    }
    for (const t of activeTasks) {
      try {
        const response = await taskService.get(t.task_id)
        const updated = response.task || response
        const taskInList = tasks.value.find(lt => lt.task_id === t.task_id)
        if (taskInList && updated.progress) {
          taskInList.progress = updated.progress
          if (updated.progress_percentage != null) {
            taskInList.progress_percentage = updated.progress_percentage
          }
          if (updated.status !== taskInList.status) {
            const wasCompleted = taskInList.status === 'completed'
            taskInList.status = updated.status
            // SSE 被緩衝時的備援：完成才扣時數，重抓額度讓 UI 同步
            if (!wasCompleted && updated.status === 'completed') {
              authStore.fetchCurrentUser()
            }
          }
        }
      } catch (_) { /* ignore */ }
    }
  }, 5000)
}

function stopPollTimer() {
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
}

// === 新手導覽（方案 C）：列表 phase ===

// demo 卡片「轉錄中 → 完成」動畫的計時器
let demoTimers = []
function animateDemoCard() {
  tourStore.setDemoStatus('processing', 10)
  demoTimers.push(setTimeout(() => tourStore.setDemoStatus('processing', 45), 500))
  demoTimers.push(setTimeout(() => tourStore.setDemoStatus('processing', 80), 1000))
  demoTimers.push(setTimeout(() => tourStore.setDemoStatus('completed', 100), 1600))
}
function clearDemoTimers() {
  demoTimers.forEach(clearTimeout)
  demoTimers = []
}

function buildListSteps() {
  return [
    {
      element: tourSel(TOUR_ANCHORS.DEMO_CARD),
      popover: {
        title: t('tour.list.title'),
        description: t('tour.list.desc'),
        doneBtnText: t('tour.toDetail'),
        // 列表 phase 最後一步：交棒到詳情 phase
        onNextClick: () =>
          tour.advanceTo(tourStore, router, TOUR_PHASES.DETAIL, `/transcript/${DEMO_ID}`),
      },
    },
  ]
}

async function maybeRunListTour() {
  if (!tourStore.active || tourStore.phase !== TOUR_PHASES.LIST) return
  tourStore.endAdvance() // 已抵達列表頁
  animateDemoCard()
  await nextTick() // 等 demo 卡片渲染出來，data-tour 錨點才存在
  // 換頁到詳情 phase 時不收尾；使用者關閉則清計時器並結束導覽
  tour.run({
    steps: buildListSteps(),
    t,
    onDestroyed: tour.makeDestroyHandler(tourStore, clearDemoTimers),
  })
}

onMounted(() => {
  maybeRunListTour()
})

// 組件卸載前斷開所有連接
onBeforeUnmount(() => {
  console.log('🔌 組件即將卸載，關閉所有 SSE 連接')
  disconnectAllSSE()
  stopPollTimer()
  clearDemoTimers()
  // 離開頁面時若列表導覽仍在跑，強制收掉避免殘留 overlay
  tour.getDriver()?.destroy?.()
})
</script>

<style scoped>
.tasks-container {
  max-width: 900px;
  margin: 0 auto;
  padding: 0 var(--spacing-md, 16px);
}

.ptr-indicator {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  height: 48px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--main-bg, #fff);
  z-index: 200;
  will-change: transform;
}

.ptr-indicator.animating {
  transition: transform 0.3s ease;
}

@media (min-width: 769px) {
  .ptr-indicator { display: none; }
}

.ptr-arrow {
  color: var(--main-text-light);
  transition: transform 0.2s ease;
}

.ptr-spinner {
  width: 22px;
  height: 22px;
  border: 2px solid var(--main-text-light);
  border-top-color: var(--main-primary);
  border-radius: 50%;
  animation: ptr-spin 0.7s linear infinite;
}

@keyframes ptr-spin {
  to { transform: rotate(360deg); }
}

.tasks-header {
  margin-bottom: 24px;
  text-align: center;
}

.tasks-header h1 {
  font-size: 2rem;
  color: var(--main-primary);
  margin: 0 0 8px 0;
  font-weight: 700;
}

.tasks-header p {
  color: var(--main-text-light);
  margin: 0;
  font-size: 1rem;
}

/* 平板以下 */
@media (max-width: 768px) {
  .tasks-container {
    padding: 0 var(--spacing-sm, 12px);
  }

  .tasks-header h1 {
    font-size: 1.5rem;
  }

  .tasks-header p {
    font-size: 0.9rem;
  }
}

/* 小手機 */
@media (max-width: 480px) {
  .tasks-container {
    padding: 0 var(--spacing-xs, 8px);
  }

  .tasks-header {
    margin-bottom: 16px;
  }

  .tasks-header h1 {
    font-size: 1.25rem;
  }
}
</style>
