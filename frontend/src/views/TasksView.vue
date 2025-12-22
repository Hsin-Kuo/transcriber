<template>
  <div class="tasks-container">
    <div class="tasks-header">
      <h1>所有任務</h1>
      <p>查看和管理您的轉錄任務</p>
    </div>

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
import { ref, onMounted, onUnmounted } from 'vue'
import api from '../utils/api'
import TaskList from '../components/TaskList.vue'
import { useRouter } from 'vue-router'

const router = useRouter()
const tasks = ref([])

// 初始化時載入任務
onMounted(async () => {
  await refreshTasks()

  // 設定自動刷新
  const interval = setInterval(() => {
    refreshTasks()
  }, 10000) // 每 10 秒刷新一次

  // 儲存 interval ID 以便清理
  onUnmounted(() => {
    clearInterval(interval)
  })
})

// 刷新任務列表
async function refreshTasks() {
  try {
    const response = await api.get('/transcribe/active/list')
    const serverTasks = response.data.all_tasks || []

    // 保留 cancelling 狀態
    const cancellingStates = new Map()
    tasks.value.forEach(task => {
      if (task.cancelling) {
        cancellingStates.set(task.task_id, task.cancelling)
      }
    })

    // 用伺服器任務列表替換本地列表
    tasks.value = serverTasks.map(serverTask => {
      // 恢復 cancelling 狀態（如果有）
      if (cancellingStates.has(serverTask.task_id)) {
        return { ...serverTask, cancelling: cancellingStates.get(serverTask.task_id) }
      }

      // 如果是 completed，確保有下載連結
      if (serverTask.status === 'completed' && !serverTask.download_url) {
        return { ...serverTask, has_download: true }
      }

      return serverTask
    })
  } catch (error) {
    console.error('刷新任務列表失敗:', error)
  }
}

// 下載任務結果
async function downloadTask(taskId) {
  try {
    const response = await api.get(`/transcribe/${taskId}/download`, {
      responseType: 'blob'
    })

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
    await api.delete(`/transcribe/${taskId}`)

    const index = tasks.value.findIndex(t => t.task_id === taskId)
    if (index !== -1) {
      tasks.value.splice(index, 1)
    }
  } catch (error) {
    console.error('刪除失敗:', error)
    alert('刪除失敗，請稍後再試')
  }
}

// 查看逐字稿（保留此功能，可能需要打開詳情對話框）
function viewTranscript(taskId) {
  // 這裡可以導航到詳情頁面，或者在未來實現對話框
  console.log('查看任務:', taskId)
  // 暫時不實現，可以在未來添加
}
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
