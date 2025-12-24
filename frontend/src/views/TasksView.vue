<template>
  <div class="tasks-container">

    <!-- 任務列表 -->
    <TaskList
      :tasks="tasks"
      @download="downloadTask"
      @refresh="refreshTasks"
      @delete="deleteTask"
      @view="viewTranscript"
    />
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted, inject } from 'vue'
import api, { API_BASE, TokenManager } from '../utils/api'
import TaskList from '../components/TaskList.vue'
import { useRouter } from 'vue-router'

// 新 API 服務層
import { transcriptionService, taskService } from '../api/services.js'

const router = useRouter()
const showNotification = inject('showNotification')
const tasks = ref([])
const eventSources = new Map() // SSE 連接管理

// 初始化時載入任務
onMounted(async () => {
  await refreshTasks()
})

// 刷新任務列表
async function refreshTasks() {
  try {
    // 使用新 API 服務層
    const response = await taskService.getActiveList()
    const serverTasks = response.all_tasks || []

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
          console.log(`🔄 刷新任務 ${serverTask.task_id}:`, {
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
              console.log(`✅ 使用本地進度: ${localProgress}%`)
            } else {
              console.log(`⚠️ 使用伺服器進度: ${serverProgress}%`)
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

    // 為正在進行的任務建立 SSE 連接
    tasks.value.forEach(task => {
      if (['pending', 'processing'].includes(task.status)) {
        connectTaskSSE(task.task_id)
      }
    })
  } catch (error) {
    console.error('刷新任務列表失敗:', error)
  }
}

// 下載任務結果
async function downloadTask(taskId) {
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
    console.error('下載失敗:', error)
    alert('下載失敗，請稍後再試')
  }
}

// 刪除任務
async function deleteTask(taskId) {
  if (!confirm('確定要刪除這個任務嗎？')) {
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
    console.error('刪除失敗:', error)
    alert('刪除失敗，請稍後再試')
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
    console.log(`⏭️ 跳過 SSE 連接（已存在）: ${taskId}`)
    return
  }

  const token = TokenManager.getAccessToken()
  if (!token) {
    console.error('❌ 無法建立 SSE 連接：未登入')
    return
  }

  // 創建 SSE 連接（使用新 API 服務層）
  const url = taskService.getEventsUrl(taskId, token)
  const eventSource = new EventSource(url)

  console.log(`🔌 建立 SSE 連接: ${taskId}`)

  eventSource.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data)
      console.log(`📊 SSE 更新 ${taskId}:`, data)

      // 找到對應的任務並更新
      const task = tasks.value.find(t => t.task_id === taskId)
      if (task) {
        const oldStatus = task.status
        console.log(`📊 更新前任務狀態:`, { progress: task.progress, progress_percentage: task.progress_percentage })
        Object.assign(task, data)
        console.log(`📊 更新後任務狀態:`, { progress: task.progress, progress_percentage: task.progress_percentage })

        // 如果任務剛完成，顯示通知
        if (oldStatus !== 'completed' && data.status === 'completed') {
          if (showNotification) {
            showNotification({
              title: '轉錄完成',
              message: `「${task.custom_name || task.filename || task.file?.filename}」已完成`,
              type: 'success',
              duration: 5000
            })
          }
        }

        // 如果任務失敗，顯示通知
        if (oldStatus !== 'failed' && data.status === 'failed') {
          if (showNotification) {
            showNotification({
              title: '轉錄失敗',
              message: `「${task.custom_name || task.filename || task.file?.filename}」轉錄失敗`,
              type: 'error',
              duration: 5000
            })
          }
        }

        // 如果任務已完成、失敗或取消，關閉 SSE 連接
        if (['completed', 'failed', 'cancelled'].includes(data.status)) {
          console.log(`✅ 任務結束（${data.status}），關閉 SSE: ${taskId}`)
          disconnectTaskSSE(taskId)
        }
      }
    } catch (error) {
      console.error('❌ 解析 SSE 數據失敗:', error)
    }
  }

  eventSource.onerror = (error) => {
    console.error(`❌ SSE 連接錯誤: ${taskId}`, error)
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
    eventSource.close()
    eventSources.delete(taskId)
    console.log(`🔌 關閉 SSE: ${taskId}`)
  }
}

// 斷開所有 SSE 連接
function disconnectAllSSE() {
  eventSources.forEach((eventSource, taskId) => {
    eventSource.close()
    console.log(`🔌 關閉 SSE: ${taskId}`)
  })
  eventSources.clear()
}

// 組件卸載時斷開所有連接
onUnmounted(() => {
  disconnectAllSSE()
})
</script>

<style scoped>
.tasks-container {
  max-width: 1400px;
  margin: 0 auto;
}

.tasks-header {
  margin-bottom: 24px;
  text-align: center;
}

.tasks-header h1 {
  font-size: 2rem;
  color: var(--neu-primary);
  margin: 0 0 8px 0;
  font-weight: 700;
}

.tasks-header p {
  color: var(--neu-text-light);
  margin: 0;
  font-size: 1rem;
}
</style>
